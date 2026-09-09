"""figalign - lay out paper figures at true physical size."""

from .presets import PRESETS, Preset, get_preset
from .render import PanelRenderError, PanelSize, render_pdf, render_svg

__version__ = "0.0.1"

__all__ = [
    "PRESETS",
    "PanelRenderError",
    "PanelSize",
    "Preset",
    "get_preset",
    "render_pdf",
    "render_svg",
]
