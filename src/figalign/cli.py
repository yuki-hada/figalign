"""Command line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="figalign", description="論文figureを実寸で並べる")
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        type=Path,
        help="fig.toml があるディレクトリ (既定: カレント)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    if not root.is_dir():
        parser.error(f"ディレクトリが無い: {root}")

    from .server import serve

    print(f"figalign: {root}  ->  http://{args.host}:{args.port}")
    serve(root, host=args.host, port=args.port)
    return 0
