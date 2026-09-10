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

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
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
class Margins:
    """Space the axes needs outside its own frame, in mm.

    Measured as the difference between `ax.get_position()` (the frame) and
    `ax.get_tightbbox()` (everything drawn: tick labels, axis labels, a title, a legend
    placed outside). Zero on a side means nothing sticks out there.
    """

    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0

    def merge(self, other: "Margins") -> "Margins":
        """Take the larger of each side, so an iteration can only ever reserve more."""
        return Margins(
            left=max(self.left, other.left),
            right=max(self.right, other.right),
            top=max(self.top, other.top),
            bottom=max(self.bottom, other.bottom),
        )

    def exceeds(self, other: "Margins", tol: float) -> bool:
        return (
            self.left - other.left > tol
            or self.right - other.right > tol
            or self.top - other.top > tol
            or self.bottom - other.bottom > tol
        )


# Slack around the axes while measuring. Only has to be large enough that nothing is
# clipped; it never reaches the output.
MEASURE_PAD_MM = 30.0


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
        super().__init__(f"panel {panel!r} failed to draw: {exc}")


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
    inner_mm: tuple[float, float, float, float] | None = None,
) -> Figure:
    """Draw a panel at `size`.

    With `inner_mm` -- (x, y, w, h) in panel-local mm from the top left -- the axes frame is
    placed there exactly, which is what makes frames line up across panels (spec 5.2).
    Without it, constrained_layout picks a reasonable position; that path is only used by
    the single-panel view, where there is nothing to line up with.
    """
    fig = Figure(figsize=size.figsize)
    if inner_mm is None:
        fig.set_layout_engine("constrained")
        ax = fig.add_subplot()
    else:
        fig.set_layout_engine("none")
        ax = fig.add_subplot()
        fig.subplots_adjust(**_adjust(size, inner_mm))
    try:
        fn(ax, data, size)
    except Exception as exc:  # one failing panel must not take everything down
        raise PanelRenderError(panel, exc) from exc
    return fig


def _rc(preset: Preset, text_as_paths: bool) -> dict[str, object]:
    rc = preset.rc_params()
    if text_as_paths:
        rc["svg.fonttype"] = "path"
    return rc


def _adjust(size: PanelSize, inner_mm: tuple[float, float, float, float]) -> dict[str, float]:
    """Convert a panel-local inner box in mm into subplots_adjust fractions.

    matplotlib measures y upwards from the bottom; a Box measures it downwards from the top.
    """
    x, y, w, h = inner_mm
    left = x / size.w_mm
    right = (x + w) / size.w_mm
    top = 1.0 - y / size.h_mm
    bottom = 1.0 - (y + h) / size.h_mm
    # A degenerate box would make matplotlib raise; clamp to something drawable so a bad
    # declaration shows up as a squashed panel rather than a traceback.
    eps = 1e-4
    right = max(right, left + eps)
    top = max(top, bottom + eps)
    return {"left": left, "right": right, "bottom": bottom, "top": top}


def measure_panel(
    fn: Callable[..., Any],
    data: Any,
    inner_w_mm: float,
    inner_h_mm: float,
    preset: Preset,
    panel: str = "panel",
) -> Margins:
    """Pass one of spec 5.2: draw once and measure what the axes needs around its frame.

    The axes is given exactly the inner size it will have in the final figure, because
    matplotlib chooses tick locations from the axes size and the tick labels are most of
    what the margin is made of.
    """
    pad = MEASURE_PAD_MM
    fig_w, fig_h = inner_w_mm + 2 * pad, inner_h_mm + 2 * pad
    with matplotlib.rc_context(preset.rc_params()):
        fig = Figure(figsize=(mm_to_in(fig_w), mm_to_in(fig_h)))
        FigureCanvasAgg(fig)
        ax = fig.add_axes((pad / fig_w, pad / fig_h, inner_w_mm / fig_w, inner_h_mm / fig_h))
        try:
            fn(ax, data, PanelSize(w_mm=inner_w_mm, h_mm=inner_h_mm))
        except Exception as exc:
            raise PanelRenderError(panel, exc) from exc

        fig.draw_without_rendering()
        renderer = fig.canvas.get_renderer()
        pos = ax.get_position()
        tight = ax.get_tightbbox(renderer)
        width_px, height_px = fig.get_size_inches() * fig.dpi
        per_px = 25.4 / fig.dpi
        return Margins(
            left=max((pos.x0 * width_px - tight.x0) * per_px, 0.0),
            right=max((tight.x1 - pos.x1 * width_px) * per_px, 0.0),
            top=max((tight.y1 - pos.y1 * height_px) * per_px, 0.0),
            bottom=max((pos.y0 * height_px - tight.y0) * per_px, 0.0),
        )


