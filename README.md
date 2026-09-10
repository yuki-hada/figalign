**English** | [日本語](README.ja.md)

# figalign

Lay out paper figures at **true physical size**.

Draw panels in Python, take them to Illustrator to arrange, and the link to the data is cut
right there. When review asks for different data, the arranging work is thrown away.
figalign removes that round trip.

```
layout declaration -> solver -> true size (mm) per panel -> matplotlib draws at that size -> pasted unscaled
```

Because nothing is scaled afterwards, font sizes and line widths never drift between panels.

## Install

In a clone of this repository:

```sh
uv sync
uv run figalign example
```

`uv.lock` is committed, so this resolves to the exact versions the figures were checked
against. That matters more here than it usually does -- see below.

For PDF output, add the extra:

```sh
uv sync --extra pdf
```

cairosvg needs a system `libcairo`, which pip cannot supply. On macOS `brew install cairo`,
on Debian `apt install libcairo2`. Where there is no root -- a compute cluster, typically --
take the conda route instead, which ships cairo as a package:

```sh
micromamba create -n figalign -c conda-forge python=3.12 matplotlib fastapi uvicorn watchfiles cairosvg
micromamba run -n figalign python -m pip install -e . --no-deps
```

Everything except composed PDF works without cairo: the preview, SVG output, live reload,
and single-panel PDF, which goes through matplotlib's own PDF backend.

## Reproducibility

The figure's geometry is a function of the environment, not only of `fig.toml`. Margins are
measured from `get_tightbbox()`, and what that returns depends on the tick locations
matplotlib chose and on the fonts it resolved. A different matplotlib version can therefore
produce a differently sized figure from the same declaration. Pinning the environment is
what protects the output, which is why the lock file is committed rather than gitignored.

Given a fixed environment, the output is byte-identical between runs. Two settings are
needed for that and neither is the default:

- `svg.hashsalt` is fixed. Otherwise matplotlib names its clip paths and markers from
  `uuid4()` and the same figure differs on every render.
- The date is dropped from the metadata, in both the SVG and the PDF.

## Running

```sh
micromamba run -n figalign figalign example
# -> http://127.0.0.1:8765
```

Or write the figure out and skip the browser:

```sh
micromamba run -n figalign figalign example -o figure.pdf
micromamba run -n figalign figalign example -o figure.svg
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
| `/api/figure.pdf` | the deliverable, converted with cairosvg |
| `/api/panel/{name}.pdf` | a single panel as PDF (`pdf.fonttype = 42`) |
| `/api/stats` | connected clients and render cache counters |

The two formats are not the same output twice:

- **SVG keeps its text as text.** It stays small and can be opened in Illustrator, which is
  what makes it the preview format (spec 9).
- **PDF outlines the text first**, in matplotlib, before cairosvg sees the file. Otherwise
  two engines lay out the same figure -- matplotlib for the preview, cairo for the PDF --
  and they do not agree glyph for glyph; cairo also resolves the font itself, so a machine
  without the preset's font substitutes silently. Pass `?text=keep` or `--keep-text` to
  leave the text as text; the page is ~30% smaller and stays selectable.

The page comes out at the declared physical size: for a 180 x 90.31mm figure the MediaBox
is `0 0 510.23622 255.983244` pt, and a raster of the PDF puts every axes frame within
one pixel of where the solver placed it.

## Axes frame alignment

Rendering panels independently leaves their frames out of line, because the margin outside
a frame is mostly tick labels and those differ in width. figalign solves for the frames
instead of the cells (spec 5.2):

1. draw each panel once and measure `ax.get_tightbbox()` against `ax.get_position()`
2. solve so that the *inner* boxes -- the frames -- share coordinates down a column
3. draw for real with an exact `figsize` and `subplots_adjust`

Alignment does not depend on the measurement being exact, because step 3 pins the frame
where the solver put it. What the measurement decides is whether enough room was reserved
for the labels around it.

The two depend on each other -- matplotlib picks tick locations from the axes size, and the
labels are what the margin is made of -- so it iterates. Ordinary figures settle in two or
three passes; measurements are cached, so re-solving after an edit is free.

Two consequences worth knowing:

- **`fr` divides the frames, not the cells.** Two columns of `1fr` get identical frame
  widths whatever their tick labels look like. A fixed `"30mm"` track also means a 30mm
  frame. The figure grows around them, so a given `row_heights` yields a taller figure than
  outer-cell layout would. Set `height` to pin the total instead.
- **`gap` is a floor.** It is the frame-to-frame distance and the labels live inside it
  (spec 6.3), so where facing margins need more than `gap`, the spacing grows to fit them.
  Below that threshold `gap` has no effect; above it, it takes over.

## The window

Editor on the left, preview on the right, with a divider you can drag (double-click resets
it). Code wants height more than width, so the editor gets a full-height column rather than
a strip along the bottom. The default split leaves the preview wide enough for the preset at
true size; the width is remembered.

The `zoom` selector reads `fit / 50% / 75% / 100% true size / 150% / 200%` and defaults to
`fit`. The effective percentage is always displayed beside it, turning amber the moment it is
not 100%. Showing a
figure at 78% while someone judges whether a line is too heavy would undo the point of the
tool, so scaling is never silent and `fit` only ever shrinks -- it will not enlarge past true
size. Hovering the percentage reports the natural size, the room available, and what `fit`
would choose.

The natural size is taken from the millimetres the SVG declares, never from the laid-out
box: `#frame` sits inside `#zoomer`, whose width is what the previous call set to
natural x scale, so measuring the box would feed the scale back into its own input and the
figure would shrink further on every call.

