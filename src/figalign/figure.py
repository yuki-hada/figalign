"""The single path from declaration to final SVG.

fig.toml --+
           +--> solver --> panel sizes --> render --> panel SVG --> compose --> figure SVG
panels.py -+

The solver runs more than once. Margins depend on the axes size, because matplotlib picks
tick locations from it, and the axes size depends on the margins -- so it is a fixed point
(spec 5.2). It settles in two passes for ordinary figures.

Alignment itself does not depend on the measurement being exact: the final draw pins the
frame with subplots_adjust, so frames line up regardless. What the measurement decides is
whether enough room was reserved for the labels around them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import loader
from .compose import compose
from .figspec import FigSpec
from .layout import Layout, solve_aligned, solve_layout
from .render import (
    Margins,
    PanelRenderError,
    PanelSize,
    measure_panel_cached,
    render_svg_cached,
)

MAX_PASSES = 5
TOLERANCE_MM = 0.05


@dataclass
class FigureResult:
    svg: str
    layout: Layout
    errors: dict[str, str] = field(default_factory=dict)
    passes: int = 0
    converged: bool = True


@dataclass
class Resolved:
    layout: Layout
    margins: dict[str, Margins]
    errors: dict[str, str]
    passes: int
    converged: bool


def resolve(spec: FigSpec) -> Resolved:
    """Measure, solve, repeat until the inner sizes stop moving."""
    data = loader.load_data(spec.root, spec.data_ref)
    version = loader.current_data_version(spec.root, spec.data_ref)
    errors: dict[str, str] = {}

    # Panels that are not axes -- an external asset -- need no margin: they fill their cell.
    drawn = [name for name, panel in spec.panels.items() if panel.fn is not None]

    provisional = solve_layout(spec)
    guess = {name: (provisional.boxes[name].w, provisional.boxes[name].h) for name in drawn}
    seen: dict[str, Margins] = {}
    layout = provisional
    passes = 0
    converged = False

    for _ in range(MAX_PASSES):
        passes += 1
        margins: dict[str, Margins] = {}
        for name in drawn:
            w, h = guess[name]
            try:
                measured = measure_panel_cached(
                    loader.load_callable(spec.root, spec.panels[name].fn),  # type: ignore[arg-type]
                    data,
                    w,
                    h,
                    spec.preset,
                    panel=name,
                    data_version=version,
                )
            except PanelRenderError as exc:
                errors[name] = exc.traceback_text
                measured = Margins()
            except (FileNotFoundError, AttributeError, TypeError, ImportError) as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
                measured = Margins()
            margins[name] = measured
            seen[name] = seen[name].merge(measured) if name in seen else measured

        layout = solve_aligned(spec, margins)
        moved = {
            name: (layout.inner_box(name).w, layout.inner_box(name).h) for name in drawn
        }
        if all(
            abs(moved[n][0] - guess[n][0]) < TOLERANCE_MM
            and abs(moved[n][1] - guess[n][1]) < TOLERANCE_MM
            for n in drawn
        ):
            converged = True
            break
        guess = moved

    if not converged and seen:
        # Tick labels can flip between sizes and make this oscillate. Fall back to the
        # largest margin seen for each side: the axes end up a little smaller than ideal,
        # but nothing is written on top of anything else.
        layout = solve_aligned(spec, seen)

    return Resolved(
        layout=layout,
        margins=seen,
        errors=errors,
        passes=passes,
        converged=converged,
    )


def build_figure(spec: FigSpec, text_as_paths: bool = False) -> FigureResult:
    """Draw every panel at its settled size and compose them into one SVG.

    `text_as_paths` is for the PDF route; see export.py for why it is not the default.
    """
    resolved = resolve(spec)
    layout = resolved.layout
    data = loader.load_data(spec.root, spec.data_ref)
    version = loader.current_data_version(spec.root, spec.data_ref)

    panel_svgs: dict[str, str] = {}
    placements: dict[str, object] = {}
    errors = dict(resolved.errors)

    for name, box in layout.boxes.items():
        panel = spec.panels[name]
        size = PanelSize(w_mm=box.w, h_mm=box.h)
        placements[name] = box
        try:
            if panel.src is not None:
                # An asset has no margins of its own, so line it up with the frames instead
                # of letting it spill into the space reserved for a neighbour's tick labels.
                placements[name] = layout.inner_box(name)
                panel_svgs[name] = _read_src(spec, panel.src)
            else:
                assert panel.fn is not None
                fn = loader.load_callable(spec.root, panel.fn)
                panel_svgs[name] = render_svg_cached(
                    fn,
                    data,
                    size,
                    spec.preset,
                    panel=name,
                    data_version=version,
                    inner_mm=layout.inner_local(name),
                    text_as_paths=text_as_paths,
                )
        except PanelRenderError as exc:
            # One failing panel must not take the others down (spec 7.3)
            errors[name] = exc.traceback_text
        except (FileNotFoundError, AttributeError, TypeError, ImportError, OSError) as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"

    svg = compose(layout, spec.preset, panel_svgs, errors, placements)  # type: ignore[arg-type]
    return FigureResult(
        svg=svg,
        layout=layout,
        errors=errors,
        passes=resolved.passes,
        converged=resolved.converged,
    )


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
