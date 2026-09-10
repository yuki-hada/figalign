"""Grid normalisation and the track solver.

Nothing carries coordinates. The grid and fr units are first class; absolute positions come
into existence here for the first time, in mm (spec 3.2). The fr rule matches CSS grid:
subtract fixed lengths and gaps first, then split what is left by weight (spec 6.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .units import UnitError, parse_length

EMPTY = "."  # same empty-cell marker as matplotlib's subplot_mosaic
DEFAULT_FR_ROW_MM = 40.0  # size of one fr when no total height is given

_FR = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*fr\s*$")


class GridError(ValueError):
    """The grid is malformed."""


@dataclass(frozen=True)
class Box:
    """A rectangle in mm, with the origin at the top left."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Cell:
    """The half-open range of grid cells a panel occupies."""

    name: str
    row0: int
    col0: int
    row1: int
    col1: int

    @property
    def order_key(self) -> tuple[int, int]:
        return (self.row0, self.col0)


def normalize_grid(raw: object) -> list[list[str]]:
    """Normalise a mosaic string, list of strings, or 2-D array into a 2-D array (spec 6.3)."""
    if isinstance(raw, str):
        rows = [list(line.strip()) for line in raw.strip().splitlines() if line.strip()]
    elif isinstance(raw, list):
        if not raw:
            raise GridError("the grid is empty")
        if all(isinstance(r, str) for r in raw):
            # mosaic notation written one row per string, single-character names
            rows = [list(r.strip()) for r in raw if r.strip()]
        elif all(isinstance(r, list) for r in raw):
            rows = [[str(c) for c in r] for r in raw]
        else:
            raise GridError("grid rows must be all strings or all arrays")
    else:
        raise GridError(f"unusable type for grid: {type(raw).__name__}")

    if not rows:
        raise GridError("the grid is empty")
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise GridError(f"grid rows differ in length: {sorted(widths)}")
    return rows


def find_cells(rows: list[list[str]]) -> dict[str, Cell]:
    """Find the range each name occupies, rejecting non-rectangular spans (L shapes)."""
    positions: dict[str, list[tuple[int, int]]] = {}
    for r, row in enumerate(rows):
        for c, name in enumerate(row):
            if name != EMPTY:
                positions.setdefault(name, []).append((r, c))

    if not positions:
        raise GridError("the grid holds no panels")

    cells: dict[str, Cell] = {}
    for name, pos in positions.items():
        rs = [r for r, _ in pos]
        cs = [c for _, c in pos]
        row0, row1 = min(rs), max(rs) + 1
        col0, col1 = min(cs), max(cs) + 1
        expected = (row1 - row0) * (col1 - col0)
        if len(pos) != expected:
            raise GridError(f"panel {name!r} does not occupy a rectangle")
        cells[name] = Cell(name, row0, col0, row1, col1)
    return cells


def parse_track(value: object) -> tuple[str, float]:
    """Read a track spec as either `("fr", 1.0)` or `("mm", 12.0)`."""
    if isinstance(value, str):
        m = _FR.match(value)
        if m:
            weight = float(m.group(1))
            if weight <= 0:
                raise GridError(f"fr must be positive: {value!r}")
            return ("fr", weight)
    try:
        return ("mm", parse_length(value))  # type: ignore[arg-type]
    except UnitError:
        raise GridError(f"cannot read the track {value!r} (e.g. '1fr', '25mm')") from None


def solve_tracks(
    specs: list[object] | None,
    count: int,
    gap_mm: float,
    total_mm: float | None,
    fr_base_mm: float = DEFAULT_FR_ROW_MM,
) -> list[float]:
    """Return the true size (mm) of every track.

    Given `total_mm`, fixed lengths and gaps are subtracted and the remainder is split by fr
    weight. Without it, each fr counts as `fr_base_mm` so that ratios alone are enough and no
    total has to be written.
    """
    if specs is None:
        specs = ["1fr"] * count
    if len(specs) != count:
        raise GridError(f"{len(specs)} track(s) given for {count} in the grid")

    tracks = [parse_track(s) for s in specs]
    gaps_mm = gap_mm * max(count - 1, 0)

    if total_mm is None:
        return [v if kind == "mm" else v * fr_base_mm for kind, v in tracks]

    fixed = sum(v for kind, v in tracks if kind == "mm")
    weights = sum(v for kind, v in tracks if kind == "fr")
    remainder = total_mm - fixed - gaps_mm
    if weights > 0 and remainder <= 0:
        raise GridError(
            f"fixed {fixed:.4g}mm + gaps {gaps_mm:.4g}mm exceed the total {total_mm:.4g}mm"
        )
    return [v if kind == "mm" else remainder * v / weights for kind, v in tracks]


