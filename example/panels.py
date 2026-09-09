"""Panels used to exercise figalign.

Conventions (spec 6.4):
- the signature is (ax, data, size); figsize is injected, so never set it here
- put expensive loading and shared work in load_data(); editing a panel will not re-run it
"""

import numpy as np


def load_data():
    """The data layer. The result is held until this file's mtime changes."""
    rng = np.random.default_rng(0)
    n = 400
    x = rng.normal(size=n)
    return {
        "x": x,
        "y": 1.8 * x + rng.normal(scale=0.9, size=n),
        "t": np.linspace(0, 12, 500),
    }


def scatter_main(ax, data, size):
    ax.scatter(data["x"], data["y"], s=3, color="#1f77b4", alpha=0.7, linewidths=0)
    ax.set_xlabel("stimulus (a.u.)")
    ax.set_ylabel("response (mV)")


def timeseries(ax, data, size):
    t = data["t"]
    ax.plot(t, np.sin(t), label="control")
    ax.plot(t, np.sin(t) * np.exp(-t / 9), label="treated")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")
    ax.legend(frameon=False)


def histogram(ax, data, size):
    ax.hist(data["x"], bins=24, color="#555", linewidth=0)
    ax.set_xlabel("stimulus (a.u.)")
    ax.set_ylabel("count")
