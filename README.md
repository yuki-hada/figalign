# figalign

Lay out paper figures at **true physical size**.

Draw panels in Python, take them to Illustrator to arrange, and the link to the data is cut
right there. When review asks for different data, the arranging work is thrown away.
figalign removes that round trip.

```
layout declaration -> solver -> true size (mm) per panel -> matplotlib draws at that size -> pasted unscaled
```

Because nothing is scaled afterwards, font sizes and line widths never drift between panels.

## Development environment

```sh
micromamba create -n figalign -c conda-forge python=3.12 matplotlib fastapi uvicorn watchfiles
micromamba run -n figalign python -m pip install -e . --no-deps
```

## Running

```sh
micromamba run -n figalign figalign example
# -> http://127.0.0.1:8765
```

When the data lives on a compute server, start the server there and forward the port with
`ssh -L 8765:localhost:8765 <host>`; the preview then works in the browser on your own machine.

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
| `gap` `gap_x` `gap_y` | `0` | spacing between cells |
| `width` | the preset width | override the total width |
| `height` | unset (`1fr` = 40mm) | total height; when set, fr splits the remainder |
| `labels` | `true` | auto-number panels a, b, c... |
| `data` | `panels.py:load_data` if present | entry point of the data layer |

`panels.py`:

```python
def load_data():
    """Expensive loading goes here; the result is held until the mtime changes"""
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
| `/api/panel/{name}.svg` | a single panel (`?w=88mm&h=46mm`) |
| `/api/panel/{name}.pdf` | a single panel as PDF (`pdf.fonttype = 42`) |
| `/api/stats` | connected clients and render cache counters |

Composed PDF output does not exist yet; the SVG-to-PDF route (cairosvg or Typst) still has
to be chosen.

## Live reload

Editing `fig.toml` or `panels.py` on disk updates the preview. Editing in VS Code and
editing through anything figalign itself grows later travel the same path, because the
watcher is the only trigger and the file on disk is the only source of truth.

Each change is scoped to the layer it actually invalidates:

| Layer | Keyed on | Invalidated by |
|---|---|---|
| data | source of `load_data` + module-level source of its file | editing that loader or the shared code; any non-code file changing |
| drawing | source of the panel function + settled size + data key | editing that one panel, or its size changing |
| composition | nothing cached | every request; it is a few ms |

So touching `labels` in `fig.toml` redraws no panels, editing one panel function redraws
only that panel, and changing `gap` redraws everything because every size moved.

Note that panel modules are compiled directly rather than imported through the bytecode
cache. A `.pyc` records the source mtime with one-second resolution and validates on
(mtime, size), so an edit within the same second that keeps the file length -- changing a
bin count or a colour -- would otherwise be served from stale bytecode.

## Status

Progress against the roadmap.

- [x] 1. Render one panel to SVG at a given size and show it in the browser
- [x] 2. Grid declaration: compose several panels, auto-number labels
- [x] 3. watch + WebSocket + live preview
- [ ] 4. Axes frame alignment (two-pass) — the core feature
- [ ] 5. Tab UI, journal presets, greyscale check

Panels are aligned by their outer cell boxes today, so adjacent axes frames do not line up
yet. That is what step 4 fixes.
