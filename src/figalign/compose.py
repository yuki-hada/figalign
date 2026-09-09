"""The composition layer: place panel SVGs into a root SVG whose unit is the millimetre.

Panels are placed, never scaled. Each one becomes a nested `<svg>` that keeps its own
viewBox in pt, and the ratio between the mm viewport and that pt viewBox is always
1mm/2.8346pt, so the factor is exactly 1:1. This is the difference from svgutils-style
composition, which shrinks with `.scale()` after the fact (spec 12).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .grid import Box
from .layout import LABEL_PAD_MM, Layout
from .presets import Preset
from .units import mm_to_pt, pt_to_mm

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

# Only two forms of reference get rewritten: url(#id) and href="#id".
# Colour literals such as fill="#1f77b4" also contain "#", so anything less specific
# would corrupt them.
_URL_REF = re.compile(r"url\(\s*#([\w:.\-]+)\s*\)")
_HREF_REF = re.compile(r"^#([\w:.\-]+)$")
_HREF_KEYS = ("href", f"{{{XLINK_NS}}}href")
_DROP = {f"{{{SVG_NS}}}metadata", f"{{{SVG_NS}}}style"}
# matplotlib emits the same rule for every panel, so hoist a single copy to the root
ROOT_STYLE = "*{stroke-linejoin: round; stroke-linecap: butt}"

LABEL_WEIGHT = "bold"


def compose(
    layout: Layout,
    preset: Preset,
    panel_svgs: dict[str, str],
    errors: dict[str, str] | None = None,
    placements: dict[str, Box] | None = None,
) -> str:
    """Assemble the final SVG from the layout and the rendered panels.

    `placements` says where each panel's SVG goes. A matplotlib panel is drawn on a canvas
    that includes its own margins, so it belongs at its outer box; an external asset has no
    margins and belongs at the inner box, where it lines up with the frames beside it.
    """
    errors = errors or {}
    placements = placements or layout.boxes
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{layout.width_mm:.6g}mm",
            "height": f"{layout.height_mm:.6g}mm",
            # 1 user unit = 1mm, so every coordinate below can be written in mm
            "viewBox": f"0 0 {layout.width_mm:.6g} {layout.height_mm:.6g}",
            "version": "1.1",
        },
    )
    style = ET.SubElement(root, f"{{{SVG_NS}}}style", {"type": "text/css"})
    style.text = ROOT_STYLE

    for name, box in layout.boxes.items():
        if name in errors:
            _error_cell(root, name, box, preset, errors[name])
        elif name in panel_svgs:
            root.append(_nest(panel_svgs[name], name, placements.get(name, box)))

    for name, label in layout.labels.items():
        # Anchored to the frame, not the canvas: flush with the panel's left edge and
        # sitting just above the axes frame, which is where journals put it.
        _label(root, layout.boxes[name], layout.inner_box(name), preset, label)

    return ET.tostring(root, encoding="unicode")


def fit(svg_text: str, w_mm: float, h_mm: float) -> str:
    """Fit an external SVG asset into a given true size on its own, for the single-panel view."""
    src = ET.fromstring(svg_text)
    if "viewBox" not in src.attrib:
        src.set("viewBox", _intrinsic_view_box(src))
    src.set("width", f"{w_mm:.6g}mm")
    src.set("height", f"{h_mm:.6g}mm")
    src.set("preserveAspectRatio", "xMidYMid meet")
    return ET.tostring(src, encoding="unicode")


def _nest(svg_text: str, name: str, box: Box) -> ET.Element:
    """Wrap a panel SVG in a nested `<svg>` and place it at its position."""
    src = ET.fromstring(svg_text)
    ids = {el.attrib["id"] for el in src.iter() if "id" in el.attrib}
    _prefix_ids(src, f"{name}-", ids)

    view_box = src.get("viewBox") or _intrinsic_view_box(src)
    nested = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "x": f"{box.x:.6g}",
            "y": f"{box.y:.6g}",
            "width": f"{box.w:.6g}",
            "height": f"{box.h:.6g}",
            "viewBox": view_box,
            # A panel is rendered at exactly its cell size, so "meet" adds no letterboxing.
            # Only external assets (src) actually get fitted here, aspect ratio preserved.
            "preserveAspectRatio": "xMidYMid meet",
            "id": f"panel-{name}",
        },
    )
    for child in list(src):
        if child.tag not in _DROP:
            nested.append(child)
    return nested


def _prefix_ids(root: ET.Element, prefix: str, ids: set[str]) -> None:
    """Prefix every id and every reference to one.

    matplotlib emits ids such as `axes_1` and `#p6947da314c` that are unique only within
    one document, so they collide once several panels share a single SVG.
    """
    if not ids:
        return

    def rewrite_url(m: re.Match[str]) -> str:
        target = m.group(1)
        return f"url(#{prefix}{target})" if target in ids else m.group(0)

    for el in root.iter():
        if "id" in el.attrib:
            el.set("id", prefix + el.attrib["id"])
        for key, value in list(el.attrib.items()):
            if key == "id":
                continue
            if key in _HREF_KEYS:
                m = _HREF_REF.match(value.strip())
                if m and m.group(1) in ids:
                    el.set(key, f"#{prefix}{m.group(1)}")
            elif "url(" in value:
                el.set(key, _URL_REF.sub(rewrite_url, value))


def _intrinsic_view_box(src: ET.Element) -> str:
    """Build a viewBox from width/height for external SVGs that lack one."""
    from .units import UnitError, parse_length

    def dim(key: str, fallback: float) -> float:
        raw = src.get(key)
        if raw is None:
            return fallback
        try:
            return mm_to_pt(parse_length(raw))
        except UnitError:
            digits = re.match(r"[\d.]+", raw)
            return float(digits.group()) if digits else fallback

    return f"0 0 {dim('width', 100.0):.6g} {dim('height', 100.0):.6g}"


def _label(
    parent: ET.Element, outer: Box, inner: Box, preset: Preset, text: str
) -> None:
    """A panel label: coordinates in mm, font size converted from pt."""
    size_mm = pt_to_mm(preset.font_size_pt)
    el = ET.SubElement(
        parent,
        f"{{{SVG_NS}}}text",
        {
            "x": f"{outer.x:.6g}",
            "y": f"{max(inner.y - LABEL_PAD_MM, outer.y + size_mm):.6g}",
            "font-family": preset.font_family,
            "font-size": f"{size_mm:.6g}",
            "font-weight": LABEL_WEIGHT,
            "fill": "#000",
        },
    )
    el.text = text


def _error_cell(
    parent: ET.Element, name: str, box: Box, preset: Preset, message: str
) -> None:
    """Turn only the failed cell into a traceback display (spec 7.3)."""
    g = ET.SubElement(parent, f"{{{SVG_NS}}}g", {"id": f"panel-{name}-error"})
    ET.SubElement(
        g,
        f"{{{SVG_NS}}}rect",
        {
            "x": f"{box.x:.6g}",
            "y": f"{box.y:.6g}",
            "width": f"{box.w:.6g}",
            "height": f"{box.h:.6g}",
            "fill": "#fff4f4",
            "stroke": "#d04040",
            "stroke-width": "0.3",
        },
    )
    size_mm = pt_to_mm(preset.font_size_pt) * 0.85
    # The label (a, b, c...) is drawn separately at the top left, so start one line below it
    top_mm = pt_to_mm(preset.font_size_pt) + size_mm * 1.4
    lines = [f"{name}: 描画失敗"] + _tail(message, box, size_mm, top_mm)
    for i, line in enumerate(lines):
        el = ET.SubElement(
            g,
            f"{{{SVG_NS}}}text",
            {
                "x": f"{box.x + 1.5:.6g}",
                "y": f"{box.y + top_mm + i * size_mm * 1.4:.6g}",
                "font-family": "monospace",
                "font-size": f"{size_mm:.6g}",
                "fill": "#a02020",
            },
        )
        el.text = line
    return None


_FRAME = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<fn>.+)$')


def _tail(message: str, box: Box, size_mm: float, top_mm: float) -> list[str]:
    """Take as many lines as fit, counting back from the end where the exception is.

    `File "/some/long/absolute/path/panels.py", line 12, in scatter_main` is guaranteed to
    be clipped by the cell width, so fold it into `panels.py:12 in scatter_main`.
    """
    max_lines = max(int((box.h - top_mm - 1.0) / (size_mm * 1.4)) - 1, 1)
    max_chars = max(int((box.w - 3.0) / (size_mm * 0.62)), 12)

    lines = []
    for raw in message.strip().splitlines():
        if not raw.strip():
            continue
        m = _FRAME.match(raw)
        if m:
            name = m["path"].rsplit("/", 1)[-1]
            lines.append(f'{name}:{m["line"]} in {m["fn"]}')
        else:
            lines.append(raw.strip())
    return [ln[:max_chars] for ln in lines[-max_lines:]]
