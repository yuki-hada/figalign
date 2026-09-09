"""The solver: declaration -> the true size (mm) of every panel.

This is where the direction of dependency in spec 3.1 lives. Sizes are settled here and the
drawing layer merely receives them. What gets aligned today is the *outer* box (the grid
cell); aligning the axes frames themselves arrives with the two-pass measurement in
roadmap step 4.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from .figspec import FigSpec, SpecError
from .grid import Box, GridError, cell_boxes, solve_tracks, total_size


@dataclass(frozen=True)
class Layout:
    width_mm: float
    height_mm: float
    boxes: dict[str, Box]
    labels: dict[str, str]

    def box(self, name: str) -> Box:
        return self.boxes[name]


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


def panel_labels(order: list[str]) -> dict[str, str]:
    """Assign a, b, c... in reading order over the grid (spec 6.3)."""
    return {name: _letter(i) for i, name in enumerate(order)}


def _letter(index: int) -> str:
    letters = string.ascii_lowercase
    if index < len(letters):
        return letters[index]
    head, tail = divmod(index, len(letters))
    return letters[head - 1] + letters[tail]
