"""File watching and the change broadcast.

The dev server metaphor of spec 2: an edit on disk shows up in the browser. Everything is
driven from the file system, so an edit made in VS Code and an edit made in the built-in
editor travel exactly the same path (spec 3.4). There is no separate "save from the UI"
route to keep in sync.

Each change is classified into the layer it invalidates (spec 5.1), which is also what the
status line in the preview reports.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from . import loader
from .figspec import FIG_TOML
from .render import clear_render_cache

IGNORED_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints", ".serena"}
DEBOUNCE_MS = 120
STEP_MS = 40

LAYOUT, CODE, DATA = "layout", "code", "data"


@dataclass(frozen=True)
class Change:
    scope: str  # LAYOUT | CODE | DATA
    paths: tuple[str, ...]


def classify(paths: Iterable[Path], root: Path) -> Change:
    """Decide which layer a batch of changes invalidates.

    A change to anything that is not a declaration or code is treated as a data change:
    figalign cannot hash a .csv it has never read, so the data layer is dropped outright.
    """
    rel = tuple(sorted(_relative(p, root) for p in paths))
    suffixes = {p.suffix for p in paths}
    names = {p.name for p in paths}

    if names == {FIG_TOML}:
        return Change(LAYOUT, rel)
    if suffixes and suffixes <= {".py", ".toml", ".svg"}:
        return Change(CODE, rel)
    return Change(DATA, rel)


def apply(change: Change) -> None:
    """Invalidate what the change reaches.

    Source-keyed caches sort themselves out on the next request; only the caches that are
    keyed on something unhashable have to be dropped by hand here.
    """
    if change.scope == DATA:
        loader.invalidate_data()
        clear_render_cache()


def is_interesting(path: Path) -> bool:
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    return not path.name.startswith(".")


async def watch(
    root: Path,
    on_change: Callable[[Change], Awaitable[Any]],
    stop: asyncio.Event | None = None,
) -> None:
    """Watch `root` and hand every batch of changes to `on_change`."""
    from watchfiles import awatch

    async for batch in awatch(
        root,
        debounce=DEBOUNCE_MS,
        step=STEP_MS,
        stop_event=stop,
        recursive=True,
    ):
        paths = [Path(p) for _, p in batch]
        paths = [p for p in paths if is_interesting(p.relative_to(root) if p.is_relative_to(root) else p)]
        if not paths:
            continue
        change = classify(paths, root)
        apply(change)
        await on_change(change)


class Hub:
    """The set of connected previews. Broadcast is best effort: a dead socket is dropped."""

    def __init__(self) -> None:
        self._clients: set[Any] = set()

    def add(self, client: Any) -> None:
        self._clients.add(client)

    def discard(self, client: Any) -> None:
        self._clients.discard(client)

    def __len__(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except Exception:
                self.discard(client)


@contextlib.asynccontextmanager
async def watching(root: Path, hub: Hub):
    """Run the watcher for the lifetime of the app."""
    stop = asyncio.Event()

    async def notify(change: Change) -> None:
        await hub.broadcast(
            {"kind": "change", "scope": change.scope, "paths": list(change.paths)}
        )

    task = asyncio.create_task(watch(root, notify, stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
