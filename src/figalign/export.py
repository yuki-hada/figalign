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
    cairosvg = _import_cairosvg()
    try:
        return cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
    except Exception as exc:
        raise ExportError(f"conversion to PDF failed: {exc}") from exc


def to_png(svg: str, scale: float = 4.0) -> bytes:
    """Raster output. Not a deliverable; useful for eyeballing and for tests."""
    cairosvg = _import_cairosvg()
    try:
        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=scale)
    except Exception as exc:
        raise ExportError(f"conversion to PNG failed: {exc}") from exc


def _import_cairosvg():
    """Import cairosvg, telling the two failure modes apart.

    `pip install cairosvg` succeeds on a machine with no cairo at all: cairocffi dlopens
    libcairo at import time and raises OSError, not ImportError. Distinguishing the two
    matters because the fix is different -- install the package, or install the C library.
    """
    try:
        import cairosvg
    except ImportError as exc:
        raise ExportError(
            "PDF output needs cairosvg: pip install 'figalign[pdf]' "
            "(or micromamba install -c conda-forge cairosvg)"
        ) from exc
    except OSError as exc:
        raise ExportError(
            "cairosvg is installed but its C library (libcairo) is missing. "
            "pip cannot supply it: install cairo from your system package manager "
            "(brew install cairo / apt install libcairo2) or use "
            "micromamba install -c conda-forge cairosvg. "
            f"Loader said: {exc}"
        ) from exc
    return cairosvg


def page_size_pt(width_mm: float, height_mm: float) -> tuple[float, float]:
    """The page size the PDF should have, for checking against its MediaBox."""
    return (mm_to_pt(width_mm), mm_to_pt(height_mm))
