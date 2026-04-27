"""Streaming JSON loader for diffalign result files.

`ScreeningResults` JSON files can be multi-GB. We use ijson to walk the
stream once, materializing the heatmap summary into numpy arrays and the
per-position variant lists into compact slot-classes so we never have to
hold a full Python dict tree of the file in memory.

The loader is designed to run on a worker thread; it accepts a
`progress_cb(current_bytes, total_bytes, message)` for UI updates and a
`cancel_cb()` that returns True to abort early.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Callable
from typing import Any

import ijson
import numpy as np

from .models import (
    NO_MATCH_SENTINEL,
    NO_MIN_MM_SENTINEL,
    SKIPPED_SENTINEL,
    Annotation,
    AnalysisParams,
    ExclusivityResult,
    LengthGrid,
    MismatchBucket,
    PositionDetail,
    ScreeningResults,
    Variant,
)

ProgressCb = Callable[[int, int, str], None] | None
CancelCb = Callable[[], bool] | None


class LoadCancelled(Exception):
    pass


class _CountingFile(io.RawIOBase):
    """Wraps a binary file and counts bytes read so we can report progress."""

    def __init__(self, fh: io.BufferedReader) -> None:
        self._fh = fh
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buf):  # type: ignore[override]
        data = self._fh.read(len(buf))
        n = len(data)
        if n:
            buf[:n] = data
            self.bytes_read += n
        return n

    def close(self) -> None:
        try:
            self._fh.close()
        finally:
            super().close()


def _emit(progress_cb: ProgressCb, current: int, total: int, msg: str) -> None:
    if progress_cb is not None:
        progress_cb(current, total, msg)


def _check_cancel(cancel_cb: CancelCb) -> None:
    if cancel_cb is not None and cancel_cb():
        raise LoadCancelled()


def load_results(
    path: str,
    progress_cb: ProgressCb = None,
    cancel_cb: CancelCb = None,
) -> ScreeningResults:
    """Stream-parse a diffalign result JSON into a ScreeningResults object.

    Memory usage scales with the number of variants in the file, not with
    the JSON file size on disk (whitespace is dropped, dict overhead is
    avoided in favour of slot-classes / numpy arrays).
    """

    file_size = os.path.getsize(path)

    # Pass 1 — top-level scalars and nested params/template/annotations.
    # We prefer to use a small `parse()` walk to grab everything except the
    # large `results_by_length` block, which we handle in pass 2 with
    # streaming `kvitems`.
    params: AnalysisParams | None = None
    template_length = 0
    total_sequences = 0
    template_sequence = ""
    differential_enabled = False
    exclusivity_sequence_count: int | None = None
    annotations: list[Annotation] = []

    fh = open(path, "rb")
    counter = _CountingFile(fh)
    try:
        # Use ijson to walk top-level fields. We hand off the long
        # results_by_length to a second pass to keep this code legible.
        parser = ijson.parse(counter, use_float=True)

        depth = 0
        current_key: list[str] = []  # stack of map keys
        in_results_by_length = False
        skip_subtree_depth = 0  # >0 while we skip events inside results_by_length

        # Buffers for nested structures
        params_buf: dict[str, Any] | None = None
        params_stack: list[Any] = []
        params_keys: list[str | None] = []

        anno_buf: dict[str, Any] | None = None
        anno_stack: list[Any] = []
        anno_keys: list[str | None] = []

        last_progress_emit = 0

        for prefix, event, value in parser:
            _check_cancel(cancel_cb)

            # progress (rate-limited)
            if counter.bytes_read - last_progress_emit > 4_000_000:
                last_progress_emit = counter.bytes_read
                _emit(progress_cb, counter.bytes_read, file_size, "Reading file…")

            # Skip the whole results_by_length subtree on this pass.
            # ijson emits events with prefix starting "results_by_length"
            # for everything inside. We use that to detect entry/exit.
            if prefix == "results_by_length" and event in ("start_map", "start_array"):
                in_results_by_length = True
                skip_subtree_depth += 1
                continue
            if in_results_by_length:
                if event in ("start_map", "start_array"):
                    skip_subtree_depth += 1
                elif event in ("end_map", "end_array"):
                    skip_subtree_depth -= 1
                    if skip_subtree_depth == 0:
                        in_results_by_length = False
                continue

            # Top-level scalars
            if prefix == "template_length" and event == "number":
                template_length = int(value)
            elif prefix == "total_sequences" and event == "number":
                total_sequences = int(value)
            elif prefix == "template_sequence" and event == "string":
                template_sequence = value
            elif prefix == "differential_enabled" and event == "boolean":
                differential_enabled = bool(value)
            elif prefix == "exclusivity_sequence_count":
                if event == "number":
                    exclusivity_sequence_count = int(value)
                elif event == "null":
                    exclusivity_sequence_count = None

            # `params` subtree — buffer into a plain dict.
            elif prefix.startswith("params"):
                if prefix == "params" and event == "start_map":
                    params_buf = {}
                    params_stack = [params_buf]
                    params_keys = [None]
                elif prefix == "params" and event == "end_map":
                    params = AnalysisParams.from_json(params_buf or {})
                    params_buf = None
                else:
                    _ingest_event(params_stack, params_keys, prefix, event, value)

            # `annotations` array — buffer item-by-item.
            elif prefix.startswith("annotations"):
                if prefix == "annotations.item" and event == "start_map":
                    anno_buf = {}
                    anno_stack = [anno_buf]
                    anno_keys = [None]
                elif prefix == "annotations.item" and event == "end_map":
                    if anno_buf:
                        annotations.append(
                            Annotation(
                                name=str(anno_buf.get("name", "")),
                                start=int(anno_buf.get("start", 0)),
                                end=int(anno_buf.get("end", 0)),
                                direction=str(anno_buf.get("direction", "sense")),
                            )
                        )
                    anno_buf = None
                elif anno_buf is not None:
                    _ingest_event(anno_stack, anno_keys, prefix, event, value)
    finally:
        counter.close()

    if params is None:
        params = AnalysisParams()

    # Pass 2 — stream the per-length results.
    grids: list[LengthGrid] = []

    fh2 = open(path, "rb")
    counter2 = _CountingFile(fh2)
    try:
        _emit(progress_cb, 0, file_size, "Loading per-length results…")
        # `kvitems("results_by_length")` yields (key, value) pairs where
        # value is the fully-parsed LengthResult. ijson's incremental parse
        # means each value is materialized on the fly without keeping
        # earlier ones in memory.
        last_progress_emit = 0
        for key, length_result in ijson.kvitems(counter2, "results_by_length", use_float=True):
            _check_cancel(cancel_cb)
            try:
                oligo_length = int(key)
            except ValueError:
                continue
            grids.append(_build_length_grid(oligo_length, length_result))

            if counter2.bytes_read - last_progress_emit > 4_000_000:
                last_progress_emit = counter2.bytes_read
                _emit(
                    progress_cb,
                    counter2.bytes_read,
                    file_size,
                    f"Loading length {oligo_length} bp…",
                )
    finally:
        counter2.close()

    grids.sort(key=lambda g: g.oligo_length)

    _emit(progress_cb, file_size, file_size, "Finalizing…")

    return ScreeningResults(
        params=params,
        template_length=template_length,
        total_sequences=total_sequences,
        template_sequence=template_sequence,
        differential_enabled=differential_enabled,
        exclusivity_sequence_count=exclusivity_sequence_count,
        annotations=annotations,
        grids=grids,
    )


def _ingest_event(
    stack: list[Any], keys: list[str | None], prefix: str, event: str, value: Any
) -> None:
    """Generic event ingester that builds a Python tree from ijson events.

    Used for small subtrees (params, annotation items). Not used for large
    subtrees because the parse cost is fine but the resulting Python tree
    would dominate memory.
    """
    if event == "map_key":
        keys[-1] = value
    elif event == "start_map":
        new_map: dict[str, Any] = {}
        _attach(stack, keys, new_map)
        stack.append(new_map)
        keys.append(None)
    elif event == "end_map":
        stack.pop()
        keys.pop()
    elif event == "start_array":
        new_arr: list[Any] = []
        _attach(stack, keys, new_arr)
        stack.append(new_arr)
        keys.append(None)
    elif event == "end_array":
        stack.pop()
        keys.pop()
    elif event in ("string", "number", "boolean", "null"):
        _attach(stack, keys, value)


def _attach(stack: list[Any], keys: list[str | None], value: Any) -> None:
    if not stack:
        return
    parent = stack[-1]
    if isinstance(parent, dict):
        k = keys[-1]
        if k is not None:
            parent[k] = value
            keys[-1] = None
    elif isinstance(parent, list):
        parent.append(value)


def _build_length_grid(oligo_length: int, length_result: dict[str, Any]) -> LengthGrid:
    positions = length_result.get("positions") or []
    n = len(positions)
    grid = LengthGrid(oligo_length=oligo_length, n=n)
    details: list[PositionDetail] = grid.details

    for i, pr in enumerate(positions):
        analysis = pr.get("analysis") or {}
        skipped = bool(analysis.get("skipped", False))
        position_idx = int(pr.get("position", 0))
        variants_needed = int(pr.get("variants_needed", 0))
        no_match_count = int(analysis.get("no_match_count", 0))
        total_sequences = int(analysis.get("total_sequences", 0))

        grid.positions[i] = position_idx
        grid.variants_needed[i] = variants_needed
        grid.no_match_count[i] = no_match_count
        grid.total_sequences[i] = total_sequences
        grid.skipped[i] = skipped

        # Variants
        variants_raw = analysis.get("variants") or []
        variants_list = [
            Variant(
                sequence=str(v.get("sequence", "")),
                count=int(v.get("count", 0)),
                percentage=float(v.get("percentage", 0.0)),
            )
            for v in variants_raw
        ]

        # Exclusivity
        excl_raw = pr.get("exclusivity")
        excl: ExclusivityResult | None = None
        if excl_raw is not None:
            excl_total = int(excl_raw.get("total_sequences", 0))
            excl_no_match = int(excl_raw.get("no_match_count", 0))
            min_mm_raw = excl_raw.get("min_mismatches")
            min_mm = None if min_mm_raw is None else int(min_mm_raw)
            # Defensive: if a file ever stored u32::MAX in min_mismatches,
            # treat it as "no aligned exclusivity sequences" (the same
            # ideal-case semantics as null).
            if min_mm is not None and min_mm >= NO_MATCH_SENTINEL:
                min_mm = None

            histogram_raw = excl_raw.get("mismatch_histogram") or []
            histogram = [
                MismatchBucket(
                    mismatches=int(b.get("mismatches", 0)),
                    count=int(b.get("count", 0)),
                    example_name=str(b.get("example_name", "")),
                )
                for b in histogram_raw
            ]
            excl = ExclusivityResult(
                total_sequences=excl_total,
                no_match_count=excl_no_match,
                mismatch_histogram=histogram,
                min_mismatches=min_mm,
            )

            grid.excl_total[i] = excl_total
            grid.excl_no_match[i] = excl_no_match
            if skipped:
                grid.min_mismatches[i] = SKIPPED_SENTINEL
            elif min_mm is None:
                grid.min_mismatches[i] = NO_MIN_MM_SENTINEL
            else:
                grid.min_mismatches[i] = min_mm

        else:
            grid.excl_total[i] = -1
            grid.excl_no_match[i] = 0
            grid.min_mismatches[i] = (
                SKIPPED_SENTINEL if skipped else NO_MIN_MM_SENTINEL
            )

        details.append(
            PositionDetail(
                position=position_idx,
                variants=variants_list,
                total_sequences=total_sequences,
                sequences_analyzed=int(analysis.get("sequences_analyzed", 0)),
                no_match_count=no_match_count,
                variants_for_threshold=int(analysis.get("variants_for_threshold", variants_needed)),
                coverage_at_threshold=float(analysis.get("coverage_at_threshold", 0.0)),
                skipped=skipped,
                skip_reason=analysis.get("skip_reason"),
                exclusivity=excl,
            )
        )

    return grid


def recompute_variants_for_threshold(grid: LengthGrid, threshold_pct: float) -> None:
    """Re-derive `variants_needed` / `coverage_at_threshold` for the
    given threshold and write the updated values back into the grid arrays
    and per-position details. O(total_variants_in_grid)."""
    for i, detail in enumerate(grid.details):
        if detail.skipped:
            continue
        cumulative = 0.0
        needed = len(detail.variants)
        coverage = 0.0
        for j, v in enumerate(detail.variants):
            cumulative += v.percentage
            if cumulative >= threshold_pct:
                needed = j + 1
                coverage = cumulative
                break
        if cumulative < threshold_pct:
            coverage = cumulative
        detail.variants_for_threshold = needed
        detail.coverage_at_threshold = coverage
        grid.variants_needed[i] = needed


__all__ = [
    "LoadCancelled",
    "load_results",
    "recompute_variants_for_threshold",
]
