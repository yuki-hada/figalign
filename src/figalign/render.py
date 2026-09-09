"""The drawing layer: turn a panel function into SVG/PDF at a given true size.

This is where the direction of dependency is settled (spec 3.1). The size comes from
outside and the panel function only receives it. Nothing is scaled afterwards, so
`bbox_inches="tight"` is never used: figsize *is* the physical size of the output.
"""

from __future__ import annotations

import io
import traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")  # spec 8.3: never grab a GUI backend inside a server process

from matplotlib.backends.backend_pdf import FigureCanvasPdf  # noqa: E402
from matplotlib.backends.backend_svg import FigureCanvasSVG  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from .cache import LruCache, source_hash  # noqa: E402
from .presets import Preset  # noqa: E402
from .units import mm_to_in, mm_to_pt  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


@dataclass(frozen=True)
class PanelSize:
    """A panel's settled size, passed to the panel function as `size` (spec 6.4)."""

    w_mm: float
    h_mm: float

    @property
    def w_in(self) -> float:
        return mm_to_in(self.w_mm)

    @property
    def h_in(self) -> float:
        return mm_to_in(self.h_mm)

    @property
    def figsize(self) -> tuple[float, float]:
        return (self.w_in, self.h_in)


class PanelRenderError(RuntimeError):
    """A panel function raised. The traceback travels with it so one cell can show it (spec 7.3)."""

    def __init__(self, panel: str, exc: BaseException):
        self.panel = panel
        self.original = exc
        self.traceback_text = _user_traceback(exc)
        super().__init__(f"パネル {panel!r} の描画が失敗した: {exc}")


_PKG_DIR = str(Path(__file__).parent)


def _user_traceback(exc: BaseException) -> str:
    """Drop figalign's own frames so only user code is shown."""
    frames = [
        f
        for f in traceback.extract_tb(exc.__traceback__)
        if not f.filename.startswith(_PKG_DIR)
    ]
    head = "Traceback (most recent call last):\n" if frames else ""
    return (
        head
        + "".join(traceback.format_list(frames))
        + "".join(traceback.format_exception_only(type(exc), exc))
    )


def _draw(
    fn: Callable[..., Any],
    data: Any,
    size: PanelSize,
    preset: Preset,
    panel: str,
) -> Figure:
    fig = Figure(figsize=size.figsize)
    # Placeholder until roadmap step 4 replaces it with two-pass alignment plus an exact
    # subplots_adjust. It does not touch the outer size, so the true-size guarantee holds.
    fig.set_layout_engine("constrained")
    ax = fig.add_subplot()
    try:
        fn(ax, data, size)
    except Exception as exc:  # one failing panel must not take everything down
        raise PanelRenderError(panel, exc) from exc
    return fig


def render_svg(
    fn: Callable[..., Any],
    data: Any,
    size: PanelSize,
    preset: Preset,
    panel: str = "panel",
) -> str:
    """Render a panel to a true-size SVG: width/height in mm on the root, viewBox in pt."""
    with matplotlib.rc_context(preset.rc_params()):
        fig = _draw(fn, data, size, preset, panel)
        FigureCanvasSVG(fig)
        buf = io.StringIO()
        fig.savefig(buf, format="svg", bbox_inches=None)
    return _set_physical_size(buf.getvalue(), size)


# The drawing layer of spec 5.1. Touching only the layout leaves these keys unchanged, so
# no panel is redrawn; changing a size or the panel's own source does redraw it.
_svg_cache: LruCache[tuple[object, ...], str] = LruCache(capacity=64)


def render_svg_cached(
    fn: Callable[..., Any],
    data: Any,
    size: PanelSize,
    preset: Preset,
    panel: str,
    data_version: str,
) -> str:
    """render_svg() with the drawing-layer cache in front of it."""
    key = (panel, source_hash(fn), size.w_mm, size.h_mm, preset.name, data_version)
    hit = _svg_cache.get(key)
    if hit is not None:
        return hit
    svg = render_svg(fn, data, size, preset, panel)
    _svg_cache.put(key, svg)
    return svg


def cache_stats() -> dict[str, int]:
    return {
        "entries": len(_svg_cache),
        "hits": _svg_cache.hits,
        "misses": _svg_cache.misses,
    }


def clear_render_cache() -> None:
    _svg_cache.clear()


def render_pdf(
    fn: Callable[..., Any],
    data: Any,
    size: PanelSize,
    preset: Preset,
    panel: str = "panel",
) -> bytes:
    """For final output. `pdf.fonttype = 42` is forced by the preset's rcParams (spec 9)."""
    with matplotlib.rc_context(preset.rc_params()):
        fig = _draw(fn, data, size, preset, panel)
        FigureCanvasPdf(fig)
        buf = io.BytesIO()
        fig.savefig(buf, format="pdf", bbox_inches=None)
    return buf.getvalue()


def _set_physical_size(svg_text: str, size: PanelSize) -> str:
    """Rewrite the root width/height in mm.

    matplotlib writes them in pt, which is already a correct physical length, but settling on
    mm lets the composition layer work in a single mm coordinate system. The viewBox stays in
    pt, so the ratio is exactly 1:1 and no distortion is introduced.
    """
    root = ET.fromstring(svg_text)
    if "viewBox" not in root.attrib:
        root.set("viewBox", f"0 0 {mm_to_pt(size.w_mm):.6g} {mm_to_pt(size.h_mm):.6g}")
    root.set("width", f"{size.w_mm:.6g}mm")
    root.set("height", f"{size.h_mm:.6g}mm")
    return ET.tostring(root, encoding="unicode")
