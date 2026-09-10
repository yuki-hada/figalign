"""Journal presets.

The preset owns the figure width and the text style; the user is not asked to decide them
every time (spec 3.3). Line widths are pinned here too: inconsistent line weight across
panels is a main cause of amateurish figures, so it ranks alongside font size.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    width_mm: float
    font_size_pt: float
    font_family: str
    line_width_pt: float = 0.5
    axes_line_width_pt: float = 0.5
    tick_length_pt: float = 2.0

    def rc_params(self) -> dict[str, object]:
        """rcParams owned by this preset. Panel functions may override them (spec 6.4)."""
        return {
            # Mandatory output settings (spec 9, 11)
            "pdf.fonttype": 42,  # the default Type 3 gets rejected by many journals
            "ps.fonttype": 42,
            "svg.fonttype": "none",  # keep text as <text> for the preview
            # Without a fixed salt matplotlib names its clip paths and markers from uuid4(),
            # so the same figure produces a different file on every run. That defeats both
            # reproducible output and putting an exported SVG under version control.
            "svg.hashsalt": "figalign",
            # Text
            "font.family": "sans-serif",
            "font.sans-serif": [self.font_family, "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": self.font_size_pt,
            "axes.titlesize": self.font_size_pt,
            "axes.labelsize": self.font_size_pt,
            "xtick.labelsize": self.font_size_pt,
            "ytick.labelsize": self.font_size_pt,
            "legend.fontsize": self.font_size_pt,
            "mathtext.fontset": "dejavusans",
            # Lines
            "lines.linewidth": self.line_width_pt,
            "patch.linewidth": self.line_width_pt,
            "axes.linewidth": self.axes_line_width_pt,
            "grid.linewidth": self.axes_line_width_pt,
            "xtick.major.width": self.axes_line_width_pt,
            "ytick.major.width": self.axes_line_width_pt,
            "xtick.major.size": self.tick_length_pt,
            "ytick.major.size": self.tick_length_pt,
            # No decorative frames
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "none",
            "axes.facecolor": "none",
            "savefig.facecolor": "none",
            "savefig.transparent": True,
        }


# Widths come from each journal's submission guidelines. Font sizes sit near the stated minimum.
PRESETS: dict[str, Preset] = {
    "nature_single": Preset("nature_single", 89.0, 7.0, "Helvetica"),
    "nature_double": Preset("nature_double", 180.0, 7.0, "Helvetica"),
    "science_single": Preset("science_single", 55.0, 7.0, "Helvetica"),
    "science_double": Preset("science_double", 178.0, 7.0, "Helvetica"),
    "cell_single": Preset("cell_single", 85.0, 7.0, "Arial"),
    "cell_double": Preset("cell_double", 174.0, 7.0, "Arial"),
    # For when the target journal is not decided yet
    "default": Preset("default", 170.0, 8.0, "Helvetica"),
}


def get_preset(name: str | None) -> Preset:
    if name is None:
        return PRESETS["default"]
    try:
        return PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise KeyError(f"unknown preset: {name!r} (available: {known})") from None
