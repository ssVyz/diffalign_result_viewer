# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-06-09

### Added

- **Export as image** now has an optional *Position range* section: tick
  "Limit to position range" and pick a start and end template position to
  render and export only that region (a zoom into a region of interest). The
  preview, ruler and subtitle update to the selected slice, and — when the
  metadata block is shown — a "Region" line records the rendered positions.

### Changed

- `build_overview_buffer` accepts optional per-grid column bounds so the live
  overview and the image export still render identically when a sub-range is
  requested.

## [0.1.2] - 2026-06-08

### Fixed

- Exported image metadata now reports the coverage threshold currently applied
  in the viewer (View → Coverage threshold) rather than the value recorded in
  the result file, so the label matches the colours actually shown.

## [0.1.1] - 2026-06-08

### Added

- **File → Export as image…** (Ctrl+E): exports the whole-template result
  overview as a PNG or JPEG. Opens a dialog with a live preview that uses the
  current display settings, with options for an editable title, colour legend,
  position ruler, an analysis/display-settings metadata block, output width,
  row height, and a dark/light background.

### Changed

- Extracted the overview's bird's-eye colour-buffer building into a shared
  `build_overview_buffer` helper so the live overview and the image export
  render identically.

## [0.1.0] - 2026-06-08

### Added

- Initial versioned release of the diffalign result viewer.
- `CHANGELOG.md` to track notable changes.
- `CLAUDE.md` with versioning and changelog conventions for agents.
