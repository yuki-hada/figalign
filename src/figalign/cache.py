"""Cache keys for the three layers of spec 5.1.

The layers differ in what invalidates them, so they must not share a key. Keying on the
file's mtime -- the obvious choice -- is wrong: it makes a one-character edit to a panel
function re-run the data load, which is the exact cost the layering exists to avoid.

So the key is the *source* of the thing that actually ran:

| layer   | key                                                          |
|---------|--------------------------------------------------------------|
| data    | source of load_data + module-level source of its file        |
| drawing | source of the panel function + data version + settled size   |

Module-level source is included in the data key because imports and constants are the
"shared code" of spec 5.1: changing them has to invalidate the load.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

UNKNOWN = "?"


def digest(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def source_hash(fn: Callable[..., Any]) -> str:
    """Hash a function's own source. Falls back to a miss-every-time sentinel."""
    try:
        return digest(inspect.getsource(fn))
    except (OSError, TypeError):
        return UNKNOWN


def module_scope_hash(path: Path) -> str:
    """Hash everything in a file except the bodies of its top-level functions.

    Imports, constants and classes are kept; `def scatter_main(...)` is not. Editing a
    panel function therefore leaves this hash untouched.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return UNKNOWN

    lines = source.splitlines(keepends=True)
    skip: set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            skip.update(range(start - 1, (node.end_lineno or node.lineno)))
    return digest("".join(ln for i, ln in enumerate(lines) if i not in skip))


class LruCache(Generic[K, V]):
    """Small bounded cache. Renders are ~50KB of SVG each, so this must not grow forever."""

    def __init__(self, capacity: int = 64):
        self.capacity = capacity
        self._items: OrderedDict[K, V] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: K) -> V | None:
        if key in self._items:
            self._items.move_to_end(key)
            self.hits += 1
            return self._items[key]
        self.misses += 1
        return None

    def put(self, key: K, value: V) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
