"""Reading fig.toml.

Layout values get their types settled here; converting them to true sizes belongs to
grid and layout.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import loader
from .grid import EMPTY, Cell, GridError, find_cells, normalize_grid
from .presets import Preset, get_preset
from .units import UnitError, parse_length

FIG_TOML = "fig.toml"
DEFAULT_PANEL_MODULE = "panels.py"


class SpecError(ValueError):
    """The contents of fig.toml do not match the specification."""


@dataclass(frozen=True)
class PanelDef:
    name: str
    fn: str | None = None  # "panels.py:scatter_main"
    src: str | None = None  # an external asset such as a hand-drawn SVG

    @property
    def kind(self) -> str:
        return "fn" if self.fn else "src"


@dataclass(frozen=True)
class FigSpec:
    root: Path
    preset: Preset
    panels: dict[str, PanelDef]
    data_ref: str | None
    grid: list[list[str]]
    cells: dict[str, Cell]
    col_widths: list[Any] | None
    row_heights: list[Any] | None
    gap_x_mm: float
    gap_y_mm: float
    width_mm: float
    height_mm: float | None
    labels: bool
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def order(self) -> list[str]:
        """Reading order over the grid, used to auto-number labels (spec 6.3)."""
        return [c.name for c in sorted(self.cells.values(), key=lambda c: c.order_key)]

    @property
    def n_cols(self) -> int:
        return len(self.grid[0])

    @property
    def n_rows(self) -> int:
        return len(self.grid)

    def panel(self, name: str) -> PanelDef:
        try:
            return self.panels[name]
        except KeyError:
            known = ", ".join(self.panels) or "(なし)"
            raise SpecError(f"パネル {name!r} は fig.toml に無い (定義済み: {known})") from None


def load_spec(root: Path) -> FigSpec:
    path = root / FIG_TOML
    if not path.is_file():
        raise FileNotFoundError(f"{FIG_TOML} が無い: {path}")
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        # Half-finished TOML is the normal state of a file being edited, so this has to
        # surface as an ordinary message rather than a server error (spec 7.3).
        raise SpecError(f"{FIG_TOML} の構文エラー: {exc}") from None
    return build_spec(root, raw)


def build_spec(root: Path, raw: dict[str, Any]) -> FigSpec:
    preset = get_preset(raw.get("preset"))

    panels_raw = raw.get("panels", {})
    if not isinstance(panels_raw, dict):
        raise SpecError("[panels.*] はテーブルで書く")

    panels: dict[str, PanelDef] = {}
    for name, body in panels_raw.items():
        if not isinstance(body, dict):
            raise SpecError(f"[panels.{name}] はテーブルで書く")
        fn, src = body.get("fn"), body.get("src")
        if fn and src:
            raise SpecError(f"[panels.{name}] は fn と src の両方を持てない")
        if not fn and not src:
            raise SpecError(f"[panels.{name}] に fn か src が必要")
        panels[name] = PanelDef(name=name, fn=fn, src=src)

    if not panels:
        raise SpecError("パネルが1つも定義されていない")

    grid, cells = _build_grid(raw, panels)

    # The preset decides the width (spec 3.3); `width` is the escape hatch for other formats.
    width_mm = _length(raw, "width", default=preset.width_mm)
    height_mm = _length(raw, "height", default=None)

    gap_mm = _length(raw, "gap", default=0.0)
    gap_x_mm = _length(raw, "gap_x", default=gap_mm)
    gap_y_mm = _length(raw, "gap_y", default=gap_mm)

    labels = raw.get("labels", True)
    if not isinstance(labels, bool):
        raise SpecError("labels は true / false で書く")

    # Use an explicit `data` when given, otherwise look for load_data() in panels.py.
    data_ref = raw.get("data")
    if data_ref is None:
        data_ref = loader.find_data_ref(root, DEFAULT_PANEL_MODULE)

    return FigSpec(
        root=root,
        preset=preset,
        panels=panels,
        data_ref=data_ref,
        grid=grid,
        cells=cells,
        col_widths=_tracks(raw, "col_widths"),
        row_heights=_tracks(raw, "row_heights"),
        gap_x_mm=gap_x_mm,
        gap_y_mm=gap_y_mm,
        width_mm=width_mm,
        height_mm=height_mm,
        labels=labels,
        raw=raw,
    )


def _build_grid(
    raw: dict[str, Any], panels: dict[str, PanelDef]
) -> tuple[list[list[str]], dict[str, Cell]]:
    """Normalise the grid and check it against [panels.*].

    With no grid, the panels are treated as a single row in definition order.
    """
    if "grid" not in raw:
        return ([list(panels)], find_cells([list(panels)]))

    try:
        grid = normalize_grid(raw["grid"])
        cells = find_cells(grid)
    except GridError as exc:
        raise SpecError(str(exc)) from None

    missing = [n for n in cells if n not in panels]
    if missing:
        raise SpecError(
            f"grid にあるが [panels.*] に定義が無い: {', '.join(sorted(missing))}"
        )
    unplaced = [n for n in panels if n not in cells]
    if unplaced:
        raise SpecError(
            f"[panels.*] にあるが grid に置かれていない: {', '.join(unplaced)} "
            f"(空セルは {EMPTY!r} で書く)"
        )
    return grid, cells


def _length(raw: dict[str, Any], key: str, default: float | None) -> float | None:
    if key not in raw:
        return default
    try:
        return parse_length(raw[key])
    except UnitError as exc:
        raise SpecError(f"{key}: {exc}") from None


def _tracks(raw: dict[str, Any], key: str) -> list[Any] | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, list):
        raise SpecError(f"{key} は配列で書く (例: [\'1fr\', \'0.7fr\'])")
    return value
