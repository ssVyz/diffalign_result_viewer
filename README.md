# diffalign result viewer

PySide6 viewer for `diffalign` result JSON files. Companion to the Rust
CLI in `current_reference_tool/` and a clean rewrite of the Tauri/TypeScript
program kept in `old_reference_program/`.

## Run

```
uv run diffalign-viewer            # empty window — open a file via File → Open
uv run diffalign-viewer path.json  # open a file directly
```

The viewer accepts the `ScreeningResults` JSON written by the CLI (see
`results_format.md` in the CLI repo).

## Architecture

```
src/diffalign_viewer/
├── __main__.py           # entry point, applies stylesheet
├── colors.py             # vectorised color gradients (numpy)
├── loader.py             # streaming ijson loader; builds compact arrays
├── models.py             # slot-class + numpy-backed data model
├── sequence.py           # IUPAC search, reverse complement, codon spacing
├── style.py              # dark stylesheet (QMainWindow + dock widgets)
└── widgets/
    ├── controls.py       # color thresholds + analysis-params summary
    ├── detail.py         # variants table + exclusivity histogram
    ├── heatmap.py        # viewport-based heatmap (QAbstractScrollArea)
    ├── legend.py         # color legend strip
    ├── loader_worker.py  # QThread wrapper around the streaming loader
    ├── main_window.py    # QMainWindow shell, menus, status bar
    └── search.py         # IUPAC-aware sequence search panel
```

## Memory & responsiveness notes

* Files are parsed via `ijson` rather than `json.load`, so the JSON tree
  is never materialised in full. Per-position summaries are stored in
  `numpy.int32` arrays (`LengthGrid` in `models.py`), and per-position
  variants are kept in slot-classes — there are no Python dicts in the
  hot path.
* Loading runs on a `QThread`; the UI shows a progress bar and a cancel
  button. Memory cost is dominated by the variant strings, not the file
  size on disk.
* The heatmap is a `QAbstractScrollArea` that paints only the visible
  columns × rows. Cell colours are computed in vectorised numpy. Even
  for 10 000 × 8 grids the per-frame work is bounded by viewport size,
  not template size.
* Search highlights and annotation bars are drawn as cheap vector
  primitives during paint, not stored as a giant precomputed pixmap.
