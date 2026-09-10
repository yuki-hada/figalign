"""Load panel functions and data from .py files on disk.

Every reference has the form `"<file>:<callable>"`. The single source of truth is the file
on disk; this tool never writes code back (spec 3.4).

Modules are cached by mtime so that repeated requests do not re-execute the file. What the
data layer is keyed on is *source*, not mtime -- see cache.py for why.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .cache import digest, module_scope_hash, source_hash

DATA_HOOK = "load_data"  # if panels.py defines this, its return value becomes `data`

_modules: dict[Path, tuple[float, ModuleType]] = {}
# (file, callable) -> (key of what produced it, value)
_data: dict[tuple[Path, str], tuple[str, Any]] = {}
# Bumped when something we cannot hash changes, e.g. a .csv the loader reads. It takes part
# in the data key so that everything downstream is invalidated with it.
_epoch = 0


class PanelRefError(ValueError):
    """The panel reference string is malformed."""


def split_ref(ref: str) -> tuple[str, str]:
    """Split `"panels.py:scatter_main"` into `("panels.py", "scatter_main")`."""
    file, sep, name = ref.partition(":")
    if not sep or not file or not name:
        raise PanelRefError(f"cannot read the reference {ref!r} (expected 'panels.py:scatter_main')")
    return file, name


def load_module(root: Path, rel_path: str) -> ModuleType:
    """Import `root / rel_path`, re-executing it when the mtime has changed."""
    path = (root / rel_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    mtime = path.stat().st_mtime
    cached = _modules.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    # Deliberately not registered in sys.modules: the same file is re-imported many times,
    # so build a fresh module object each time instead of polluting the global namespace.
    mod_name = f"_figalign_user_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None:
        raise ImportError(f"cannot import: {path}")
    module = importlib.util.module_from_spec(spec)

    # Compile the source here rather than calling spec.loader.exec_module().
    # A .pyc records the source mtime with one-second resolution and validates on
    # (mtime, size), so an edit landing in the same second that keeps the file length
    # -- "n = 400" -> "n = 401", a colour, a bin count -- serves stale bytecode. That is
    # exactly the edit shape live reloading has to survive, so never go through the cache.
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")

    # Let panel code import its own sibling modules.
    root_str = str(root.resolve())
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        exec(code, module.__dict__)
    finally:
        if inserted:
            sys.path.remove(root_str)

    _modules[path] = (mtime, module)
    return module


def load_callable(root: Path, ref: str) -> Callable[..., Any]:
    """Resolve `"panels.py:scatter_main"` to a callable."""
    rel_path, name = split_ref(ref)
    module = load_module(root, rel_path)
    try:
        fn = getattr(module, name)
    except AttributeError:
        raise AttributeError(f"{rel_path} has no {name}") from None
    if not callable(fn):
        raise TypeError(f"{ref} is not callable ({type(fn).__name__})")
    return fn


def load_data(root: Path, ref: str | None) -> Any:
    """The data layer. Returns None when `ref` is None.

    The result is held until the source of `load_data` itself, or the module-level source of
    its file, changes. Editing a panel function does not re-run it (spec 5.1).
    """
    if ref is None:
        return None
    rel_path, name = split_ref(ref)
    path = (root / rel_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    fn = load_callable(root, ref)
    key = (path, name)
    version = data_version(path, fn)

    cached = _data.get(key)
    if cached is not None and cached[0] == version:
        return cached[1]

    value = fn()
    _data[key] = (version, value)
    return value


def data_version(path: Path, fn: Callable[..., Any]) -> str:
    """The data layer's cache key: the loader's own source plus its file's module scope."""
    return digest(source_hash(fn), module_scope_hash(path), _epoch)


def current_data_version(root: Path, ref: str | None) -> str:
    """The data key without loading anything, for use in the drawing layer's key."""
    if ref is None:
        return digest("no-data", _epoch)
    rel_path, name = split_ref(ref)
    path = (root / rel_path).resolve()
    try:
        return data_version(path, load_callable(root, ref))
    except (FileNotFoundError, AttributeError, TypeError, ImportError, SyntaxError):
        return digest("unloadable", _epoch)


def invalidate_data() -> None:
    """Force the data layer to re-run. Called when an input we cannot hash has changed."""
    global _epoch
    _epoch += 1
    _data.clear()


def find_data_ref(root: Path, module_path: str) -> str | None:
    """Return the reference string if `module_path` defines `load_data()`."""
    try:
        module = load_module(root, module_path)
    except (FileNotFoundError, ImportError):
        return None
    if callable(getattr(module, DATA_HOOK, None)):
        return f"{module_path}:{DATA_HOOK}"
    return None


def clear_cache() -> None:
    _modules.clear()
    _data.clear()
