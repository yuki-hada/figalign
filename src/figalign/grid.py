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
            raise GridError("grid が空")
        if all(isinstance(r, str) for r in raw):
            # mosaic notation written one row per string, single-character names
            rows = [list(r.strip()) for r in raw if r.strip()]
        elif all(isinstance(r, list) for r in raw):
            rows = [[str(c) for c in r] for r in raw]
        else:
            raise GridError("grid の行は文字列か配列で揃える")
    else:
        raise GridError(f"grid の型が不正: {type(raw).__name__}")

    if not rows:
        raise GridError("grid が空")
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise GridError(f"grid の行の長さが揃っていない: {sorted(widths)}")
    return rows


def find_cells(rows: list[list[str]]) -> dict[str, Cell]:
    """Find the range each name occupies, rejecting non-rectangular spans (L shapes)."""
    positions: dict[str, list[tuple[int, int]]] = {}
    for r, row in enumerate(rows):
        for c, name in enumerate(row):
            if name != EMPTY:
                positions.setdefault(name, []).append((r, c))

    if not positions:
        raise GridError("grid にパネルが1つも無い")

    cells: dict[str, Cell] = {}
    for name, pos in positions.items():
        rs = [r for r, _ in pos]
        cs = [c for _, c in pos]
        row0, row1 = min(rs), max(rs) + 1
        col0, col1 = min(cs), max(cs) + 1
        expected = (row1 - row0) * (col1 - col0)
        if len(pos) != expected:
            raise GridError(f"パネル {name!r} の占める範囲が矩形でない")
        cells[name] = Cell(name, row0, col0, row1, col1)
    return cells


def parse_track(value: object) -> tuple[str, float]:
    """Read a track spec as either `("fr", 1.0)` or `("mm", 12.0)`."""
    if isinstance(value, str):
        m = _FR.match(value)
        if m:
            weight = float(m.group(1))
            if weight <= 0:
                raise GridError(f"fr は正の値で指定する: {value!r}")
            return ("fr", weight)
    try:
        return ("mm", parse_length(value))  # type: ignore[arg-type]
    except UnitError:
        raise GridError(f"トラック指定が読めない: {value!r} (例: '1fr', '25mm')") from None


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
        raise GridError(f"トラック指定が {len(specs)} 個、grid は {count} 本")

    tracks = [parse_track(s) for s in specs]
    gaps_mm = gap_mm * max(count - 1, 0)

    if total_mm is None:
        return [v if kind == "mm" else v * fr_base_mm for kind, v in tracks]

    fixed = sum(v for kind, v in tracks if kind == "mm")
    weights = sum(v for kind, v in tracks if kind == "fr")
    remainder = total_mm - fixed - gaps_mm
    if weights > 0 and remainder <= 0:
        raise GridError(
            f"固定長 {fixed:.4g}mm + gap {gaps_mm:.4g}mm が全体 {total_mm:.4g}mm を超えている"
        )
    return [v if kind == "mm" else remainder * v / weights for kind, v in tracks]


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
