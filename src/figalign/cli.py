"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

FORMATS = {".pdf", ".svg", ".png"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="figalign", description="lay out paper figures at true physical size")
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        type=Path,
        help="directory holding fig.toml (default: the current one)",
    )
    parser.add_argument(
        "-o",
        "--export",
        type=Path,
        metavar="FILE",
        help="write the figure out and exit instead of serving (.pdf / .svg / .png)",
    )
    parser.add_argument(
        "--keep-text",
        action="store_true",
        help="keep text as text in the PDF instead of outlining it",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    if args.export is not None:
        return _export(root, args.export, keep_text=args.keep_text, parser=parser)

    from .server import serve

    print(f"figalign: {root}  ->  http://{args.host}:{args.port}")
    serve(root, host=args.host, port=args.port)
    return 0


def _export(
    root: Path, target: Path, keep_text: bool, parser: argparse.ArgumentParser
) -> int:
    suffix = target.suffix.lower()
    if suffix not in FORMATS:
        parser.error(f"unsupported format: {suffix or '(no suffix)'} ({', '.join(sorted(FORMATS))})")

    from . import figspec
    from .export import ExportError, to_pdf, to_png
    from .figure import build_figure

    try:
        spec = figspec.load_spec(root)
        # Only the PDF route outlines text; SVG stays editable (spec 9).
        result = build_figure(spec, text_as_paths=(suffix == ".pdf" and not keep_text))
        if suffix == ".svg":
            target.write_text(result.svg, encoding="utf-8")
        elif suffix == ".pdf":
            target.write_bytes(to_pdf(result.svg))
        else:
            target.write_bytes(to_png(result.svg))
    except (FileNotFoundError, ValueError, ExportError) as exc:
        print(f"figalign: {exc}", file=sys.stderr)
        return 1

    print(
        f"figalign: {target} ({result.layout.width_mm:.2f} x "
        f"{result.layout.height_mm:.2f} mm, {target.stat().st_size} bytes)"
    )
    if result.errors:
        print(f"figalign: panels that failed to draw: {', '.join(sorted(result.errors))}", file=sys.stderr)
        return 1
    if not result.converged:
        print("figalign: axes alignment did not converge; drew with the largest margins seen", file=sys.stderr)
    return 0
