# diffalign result viewer

PySide6 desktop viewer for `diffalign` result JSON files. Companion to
the Rust CLI in `current_reference_tool/` and a clean rewrite of the
original Tauri/TypeScript program kept in `old_reference_program/`.

The viewer is read-only: it does not run analyses. It opens the
`ScreeningResults` JSON the CLI writes (schema documented in the CLI
repo's `results_format.md`) and presents it as an interactive heatmap
plus per-position drill-down.

## Running

```
uv sync
uv run diffalign-viewer              # empty window — File → Open to load
uv run diffalign-viewer path.json    # open a file directly
```

The script entry point is registered in `pyproject.toml`. `python main.py`
also works.

Tested on Windows 11 / Python 3.12. Files up to ~3 GB on disk have been
loaded successfully without OOM.

## Functionality

### File handling

* **Open / close / recent files.** File menu and `Ctrl+O` / `Ctrl+W`.
  Up to eight recent paths are persisted per user via `QSettings`.
* **Streaming load.** Files are parsed off the UI thread on a `QThread`;
  the status bar shows a progress bar and a "Cancel load" toolbar button.
  The bar tracks bytes read, scaled to a 0–10 000-tick range so it works
  for files larger than 2 GiB (`QProgressBar` is otherwise int32-bound).
* **Window state persistence.** Window geometry, dock layout, splitter
  sizes and the controls dock state are restored across sessions.

### Heatmap

* X axis: position along the template, Y axis: oligo length (one row per
  length present in `results_by_length`). Cells are coloured by the
  per-position `variants_for_threshold` count using the same green →
  yellow → red gradient as the legacy program.
* **Viewport rendering** — only the visible columns × rows are painted on
  each repaint. The widget is a `QAbstractScrollArea`, so scrollbars
  reflect the full virtual size without any large pixmap allocation.
* **Hover** shows a tooltip with the variant count, no-match fraction and
  (in differential mode) the minimum exclusivity mismatch count for that
  cell.
* **Click** populates the right-hand details dock for that
  (length, position) pair.
* **Zoom**: slider in the controls dock, or `Ctrl + mouse wheel`. Cell
  width scales from 30% to 400%; the position ruler stride adapts so
  labels stay readable at any zoom.
* **Scrolling**: vertical wheel scrolls vertically as usual; a true
  horizontal wheel/trackpad delta scrolls horizontally. A
  **Horizontal wheel** checkbox above the heatmap flips the mousewheel
  so it scrolls left/right instead of up/down. `Shift + wheel`
  multiplies the step size (works on whichever axis is active).
* **Search jump-to**: double-clicking a search result scrolls the
  heatmap to that template position.

### Differential mode

When the file's `differential_enabled` flag is true, the controls dock
exposes:

* a toggle to switch the cell colours from "variants needed" to
  exclusivity scoring,
* green-at / red-at thresholds (in mismatches),
* an "ignore if ≤ N seqs" cutoff for noisy off-targets.

The legend updates accordingly. The three exclusivity states are
distinguished:

* `min_mismatches = null` (no exclusivity sequence aligned — the *best*
  outcome): rendered green.
* low `min_mismatches` (off-target match): rendered red.
* in-between: yellow ramp.

The heatmap also darkens cells when the variant count or no-match
fraction is high, so a primer that is non-specific *and* hard to design
shows up as dark red regardless of mode.

### Sequence ruler & template row

* A position ruler above the heatmap shows 1-indexed template positions
  with adaptive stride (every 1 / 5 / 10 positions depending on zoom).
* The template sequence itself is drawn as a coloured base row above the
  grid, using the standard A/C/G/T palette.

### Annotations

Annotations from the file (`annotations[]` in the JSON) are drawn as
coloured horizontal bars above the position ruler. Overlapping
annotations stack into multiple rows. The arrow glyph (`→` / `←`)
indicates sense / antisense direction.

The viewer does not edit annotations — that responsibility is left to
whatever wrote the file.

### Search

* IUPAC-aware exact search across the template sequence, in both sense
  and antisense orientations.
* The query may include `R Y S W K M B D H V N` codes; the matcher
  expands each to the standard bases it covers.
* Hits are rendered as a translucent overlay on the template row; the
  results panel lists them with template coordinates and direction.
* Double-click a result to jump the heatmap to that position.

### Details dock

For the clicked cell, the right-hand dock shows:

* The position, oligo length and the template oligo at that window,
  rendered with per-base colouring and IUPAC codes styled distinctly
  (italic + underline + bold).
* Stats: total references, matched count, no-match count and percentage,
  variants needed for the active coverage threshold, and the actual
  coverage achieved at threshold (which can be **below** threshold —
  that case is rendered as-is rather than clamped).
* **Variants table**, in JSON order (`variants` is already sorted by
  count descending, so no re-sort). The threshold-boundary row is
  highlighted; cumulative percentage is shown alongside individual.
  A trailing "no match" row is appended when applicable.
* Display options for the variants table: reverse complement and
  codon (3-base) spacing, both togglable inline.
* **Exclusivity histogram** (when present): a bar chart with a separate
  colour-coded bar for the `u32::MAX` "no match" bucket — never rendered
  as `4 294 967 295 mismatches`. A table below the chart lists the same
  data with the example off-target name per bucket.
* Skipped windows are rendered as a single banner with the
  `skip_reason` text instead of the variants/exclusivity sections.

### Controls dock

* **View**: zoom slider, coverage threshold spinbox. Changing the
  coverage threshold recomputes `variants_for_threshold` and
  `coverage_at_threshold` for every position in place
  (`recompute_variants_for_threshold`) and triggers a heatmap repaint.
* **Color thresholds**: green-at / red-at variant counts, no-match OK / Bad
  percentages.
* **Differential mode**: enabled-toggle, green-at / red-at mismatch
  thresholds, ignore-if-aligned-≤-N filter. The whole group is disabled
  for non-differential files.

### Analysis parameters panel

A read-only summary of the file's `params` block (method, oligo length
range, resolution, coverage threshold, exclude-N, pairwise scoring,
thread count, template length, reference count, differential flag and
exclusivity sequence count). Two files for the same template can differ
entirely on parameters — this panel is the disambiguator.

