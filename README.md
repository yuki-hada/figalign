**English** | [日本語](README.ja.md)

# figalign

Lay out paper figures at **true physical size**.

Panels drawn in Python get arranged in Illustrator, and the link to the data is cut there.
When review asks for different data, the arranging work is thrown away. figalign removes
that round trip.

```
layout declaration -> solver -> true size (mm) per panel -> matplotlib draws at that size -> pasted unscaled
```

Nothing is scaled afterwards, so font sizes and line widths never drift between panels.

## Install

```sh
git clone https://github.com/yuki-hada/figalign.git
cd figalign
pixi install
pixi run figalign example
# -> http://127.0.0.1:8765
```

pixi is the recommended route because cairosvg needs `libcairo`, a C library pip cannot
supply. conda-forge ships it, so PDF output works with no system package and no root --
which matters on a compute cluster.

To install into an existing analysis environment instead, use pip or uv. figalign runs your
`panels.py` in the same process, so it has to be able to import whatever your panels import:

```sh
pip install -e .            # or: uv pip install -e .
pip install -e '.[pdf]'     # for PDF output; also needs system cairo:
                            # macOS: brew install cairo / Debian: apt install libcairo2
```

Everything except composed PDF works without cairo: the preview, SVG output, live reload,
and single-panel PDF, which goes through matplotlib's own PDF backend.

## Run

```sh
pixi run figalign example                   # preview in the browser
pixi run figalign example -o figure.pdf     # write it out and exit
pixi run figalign example -o figure.svg
```

When the data lives on a compute server, start the server there and forward the port with
`ssh -L 8765:localhost:8765 <host>`.

## Writing a figure

`fig.toml`:

```toml
preset = "nature_double"        # the preset owns the width and the text style

grid = [["a", "a", "b"],        # the mosaic string "aab\ncdb" also works
        ["c", "d", "b"]]

row_heights = ["1fr", "0.7fr"]  # fr and mm may be mixed; fixed lengths are subtracted first
gap = "4mm"

[panels.a]
fn = "panels.py:scatter_main"

[panels.c]
src = "schema.svg"              # pour a hand-drawn asset into the cell
```

| Key | Default | Meaning |
|---|---|---|
| `preset` | `"default"` | `nature_single` / `nature_double` / `science_*` / `cell_*` / `default` |
| `grid` | one row, definition order | 2-D array or mosaic string; `"."` is an empty cell |
| `col_widths` `row_heights` | all `"1fr"` | `"1fr"` and `"25mm"` may be mixed |
| `gap` `gap_x` `gap_y` | `0` | spacing between axes frames |
| `width` | the preset width | override the total width |
| `height` | unset (`1fr` = 40mm) | total height; when set, fr splits the remainder |
| `labels` | `true` | auto-number panels a, b, c... |
| `data` | `panels.py:load_data` if present | entry point of the data layer |

`panels.py`:

```python
def load_data():
    """Expensive loading goes here; the result is held until the source changes"""
    return ...

def scatter_main(ax, data, size):
    """figsize is injected from outside; never decide the size in here"""
    ax.plot(data["x"], data["y"])
```

## Output

| URL | Contents |
|---|---|
| `/` | preview |
| `/ws` | push notification whenever a watched file changes |
| `/api/figure.svg` | the final SVG, composed according to the grid |
| `/api/figure.pdf` | the deliverable, converted with cairosvg |
| `/api/panel/{name}.svg` | a single panel (`?w=88mm&h=46mm`) |
| `/api/panel/{name}.pdf` | a single panel as PDF (`pdf.fonttype = 42`) |
| `/api/stats` | connected clients and render cache counters |

SVG keeps its text as text, so it stays small and editable. PDF outlines the text in
matplotlib first, so the file matches the preview glyph for glyph instead of being laid out
again by cairo. Pass `?text=keep` or `--keep-text` to leave it as text.

Either way the page comes out at the declared physical size.

## Axes frame alignment

Panels rendered independently do not line up, because the margin outside a frame is mostly
tick labels and those differ in width. figalign solves for the frames rather than the cells:

1. draw each panel once and measure `ax.get_tightbbox()` against `ax.get_position()`
2. solve so the frames share coordinates down a column
3. draw for real with an exact `figsize` and `subplots_adjust`

Two consequences:

- **`fr` divides the frames, not the cells.** Two columns of `1fr` get identical frame
  widths whatever their tick labels look like, and a fixed `"30mm"` track means a 30mm
  frame. The figure grows around them, so set `height` to pin the total instead.
- **`gap` is a floor.** It is the frame-to-frame distance and the labels live inside it, so
  where facing margins need more than `gap`, the spacing grows to fit them.

## The window

Editor on the left, preview on the right, with a divider you can drag.

`zoom` reads `fit / 50% / 75% / 100% true size / 150% / 200%` and defaults to `fit`. The
effective percentage is always shown beside it and turns amber below 100%, and `fit` only
ever shrinks -- judging a line weight at 78% would undo the point of the tool.

Switching to a panel tab outlines that panel's axes frame. `check` filters the preview to
greyscale or to protanopia / deuteranopia / tritanopia, to catch "these two series only
differ in hue" before the figure is printed.

## Editing in the browser

Tabs sit over the code: `data`, one per panel, then `layout`. Tabs pointing at the same file
share one buffer. The editor is CodeMirror from a CDN with no LSP and no completion, and
falls back to a plain textarea if the CDN is unreachable.

Save with ⌘S. The write lands on disk, the watcher notices, and every connected preview
redraws -- the same path an edit made in VS Code takes.

- **Writes carry a precondition.** The editor sends the digest it last read; if the file
  changed underneath, the server answers 409 and keeps the buffer.
- **Paths are validated.** `..`, absolute paths, symlinks pointing outside the project, and
  anything that is not `.py` / `.toml` / `.svg` are refused.

`undo` steps back through whole-file snapshots. They are held in the server's memory and are
lost when it restarts.

## Live reload

Each change is scoped to the layer it actually invalidates:

| Layer | Keyed on | Invalidated by |
|---|---|---|
| data | source of `load_data` + module-level source of its file | editing that loader or the shared code; any non-code file changing |
| drawing | source of the panel function + settled size + data key | editing that one panel, or its size changing |
| composition | nothing cached | every request; it is a few ms |

So touching `labels` in `fig.toml` redraws no panels, editing one panel function redraws
only that panel, and changing `gap` redraws everything because every size moved.

## Reproducibility

The geometry depends on the environment, not only on `fig.toml`: margins come from
`get_tightbbox()`, and what that returns depends on the tick locations and the fonts
matplotlib resolved. `pixi.lock` is committed so a clone resolves to the versions the
figures were checked against. Within a fixed environment the output is byte-identical
between runs.

## Status

- [x] 1. Render one panel to SVG at a given size and show it in the browser
- [x] 2. Grid declaration: compose several panels, auto-number labels
- [x] 3. watch + WebSocket + live preview
- [x] 4. Axes frame alignment (two-pass) — the core feature
- [x] PDF export of the composed figure
- [x] 5. Tab UI, journal presets, greyscale check

Still open: colorbars and shared axes (one panel is still one axes), and the `align_x` /
`align_y` opt-out for panels that should *not* be aligned.