def solve_inner_tracks(
    specs: list[object] | None,
    count: int,
    gap_mm: float,
    total_mm: float | None,
    lead_mm: list[float],
    trail_mm: list[float],
    fr_base_mm: float = DEFAULT_FR_ROW_MM,
) -> tuple[list[float], list[float], float]:
    """Solve for the size of the *inner* boxes -- the axes frames themselves (spec 5.2).

    `lead_mm[j]` / `trail_mm[j]` are the margins reserved before and after track j.

    `gap` is the distance from one frame to the next, and it is a *minimum*: where the
    facing margins need more room than that, the spacing grows to fit them, because the
    alternative is tick labels written on top of each other.

    Returns the inner sizes, their offsets from the figure edge, and the resulting total.
    """
    if specs is None:
        specs = ["1fr"] * count
    if len(specs) != count:
        raise GridError(f"{len(specs)} track(s) given for {count} in the grid")

    tracks = [parse_track(spec) for spec in specs]
    gaps = [
        max(gap_mm, trail_mm[j] + lead_mm[j + 1]) for j in range(count - 1)
    ]
    outside = lead_mm[0] + trail_mm[count - 1]

    if total_mm is None:
        # No total given: 1fr is worth fr_base_mm and the figure grows to fit.
        inner = [v if kind == "mm" else v * fr_base_mm for kind, v in tracks]
    else:
        fixed = sum(v for kind, v in tracks if kind == "mm")
        weights = sum(v for kind, v in tracks if kind == "fr")
        available = total_mm - outside - sum(gaps) - fixed
        if weights > 0 and available <= 0:
            raise GridError(
                f"nothing left for the axes frames: total {total_mm:.4g}mm - margins {outside:.4g}mm "
                f"- gaps {sum(gaps):.4g}mm - fixed {fixed:.4g}mm"
            )
        inner = [
            v if kind == "mm" else available * v / weights for kind, v in tracks
        ]

    offsets, acc = [], lead_mm[0]
    for j, size in enumerate(inner):
        offsets.append(acc)
        acc += size + (gaps[j] if j < count - 1 else 0.0)
    return inner, offsets, acc + trail_mm[count - 1]


def track_margins(
    cells: dict[str, Cell],
    margins: dict[str, tuple[float, float, float, float]],
    count: int,
    axis: str,
) -> tuple[list[float], list[float]]:
    """Reduce per-panel margins to per-track margins.

    A panel only contributes at the tracks it starts and ends on: a panel spanning two
    columns says nothing about the boundary it crosses.
    """
    lead = [0.0] * count
    trail = [0.0] * count
    for name, cell in cells.items():
        left, right, top, bottom = margins.get(name, (0.0, 0.0, 0.0, 0.0))
        if axis == "x":
            start, end, before, after = cell.col0, cell.col1 - 1, left, right
        else:
            start, end, before, after = cell.row0, cell.row1 - 1, top, bottom
        lead[start] = max(lead[start], before)
        trail[end] = max(trail[end], after)
    return lead, trail


def cell_boxes(
    cells: dict[str, Cell],
    col_widths: list[float],
    row_heights: list[float],
    gap_x: float,
    gap_y: float,
) -> dict[str, Box]:
    """Build each panel's rectangle from track sizes. A span absorbs the gaps it crosses."""
    x_at = _offsets(col_widths, gap_x)
    y_at = _offsets(row_heights, gap_y)

    boxes: dict[str, Box] = {}
    for name, cell in cells.items():
        x = x_at[cell.col0]
        y = y_at[cell.row0]
        w = sum(col_widths[cell.col0 : cell.col1]) + gap_x * (cell.col1 - cell.col0 - 1)
        h = sum(row_heights[cell.row0 : cell.row1]) + gap_y * (cell.row1 - cell.row0 - 1)
        boxes[name] = Box(x=x, y=y, w=w, h=h)
    return boxes


def total_size(
    col_widths: list[float], row_heights: list[float], gap_x: float, gap_y: float
) -> tuple[float, float]:
    w = sum(col_widths) + gap_x * max(len(col_widths) - 1, 0)
    h = sum(row_heights) + gap_y * max(len(row_heights) - 1, 0)
    return (w, h)


def _offsets(sizes: list[float], gap: float) -> list[float]:
    out, acc = [], 0.0
    for s in sizes:
        out.append(acc)
        acc += s + gap
    return out
