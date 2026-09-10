"""Reading and writing the project's own files.

The UI edits files and nothing else (spec 3.4): there is no separate "save from the editor"
path that could drift from what the file watcher sees. An edit made here and an edit made in
VS Code are the same event.

Two things are not optional here.

Path validation, because the server can be exposed with `--host` and a naive handler would
happily write to `../../.ssh/authorized_keys`.

A precondition on writes, because the editor holds a buffer while the file may be changing
underneath it. Writing unconditionally would silently discard whatever the other editor did.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

EDITABLE_SUFFIXES = {".py", ".toml", ".svg"}
# How many previous versions of each file to keep for undo. Snapshots are whole files --
# they are text, so nothing cleverer is needed (spec 7.2) -- and they live in memory only,
# so restarting the server drops them.
SNAPSHOT_DEPTH = 50

_snapshots: dict[Path, list[str]] = {}


class FileAccessError(ValueError):
    """The path is not something this project may read or write."""


class ConflictError(RuntimeError):
    """The file changed on disk since the caller last read it."""

    def __init__(self, path: str, expected: str, actual: str):
        self.path, self.expected, self.actual = path, expected, actual
        super().__init__(
            f"{path} changed on disk (read as {expected[:8]}, now {actual[:8]})"
        )


@dataclass(frozen=True)
class FileState:
    path: str  # relative to the project root
    text: str
    digest: str
    undo_depth: int


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve(root: Path, relative: str) -> Path:
    """Turn a client-supplied relative path into a path inside the project, or refuse."""
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise FileAccessError(f"unusable path: {relative!r}")

    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise FileAccessError(f"points outside the project: {relative!r}")

    root = root.resolve()
    # resolve() follows symlinks, so a link pointing outside the project fails the next check
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise FileAccessError(f"points outside the project: {relative!r}")
    if path.suffix.lower() not in EDITABLE_SUFFIXES:
        allowed = ", ".join(sorted(EDITABLE_SUFFIXES))
        raise FileAccessError(f"not an editable suffix: {path.suffix or '(none)'} (allowed: {allowed})")
    return path


def read(root: Path, relative: str) -> FileState:
    path = resolve(root, relative)
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {relative}")
    text = path.read_text(encoding="utf-8")
    return FileState(
        path=relative,
        text=text,
        digest=digest_of(text),
        undo_depth=len(_snapshots.get(path, ())),
    )


def write(root: Path, relative: str, text: str, if_match: str | None) -> FileState:
    """Write `text`, refusing if the file no longer matches `if_match`.

    `if_match` of None forces the write; the UI always sends the digest it last read.
    """
    path = resolve(root, relative)
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    actual = digest_of(current)
    if if_match is not None and if_match != actual:
        raise ConflictError(relative, if_match, actual)

    if current != text:
        _push_snapshot(path, current)
        path.write_text(text, encoding="utf-8")
    return FileState(
        path=relative,
        text=text,
        digest=digest_of(text),
        undo_depth=len(_snapshots.get(path, ())),
    )


def undo(root: Path, relative: str) -> FileState:
    """Restore the version before the last write."""
    path = resolve(root, relative)
    history = _snapshots.get(path)
    if not history:
        raise FileAccessError(f"no history to restore for {relative} (snapshots live in the server only and are lost on restart)")
    previous = history.pop()
    path.write_text(previous, encoding="utf-8")
    return FileState(
        path=relative,
        text=previous,
        digest=digest_of(previous),
        undo_depth=len(history),
    )


def definition_line(root: Path, relative: str, name: str) -> int | None:
    """The line where `name` is defined, so a tab can open its file at the right place.

    A panel tab shows the whole file rather than a slice of it: slicing means writing back
    into a range, and a half-typed edit can make the range impossible to locate. Scrolling
    to the definition gives the same navigation without that risk.
    """
    try:
        tree = ast.parse(resolve(root, relative).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, FileAccessError):
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.lineno
    return None


def _push_snapshot(path: Path, text: str) -> None:
    history = _snapshots.setdefault(path, [])
    history.append(text)
    del history[:-SNAPSHOT_DEPTH]


def clear_snapshots() -> None:
    _snapshots.clear()
