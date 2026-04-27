"""Compact data model for parsed diffalign result files.

Memory budget: only the heatmap-summary fields are stored as numpy arrays;
variants and exclusivity histograms are kept per-position in lightweight
slot-classes so multi-GB JSON inputs don't blow up RAM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

NO_MATCH_SENTINEL: int = 4_294_967_295  # u32::MAX, "no alignment found"
SKIPPED_SENTINEL: int = -1
NO_MIN_MM_SENTINEL: int = -2  # min_mismatches was null (best case)


@dataclass(slots=True)
class PairwiseParams:
    match_score: int = 2
    mismatch_score: int = -1
    gap_open_penalty: int = -2
    gap_extend_penalty: int = -1
    max_mismatches: int = 8


@dataclass(slots=True)
class AnalysisMethod:
    kind: str  # "NoAmbiguities" | "FixedAmbiguities" | "Incremental"
    fixed_ambiguities: int | None = None
    incremental_pct: int | None = None
    incremental_max_amb: int | None = None

    def description(self) -> str:
        if self.kind == "NoAmbiguities":
            return "No ambiguities (exact variants only)"
        if self.kind == "FixedAmbiguities":
            return f"Fixed ambiguities (max {self.fixed_ambiguities} per variant)"
        if self.kind == "Incremental":
            cap = self.incremental_max_amb
            cap_str = f", max {cap}" if cap is not None else ""
            return f"Incremental ({self.incremental_pct}% per step{cap_str})"
        return self.kind

    @classmethod
    def from_json(cls, value: Any) -> "AnalysisMethod":
        # NoAmbiguities can be either the string "NoAmbiguities" or { "NoAmbiguities": null }
        if isinstance(value, str):
            return cls(kind=value)
        if isinstance(value, dict):
            if "FixedAmbiguities" in value:
                return cls(kind="FixedAmbiguities", fixed_ambiguities=int(value["FixedAmbiguities"]))
            if "Incremental" in value:
                payload = value["Incremental"]
                pct, cap = (payload[0], payload[1]) if isinstance(payload, list) else (payload, None)
                return cls(
                    kind="Incremental",
                    incremental_pct=int(pct),
                    incremental_max_amb=int(cap) if cap is not None else None,
                )
            if "NoAmbiguities" in value:
                return cls(kind="NoAmbiguities")
        return cls(kind=str(value))


@dataclass(slots=True)
class ThreadCount:
    kind: str  # "Auto" | "Fixed"
    fixed: int | None = None

    def description(self) -> str:
        if self.kind == "Auto":
            return "Auto"
        return f"{self.fixed}"

    @classmethod
    def from_json(cls, value: Any) -> "ThreadCount":
        if isinstance(value, str):
            return cls(kind=value)
        if isinstance(value, dict) and "Fixed" in value:
            return cls(kind="Fixed", fixed=int(value["Fixed"]))
        return cls(kind="Auto")


@dataclass(slots=True)
class AnalysisParams:
    method: AnalysisMethod = field(default_factory=lambda: AnalysisMethod(kind="NoAmbiguities"))
    pairwise: PairwiseParams = field(default_factory=PairwiseParams)
    exclude_n: bool = True
    min_oligo_length: int = 18
    max_oligo_length: int = 25
    resolution: int = 1
    coverage_threshold: float = 90.0
    thread_count: ThreadCount = field(default_factory=lambda: ThreadCount(kind="Auto"))
    length_skip: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AnalysisParams":
        pw = data.get("pairwise", {})
        return cls(
            method=AnalysisMethod.from_json(data.get("method", "NoAmbiguities")),
            pairwise=PairwiseParams(
                match_score=int(pw.get("match_score", 2)),
                mismatch_score=int(pw.get("mismatch_score", -1)),
                gap_open_penalty=int(pw.get("gap_open_penalty", -2)),
                gap_extend_penalty=int(pw.get("gap_extend_penalty", -1)),
                max_mismatches=int(pw.get("max_mismatches", 8)),
            ),
            exclude_n=bool(data.get("exclude_n", True)),
            min_oligo_length=int(data.get("min_oligo_length", 18)),
            max_oligo_length=int(data.get("max_oligo_length", 25)),
            resolution=int(data.get("resolution", 1)),
            coverage_threshold=float(data.get("coverage_threshold", 90.0)),
            thread_count=ThreadCount.from_json(data.get("thread_count", "Auto")),
            length_skip=int(data.get("length_skip", 0) or 0),
        )


@dataclass(slots=True)
class Variant:
    sequence: str
    count: int
    percentage: float


@dataclass(slots=True)
class MismatchBucket:
    mismatches: int
    count: int
    example_name: str

    @property
    def is_no_match(self) -> bool:
        return self.mismatches == NO_MATCH_SENTINEL


@dataclass(slots=True)
class ExclusivityResult:
    total_sequences: int
    no_match_count: int
    mismatch_histogram: list[MismatchBucket]
    min_mismatches: int | None  # None = all no-match (best case)


@dataclass(slots=True)
class PositionDetail:
    """Full per-position payload, kept in memory because a single position's
    detail is small. Only loaded when the user clicks a cell or for variant
    recomputation."""

    position: int
    variants: list[Variant]
    total_sequences: int
    sequences_analyzed: int
    no_match_count: int
    variants_for_threshold: int
    coverage_at_threshold: float
    skipped: bool
    skip_reason: str | None
    exclusivity: ExclusivityResult | None


@dataclass(slots=True)
class Annotation:
    name: str
    start: int  # 0-indexed inclusive
    end: int  # 0-indexed exclusive
    direction: str  # "sense" | "antisense"


class LengthGrid:
    """Per-length compact summary used for heatmap rendering.

    All position arrays are aligned (same length, same indexing). The full
    `PositionDetail` for column `i` is at `details[i]`.
    """

    __slots__ = (
        "oligo_length",
        "positions",  # int32 array — 0-indexed positions on the template
        "variants_needed",  # int32 array
        "no_match_count",  # int32 array
        "total_sequences",  # int32 array
        "skipped",  # bool array
        "min_mismatches",  # int32 array, sentinels: NO_MATCH_SENTINEL→u32::MAX, NO_MIN_MM_SENTINEL→null, SKIPPED_SENTINEL→skipped
        "excl_total",  # int32 array — exclusivity total_sequences (-1 if no exclusivity)
        "excl_no_match",  # int32 array — exclusivity no_match_count
        "details",  # list[PositionDetail] aligned with the arrays
    )

    def __init__(self, oligo_length: int, n: int) -> None:
        self.oligo_length = oligo_length
        self.positions = np.zeros(n, dtype=np.int32)
        self.variants_needed = np.zeros(n, dtype=np.int32)
        self.no_match_count = np.zeros(n, dtype=np.int32)
        self.total_sequences = np.zeros(n, dtype=np.int32)
        self.skipped = np.zeros(n, dtype=bool)
        self.min_mismatches = np.full(n, NO_MIN_MM_SENTINEL, dtype=np.int32)
        self.excl_total = np.full(n, -1, dtype=np.int32)
        self.excl_no_match = np.zeros(n, dtype=np.int32)
        self.details: list[PositionDetail] = []


@dataclass
class ScreeningResults:
    params: AnalysisParams
    template_length: int
    total_sequences: int
    template_sequence: str
    differential_enabled: bool
    exclusivity_sequence_count: int | None
    annotations: list[Annotation]
    # ascending-sorted list of (oligo_length, LengthGrid)
    grids: list[LengthGrid]

    @property
    def lengths(self) -> list[int]:
        return [g.oligo_length for g in self.grids]
