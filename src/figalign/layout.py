"""The solver: declaration -> the true size (mm) of every panel.

This is where the direction of dependency in spec 3.1 lives. Sizes are settled here and the
drawing layer merely receives them.

Two solvers live here. `solve_layout` divides the figure into outer cells and knows nothing
about what will be drawn in them; it produces the provisional sizes that the first
measuring pass needs. `solve_aligned` takes those measurements and solves for the *inner*
boxes -- the axes frames themselves -- so that frames in the same column or row land on the
same coordinate (spec 5.2).
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from .figspec import FigSpec, SpecError
from .grid import (
    Box,
    GridError,
    cell_boxes,
    solve_inner_tracks,
    solve_tracks,
    total_size,
    track_margins,
)
from .presets import Preset
from .render import Margins
from .units import pt_to_mm


# Room kept for a panel label between the letter and the axes frame.
LABEL_PAD_MM = 0.7
# A single lowercase letter is narrower than the font size; enough to reserve for.
LABEL_WIDTH_RATIO = 0.75


@dataclass(frozen=True)
class Layout:
    width_mm: float
    height_mm: float
    boxes: dict[str, Box]  # outer: the canvas each panel is drawn on
    labels: dict[str, str]
    inner: dict[str, Box] | None = None  # the axes frames, once they have been solved

    def box(self, name: str) -> Box:
        return self.boxes[name]

    def inner_box(self, name: str) -> Box:
        """The axes frame, falling back to the outer box when nothing was measured."""
        if self.inner is None:
            return self.boxes[name]
        return self.inner[name]

    def inner_local(self, name: str) -> tuple[float, float, float, float]:
        """The axes frame in the panel's own coordinates, for subplots_adjust."""
        outer, inner = self.boxes[name], self.inner_box(name)
        return (inner.x - outer.x, inner.y - outer.y, inner.w, inner.h)


def solve_layout(spec: FigSpec) -> Layout:
    try:
        col_widths = solve_tracks(
            spec.col_widths, spec.n_cols, spec.gap_x_mm, total_mm=spec.width_mm
        )
        row_heights = solve_tracks(
            spec.row_heights, spec.n_rows, spec.gap_y_mm, total_mm=spec.height_mm
        )
    except GridError as exc:
        raise SpecError(str(exc)) from None

    width_mm, height_mm = total_size(col_widths, row_heights, spec.gap_x_mm, spec.gap_y_mm)
    boxes = cell_boxes(spec.cells, col_widths, row_heights, spec.gap_x_mm, spec.gap_y_mm)
    labels = panel_labels(spec.order) if spec.labels else {}
    return Layout(width_mm=width_mm, height_mm=height_mm, boxes=boxes, labels=labels)


def solve_aligned(spec: FigSpec, margins: dict[str, Margins]) -> Layout:
    """Solve for inner boxes, given what each panel needs around its frame."""
    as_tuples = {
        name: (m.left, m.right, m.top, m.bottom) for name, m in margins.items()
    }
    lead_x, trail_x = track_margins(spec.cells, as_tuples, spec.n_cols, "x")
    lead_y, trail_y = track_margins(spec.cells, as_tuples, spec.n_rows, "y")

    if spec.labels:
        _reserve_label_space(spec, spec.preset, lead_x, lead_y)

    try:
        widths, x_at, total_w = solve_inner_tracks(
            spec.col_widths, spec.n_cols, spec.gap_x_mm, spec.width_mm, lead_x, trail_x
        )
        heights, y_at, total_h = solve_inner_tracks(
            spec.row_heights, spec.n_rows, spec.gap_y_mm, spec.height_mm, lead_y, trail_y
        )
    except GridError as exc:
        raise SpecError(str(exc)) from None

    inner: dict[str, Box] = {}
    outer: dict[str, Box] = {}
    for name, cell in spec.cells.items():
        # A spanning panel's frame swallows the gaps it crosses, so its inner box runs from
        # the first track's offset to the end of the last one.
        x0 = x_at[cell.col0]
        y0 = y_at[cell.row0]
        x1 = x_at[cell.col1 - 1] + widths[cell.col1 - 1]
        y1 = y_at[cell.row1 - 1] + heights[cell.row1 - 1]
        inner[name] = Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
        # The canvas reserves the track's margin, not the panel's own, so a panel that needs
        # slightly more than was measured has the column's slack to grow into.
        outer[name] = Box(
            x=x0 - lead_x[cell.col0],
            y=y0 - lead_y[cell.row0],
            w=(x1 + trail_x[cell.col1 - 1]) - (x0 - lead_x[cell.col0]),
            h=(y1 + trail_y[cell.row1 - 1]) - (y0 - lead_y[cell.row0]),
        )

    return Layout(
        width_mm=total_w,
        height_mm=total_h,
        boxes=outer,
        labels=panel_labels(spec.order) if spec.labels else {},
        inner=inner,
    )


def _reserve_label_space(
    spec: FigSpec, preset: Preset, lead_x: list[float], lead_y: list[float]
) -> None:
    """Keep room for the panel letter above and to the left of the frame.

    Journals set it at the very top left of the panel, outside the axis labels, and the top
    margin is often zero otherwise -- no title, no spine -- so without this the letter would
    have nowhere to go.
    """
    height = pt_to_mm(preset.font_size_pt)
    width = height * LABEL_WIDTH_RATIO
    for cell in spec.cells.values():
        lead_y[cell.row0] = max(lead_y[cell.row0], height + LABEL_PAD_MM)
        lead_x[cell.col0] = max(lead_x[cell.col0], width + LABEL_PAD_MM)


def panel_labels(order: list[str]) -> dict[str, str]:
    """Assign a, b, c... in reading order over the grid (spec 6.3)."""
    return {name: _letter(i) for i, name in enumerate(order)}


def _letter(index: int) -> str:
    letters = string.ascii_lowercase
    if index < len(letters):
        return letters[index]
    head, tail = divmod(index, len(letters))
    return letters[head - 1] + letters[tail]
