"""Length units. Everything is millimetres internally; inches only at the matplotlib boundary."""

from __future__ import annotations

import re

MM_PER_IN = 25.4
PT_PER_IN = 72.0

_LENGTH = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*(mm|cm|in|pt)?\s*$")

_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "in": MM_PER_IN,
    "pt": MM_PER_IN / PT_PER_IN,
}


class UnitError(ValueError):
    """The value could not be read as a length literal."""


def parse_length(value: str | float | int) -> float:
    """Return a length literal in mm. A bare number is taken as mm."""
    if isinstance(value, (int, float)):
        return float(value)
    m = _LENGTH.match(str(value))
    if m is None:
        raise UnitError(f"長さとして読めない: {value!r} (例: '89mm', '3.5in', 12)")
    number, unit = m.groups()
    return float(number) * _TO_MM[unit or "mm"]


def mm_to_in(mm: float) -> float:
    return mm / MM_PER_IN


def mm_to_pt(mm: float) -> float:
    return mm / MM_PER_IN * PT_PER_IN


def pt_to_mm(pt: float) -> float:
    return pt / PT_PER_IN * MM_PER_IN