## Editing in the browser

The editor is a tab strip over the code: `data`, one tab per panel, then `layout`.

A tab is a *view* of a file, not a slice of one. Several panels normally live in the same
`panels.py`, so those tabs share a single buffer and the tab only decides where to scroll --
with a buffer per tab, saving from one would throw away what was typed in another. The editor
is CodeMirror loaded from a CDN, with no LSP and no completion, because it exists for
nudging an axis range while watching the figure (spec 4, 7.1). If the CDN is unreachable it
falls back to a plain textarea, which still edits files.

Saving is explicit (⌘S). A dev server does not save your files for you; your editor does.

Nothing about saving is special-cased: the write lands on disk, the watcher notices, and
every connected preview redraws. An edit made here and an edit made in VS Code are the same
event (spec 3.4). Two consequences of taking that seriously:

- **Writes carry a precondition.** The editor sends the digest it last read; if the file
  changed underneath, the server answers 409 and the buffer is kept. Losing what you typed
  is worse than a stale file, and silently overwriting someone else's edit is worse than
  both.
- **Paths are validated, not trusted.** `..`, absolute paths, symlinks pointing outside the
  project, and anything that is not `.py` / `.toml` / `.svg` are refused. The server binds
  to localhost by default but `--host` can expose it.

Lines wrap: the column is deliberately narrow so the preview keeps its room, and ordinary
Python lines would otherwise need constant horizontal scrolling.

`undo` steps back through whole-file snapshots (spec 7.2 -- it is text, so nothing
cleverer is needed). They live in the server's memory and are **lost when it restarts**.

## Checking before you print

The `check` selector filters the preview: greyscale, and protanopia / deuteranopia /
tritanopia via `feColorMatrix`. It is there to catch "these two series only differ in hue"
before the figure is printed rather than after. The matrices preserve luminance, so a pair
that stays distinct under them is distinct for the reason you think it is.

Switching to a panel tab outlines that panel's axes frame in the preview. The preview is
rendered at true size, so an overlay positioned in mm lands exactly on the solved box.

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
- [x] 4. Axes frame alignment (two-pass) — the core feature
- [x] PDF export (composed figure, out of roadmap order: it is the deliverable)
- [x] 5. Tab UI, journal presets, greyscale check

The preset is shown read-only in the header and changed by editing `fig.toml` in the layout
tab. There is deliberately no preset dropdown: writing the setting back would mean rewriting
TOML programmatically, which loses the comments and formatting in the file the user owns.
Editing the declaration directly is the same principle as not generating code (spec 3.4).

Still open: colorbars and shared axes (one panel is still one axes), and the `align_x` /
`align_y` opt-out for panels that should *not* be aligned.