### Compatibility with legacy files

Tauri-style files are accepted unchanged. Specifically:

* `params.thread_count` may be `"Auto"` *or* `{"Fixed": N}`.
* `params.length_skip` is treated as `0` when absent.
* `annotations` is treated as `[]` when absent.
* `params.method` may be either the bare string (`"NoAmbiguities"`) or
  the wrapped form (`{"NoAmbiguities": null}`); both parse identically.
* `min_mismatches = u32::MAX` (a value that should normally appear only
  inside the histogram, but defensively handled here too) is collapsed
  to `None` so it renders as the ideal-case green.

## Architecture

```
src/diffalign_viewer/
├── __main__.py           # entry point: QApplication, stylesheet, font
├── colors.py             # green-yellow-red gradient + vectorised RGBA fill
├── loader.py             # streaming ijson loader → compact data model
├── models.py             # numpy + slot-class data model
├── sequence.py           # IUPAC search, reverse complement, codon spacing
├── style.py              # dark Qt stylesheet
└── widgets/
    ├── controls.py       # ViewControls + ParamsPanel
    ├── detail.py         # VariantTableModel, ExclusivityTableModel,
    │                     # HistogramBar, ColorizedSequenceLabel, DetailPanel
    ├── heatmap.py        # HeatmapWidget (QAbstractScrollArea + QPainter)
    ├── legend.py         # color legend strip
    ├── loader_worker.py  # LoaderWorker (QObject) + LoaderController (QThread)
    ├── main_window.py    # QMainWindow shell, menus, dock layout, signals
    └── search.py         # SearchPanel
```

### Data model (`models.py`)

The Tauri program kept the entire JSON in a TypeScript object tree; for
multi-GB files that put the renderer dangerously close to OOM. Here the
model is split into a wide-but-cheap *summary* view (numpy arrays) and a
narrow-but-detailed *detail* view (per-position slot-classes).

```
ScreeningResults
  ├── params: AnalysisParams         # small, kept in full
  ├── template_sequence: str         # one big string, kept verbatim
  ├── annotations: list[Annotation]
  └── grids: list[LengthGrid]        # one per oligo length, ascending

LengthGrid                            # the heatmap-fast path
  ├── positions, variants_needed,    # ┐ aligned numpy.int32
  │   no_match_count, total_seqs,    # │ arrays — one entry per
  │   min_mismatches, excl_total,    # │ visible column. Skipped
  │   excl_no_match                  # │ positions are flagged in
  ├── skipped: numpy.bool_           # ┘ a parallel bool array.
  └── details: list[PositionDetail]  # full payload per column
```

`min_mismatches` carries three sentinels:

* `NO_MIN_MM_SENTINEL` (`-2`) — the JSON field was `null` (ideal case).
* `SKIPPED_SENTINEL` (`-1`) — the position was skipped.
* `NO_MATCH_SENTINEL` (`u32::MAX`) — defensive, never emitted by the CLI
  in this field; folded back to "ideal" by the loader.

