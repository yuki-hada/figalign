"""Final output (spec 9).

SVG is the preview format and stays editable: text is kept as `<text>`, so it can be opened
in Illustrator and it is small. PDF is the deliverable, and there the text is outlined by
matplotlib before cairosvg ever sees it.

That second point is the reason this module is not a one-liner. If the text reaches cairosvg
as `<text>`, then two different engines lay out the same figure: matplotlib for the preview,
cairo for the PDF. They agree closely but not exactly, and cairo resolves the font itself,
so a machine without the preset's font silently substitutes. Outlining first makes the PDF
glyph-for-glyph what the preview showed (spec 11).
"""

from __future__ import annotations

from .units import mm_to_pt


class ExportError(RuntimeError):
    """The conversion could not be performed."""


def to_pdf(svg: str) -> bytes:
    """Convert a composed SVG to PDF, preserving the physical size.

    The root SVG carries its size in mm and a viewBox in the same units, so cairosvg needs
    no scaling hints: the page comes out at exactly the declared size.
    """
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ExportError(
            "PDF出力には cairosvg が必要: micromamba install -c conda-forge cairosvg"
        ) from exc

    try:
        return cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
    except Exception as exc:
        raise ExportError(f"PDFへの変換が失敗した: {exc}") from exc


def to_png(svg: str, scale: float = 4.0) -> bytes:
    """Raster output. Not a deliverable; useful for eyeballing and for tests."""
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover
        raise ExportError("PNG出力には cairosvg が必要") from exc
    try:
        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=scale)
    except Exception as exc:
        raise ExportError(f"PNGへの変換が失敗した: {exc}") from exc


def page_size_pt(width_mm: float, height_mm: float) -> tuple[float, float]:
    """The page size the PDF should have, for checking against its MediaBox."""
    return (mm_to_pt(width_mm), mm_to_pt(height_mm))
