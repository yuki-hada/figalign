"""The single path from declaration to final SVG.

fig.toml --+
           +--> solver --> panel sizes --> render --> panel SVG --> compose --> figure SVG
panels.py -+
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import loader
from .compose import compose
from .figspec import FigSpec
from .layout import Layout, solve_layout
from .render import PanelRenderError, PanelSize, render_svg_cached


@dataclass
class FigureResult:
    svg: str
    layout: Layout
    errors: dict[str, str] = field(default_factory=dict)


def build_figure(spec: FigSpec) -> FigureResult:
    """Draw every panel at its settled size and compose them into one SVG."""
    layout = solve_layout(spec)
    data = loader.load_data(spec.root, spec.data_ref)
    version = loader.current_data_version(spec.root, spec.data_ref)

    panel_svgs: dict[str, str] = {}
    errors: dict[str, str] = {}

    for name, box in layout.boxes.items():
        panel = spec.panels[name]
        size = PanelSize(w_mm=box.w, h_mm=box.h)
        try:
            if panel.src is not None:
                panel_svgs[name] = _read_src(spec, panel.src)
            else:
                assert panel.fn is not None
                fn = loader.load_callable(spec.root, panel.fn)
                panel_svgs[name] = render_svg_cached(
                    fn, data, size, spec.preset, panel=name, data_version=version
                )
        except PanelRenderError as exc:
            # One failing panel must not take the others down (spec 7.3)
            errors[name] = exc.traceback_text
        except (FileNotFoundError, AttributeError, TypeError, ImportError, OSError) as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"

    svg = compose(layout, spec.preset, panel_svgs, errors)
    return FigureResult(svg=svg, layout=layout, errors=errors)


def _read_src(spec: FigSpec, src: str) -> str:
    """Read an external asset such as a hand-drawn SVG (spec 3.2).

    The asset is fitted into its cell with the aspect ratio preserved. Text inside it scales
    with the cell, so the preset font size does not apply. This is accepted as an escape
    hatch for schematics.
    """
    path = (spec.root / src).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"素材が無い: {path}")
    return path.read_text(encoding="utf-8")