`PositionDetail` keeps the full variants list and exclusivity histogram
for that cell. It's still a slot-class to dodge dict overhead, but it's
created lazily-ish: only as many as there are heatmap cells.

### Streaming loader (`loader.py`)

Two passes over the file with `ijson.parse` / `ijson.kvitems`:

1. **Pass 1** walks top-level scalars, the `params` subtree and
   `annotations` items. The `results_by_length` subtree is skipped by
   tracking start/end events — the events still flow but we don't
   buffer them.
2. **Pass 2** uses `ijson.kvitems(stream, "results_by_length")` to yield
   one `LengthResult` at a time. Each result is converted into a
   `LengthGrid` and the source dict is allowed to drop. The Python
   garbage collector therefore frees each length's intermediate dict
   tree before the next is parsed, keeping peak RAM bounded by the
   largest single length and not the file size.

The loader emits progress callbacks throttled to ~4 MB granularity so
the UI thread isn't flooded with paint requests.

### Worker thread (`widgets/loader_worker.py`)

`LoaderWorker` runs `load_results` on a `QThread`. Two practical
gotchas drove the API shape:

* Qt `Signal(int, ...)` maps to a 4-byte signed C int, which overflows
  for files >2 GiB. The progress signal is therefore typed as
  `Signal("qint64", "qint64", str)`.
* A `QProgressBar` value is also int32. The main window scales the
  byte count to a 0–10 000 tick range before forwarding it to the bar.

A `LoaderController` owns the thread+worker lifecycle, exposes a
plain Qt-signal API (`progress`, `finished`, `failed`, `cancelled`) and
cleans both up on completion. Cancellation flows from
`LoaderController.cancel()` into a flag the worker checks at every
ijson event.

### Heatmap (`widgets/heatmap.py`)

`HeatmapWidget` extends `QAbstractScrollArea`. On `paintEvent` it:

1. Computes `col_start`/`col_end` from the horizontal scrollbar value
   and viewport width — a couple of integer divisions, no per-cell
   visibility test.
2. Slices the relevant numpy arrays for the visible column range.
3. Calls `colorize_grid_rgba` (or `colorize_grid_differential_rgba`) on
   the slice. These functions vectorise the gradient computation in
   numpy: one `np.clip` for the green→red mix, one for the no-match
   darkening, one for differential `min_mismatches` mapping. The result
   is an `(N_visible, 4) uint8` array.
4. Iterates the slice and calls `QPainter.fillRect` once per visible
   cell. The annotation bars, position ruler, template bases and search
   highlights are all painted as small vector primitives over the same
   `QPainter`.

Cost per repaint is therefore O(visible_cells), independent of template
length. Search hits map template-position ranges to column ranges via
`numpy.searchsorted` against the first grid's positions array.

Mouse handling is a single `_hit_test` integer arithmetic check; tooltip
showing is rate-limited to the cell granularity.

### Detail dock (`widgets/detail.py`)

Variants are rendered through a `QAbstractTableModel`
(`VariantTableModel`); the view never instantiates rows that aren't on
screen, so a 10 000-variant cell still opens instantly. The model
formats sequences on demand, which means toggling the reverse-complement
or codon-spacing checkboxes only re-emits `dataChanged` for the
sequence column instead of resetting the whole model.

The exclusivity histogram (`HistogramBar`) is a custom-painted
`QFrame` — a few `fillRect` calls per bucket — to avoid a `pyqtgraph`
or `matplotlib` dependency for what is fundamentally one bar chart.

### Recompute on threshold change

`loader.recompute_variants_for_threshold(grid, threshold_pct)` walks the
per-position variants once and rewrites `variants_for_threshold`,
`coverage_at_threshold` and the corresponding numpy slot in
`grid.variants_needed`. It runs on the UI thread because for the
sizes seen in practice (≤ 10⁵ positions × ≤ 10² variants) it completes
in tens of milliseconds. Larger files would warrant moving this to a
worker; the current cost has not been a problem with 3 GB files.

## Performance characteristics observed

* 3 GB JSON file: load time on the order of a few minutes, peak resident
  set well below the file size on disk; heatmap interactive zoom/scroll
  feels instant.
* 20 MB synthetic file (5 000 positions × 4 lengths × ~10 variants/cell):
  parsed in ~2.6 s.
* Per-frame paint: bounded by viewport size, typically a few hundred
  cells, regardless of template length.

## Dependencies

* `PySide6` (Qt 6 bindings)
* `ijson` (incremental JSON parser, used as the SAX-style backbone)
* `numpy` (per-cell summary arrays + vectorised colour math)

Managed via `uv` from `pyproject.toml`.
