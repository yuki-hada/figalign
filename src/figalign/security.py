"""Two separate questions, kept separate.

**Who may talk to the server.** Reaching the HTTP API is enough to run code: a client can
write a `.py` into the project and point `fig.toml` at it, and the next render executes it.
So the API carries a token. The default bind is loopback, but on a shared machine loopback
is not private -- anyone logged into the same node can reach 127.0.0.1 -- and that is the
setup the README suggests for keeping the server next to the data.

**Whose code this is.** Executing `panels.py` is not a risk to be mitigated, it is the
entire point, the same as running `python panels.py`. What the tool cannot decide is whether
the directory came from you or from someone else, so it asks once per directory and
remembers. Hashing the file would answer a different and far less useful question.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TOKEN_ENV = "FIGALIGN_TOKEN"
TOKEN_QUERY = "token"
TOKEN_COOKIE = "figalign_token"
TOKEN_HEADER = "x-figalign-token"

LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


def new_token() -> str:
    """Use the token from the environment when given, so a wrapper script can fix it."""
    return os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24)


def is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK


# --- trust ------------------------------------------------------------------

def _store() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "figalign" / "trusted.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_trusted(root: Path) -> bool:
    return str(root.resolve()) in _load()


def trust(root: Path) -> None:
    """Record the decision outside the project.

    Deliberately not a file inside the directory: a directory that has to earn trust must
    not be able to vouch for itself.
    """
    data = _load()
    data[str(root.resolve())] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def forget(root: Path) -> bool:
    data = _load()
    if data.pop(str(root.resolve()), None) is None:
        return False
    _store().write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return True


@dataclass(frozen=True)
class TrustDecision:
    granted: bool
    reason: str


def executable_files(root: Path) -> list[str]:
    """The .py files in the project, which are what a render can end up executing."""
    root = root.resolve()
    out = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__", ".pixi", ".venv", ".git"} for part in path.parts):
            continue
        out.append(str(path.relative_to(root)))
    return out


def ensure_trusted(root: Path, assume_yes: bool = False) -> TrustDecision:
    """Ask once per directory whether its code may run."""
    root = root.resolve()
    if is_trusted(root):
        return TrustDecision(True, "already trusted")
    if assume_yes:
        trust(root)
        return TrustDecision(True, "accepted with --trust")

    files = executable_files(root)
    print(f"figalign: {root}")
    print("  Rendering this figure runs the Python in this directory:")
    for name in files[:10]:
        print(f"    {name}")
    if len(files) > 10:
        print(f"    ... and {len(files) - 10} more")
    if not files:
        print("    (no .py files yet; panels added later will run too)")

    if not sys.stdin.isatty():
        print("  Not a terminal, so there is nobody to ask. Pass --trust to accept.")
        return TrustDecision(False, "no tty and no --trust")

    answer = input("  Run code from this directory? [y/N] ").strip().lower()
    if answer in {"y", "yes"}:
        trust(root)
        return TrustDecision(True, "accepted")
    return TrustDecision(False, "declined")