def render_svg(
    fn: Callable[..., Any],
    data: Any,
    size: PanelSize,
    preset: Preset,
    panel: str = "panel",
    inner_mm: tuple[float, float, float, float] | None = None,
    text_as_paths: bool = False,
) -> str:
    """Render a panel to a true-size SVG: width/height in mm on the root, viewBox in pt.

    With `text_as_paths`, matplotlib converts the text to outlines before it is written.
    That matters for the PDF route: the preview and the PDF then contain the same glyphs at
    the same positions, instead of matplotlib laying out the preview and another text engine
    laying out the PDF (spec 11).
    """
    with matplotlib.rc_context(_rc(preset, text_as_paths)):
        fig = _draw(fn, data, size, preset, panel, inner_mm)
        FigureCanvasSVG(fig)
        buf = io.StringIO()
        # Date=None drops the timestamp matplotlib would otherwise write into the metadata,
        # which is the other thing that makes two identical figures differ.
        fig.savefig(buf, format="svg", bbox_inches=None, metadata={"Date": None})
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
    inner_mm: tuple[float, float, float, float] | None = None,
    text_as_paths: bool = False,
) -> str:
    """render_svg() with the drawing-layer cache in front of it."""
    key = (
        panel,
        source_hash(fn),
        size.w_mm,
        size.h_mm,
        preset.name,
        data_version,
        inner_mm and tuple(round(v, 6) for v in inner_mm),
        text_as_paths,
    )
    hit = _svg_cache.get(key)
    if hit is not None:
        return hit
    svg = render_svg(fn, data, size, preset, panel, inner_mm, text_as_paths)
    _svg_cache.put(key, svg)
    return svg


_margin_cache: LruCache[tuple[object, ...], Margins] = LruCache(capacity=64)


def measure_panel_cached(
    fn: Callable[..., Any],
    data: Any,
    inner_w_mm: float,
    inner_h_mm: float,
    preset: Preset,
    panel: str,
    data_version: str,
) -> Margins:
    """measure_panel() with a cache. A measurement costs a full draw, so it needs one."""
    key = (
        panel,
        source_hash(fn),
        round(inner_w_mm, 4),
        round(inner_h_mm, 4),
        preset.name,
        data_version,
    )
    hit = _margin_cache.get(key)
    if hit is not None:
        return hit
    margins = measure_panel(fn, data, inner_w_mm, inner_h_mm, preset, panel)
    _margin_cache.put(key, margins)
    return margins


def cache_stats() -> dict[str, int]:
    return {
        "entries": len(_svg_cache),
        "hits": _svg_cache.hits,
        "misses": _svg_cache.misses,
        "measure_entries": len(_margin_cache),
        "measure_hits": _margin_cache.hits,
        "measure_misses": _margin_cache.misses,
    }


def clear_render_cache() -> None:
    _svg_cache.clear()
    _margin_cache.clear()


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
        fig.savefig(
            buf, format="pdf", bbox_inches=None, metadata={"CreationDate": None}
        )
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
