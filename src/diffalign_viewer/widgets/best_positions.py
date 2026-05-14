"""Slim, movable dialog that ranks the best oligo positions across all
lengths. In non-differential mode the score is `variants_needed` ascending;
in differential mode it is `variants_needed` ascending then off-target
`min_mismatches` descending. The user can cycle through hits and jump to
the corresponding template position in the heatmap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import (
    NO_MIN_MM_SENTINEL,
    SKIPPED_SENTINEL,
    LengthGrid,
    PositionDetail,
    ScreeningResults,
    effective_min_mismatches,
)


# Used as the "off-target mismatches" score when there is effectively
# infinite discrimination: nothing in the off-target set aligns, or every
# aligned off-target falls within the ignore-count threshold.
_INF_MM = 10**9


MODE_FEWEST_VARIANTS = "fewest_variants"
MODE_TOP_VARIANT_COVERAGE = "top_variant_coverage"


@dataclass(slots=True)
class _Hit:
    grid_index: int
    col: int
    position: int  # 0-indexed template position
    oligo_length: int
    variants: int
    mm_score: int  # higher = better discrimination (only meaningful in diff mode)
    mm_display: str  # human-readable mismatch text for the list
    top_pct: float  # percentage of the most-abundant variant at this position


class BestPositionsDialog(QDialog):
    """Non-modal dialog. Emits `positionSelected(detail, length)` when the
    user activates a hit either by list-click or with the prev/next cycle."""

    positionSelected = Signal(object, int)  # (PositionDetail, oligo_length)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Best positions")
        self.setModal(False)
        # Keep visible above main window without being always-on-top so
        # the user can move it around freely.
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Tool)
        self.resize(280, 360)

        self._results: ScreeningResults | None = None
        self._differential = False
        self._diff_ignore_count = 0
        self._hits: list[_Hit] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(QLabel("Show top:"))
        self._n_spin = QSpinBox()
        self._n_spin.setRange(1, 1000)
        self._n_spin.setValue(10)
        self._n_spin.setKeyboardTracking(False)
        self._n_spin.valueChanged.connect(lambda *_: self.refresh())
        top_row.addWidget(self._n_spin)
        top_row.addStretch(1)
        outer.addLayout(top_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("Rank by:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Fewest variants", MODE_FEWEST_VARIANTS)
        self._mode_combo.addItem("Highest variant-1 coverage", MODE_TOP_VARIANT_COVERAGE)
        self._mode_combo.currentIndexChanged.connect(lambda *_: self.refresh())
        mode_row.addWidget(self._mode_combo, 1)
        outer.addLayout(mode_row)

        self._mode_label = QLabel("")
        self._mode_label.setStyleSheet("color: #a0a0b8; font-size: 10px;")
        outer.addWidget(self._mode_label)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #1a1a26; color: #e0e0e8; "
            "border: 1px solid #3a3a52; }"
        )
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(self._on_item_activated)
        self._list.itemDoubleClicked.connect(self._on_item_activated)
        self._list.currentRowChanged.connect(self._on_row_changed)
        outer.addWidget(self._list, 1)

        cycle_row = QHBoxLayout()
        cycle_row.setSpacing(6)
        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.clicked.connect(self._prev)
        self._next_btn = QPushButton("Next ▶")
        self._next_btn.clicked.connect(self._next)
        self._counter = QLabel("0 / 0")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setMinimumWidth(60)
        cycle_row.addWidget(self._prev_btn)
        cycle_row.addWidget(self._counter, 1)
        cycle_row.addWidget(self._next_btn)
        outer.addLayout(cycle_row)

    # ────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────

    def set_results(self, results: ScreeningResults | None) -> None:
        self._results = results
        if self.isVisible():
            self.refresh()

    def set_view_state(self, differential: bool, diff_ignore_count: int) -> None:
        self._differential = differential
        self._diff_ignore_count = diff_ignore_count
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self._hits = self._compute_hits(self._n_spin.value())
        self._populate_list()

    # ────────────────────────────────────────────────────────
    # Ranking
    # ────────────────────────────────────────────────────────

    def _compute_hits(self, n: int) -> list[_Hit]:
        if self._results is None or not self._results.grids:
            return []

        mode = self._mode_combo.currentData()
        candidates: list[_Hit] = []
        for gi, grid in enumerate(self._results.grids):
            valid = (~grid.skipped) & (grid.variants_needed > 0)
            if not valid.any():
                continue
            cols = np.flatnonzero(valid)
            v = grid.variants_needed[cols]

            if self._differential:
                # Match the heatmap: resolve off-target mismatches after
                # discarding the `diff_ignore_count` lowest-mismatch
                # off-targets. Positions with no surviving off-target signal
                # count as infinitely discriminating.
                eff_mm, has_signal = effective_min_mismatches(
                    grid.excl_mm_levels[cols],
                    grid.excl_mm_cumcount[cols],
                    self._diff_ignore_count,
                )
                mm_score = eff_mm.astype(np.int64).copy()
                mm_score[~has_signal] = _INF_MM
            else:
                mm_score = np.zeros(cols.shape[0], dtype=np.int64)

            for k, col in enumerate(cols):
                col_int = int(col)
                pos = int(grid.positions[col_int])
                detail = grid.details[col_int] if col_int < len(grid.details) else None
                top_pct = (
                    detail.variants[0].percentage
                    if detail is not None and detail.variants
                    else 0.0
                )
                candidates.append(
                    _Hit(
                        grid_index=gi,
                        col=col_int,
                        position=pos,
                        oligo_length=grid.oligo_length,
                        variants=int(v[k]),
                        mm_score=int(mm_score[k]),
                        mm_display=(
                            self._format_mm(
                                grid, col_int, int(eff_mm[k]), bool(has_signal[k])
                            )
                            if self._differential
                            else ""
                        ),
                        top_pct=float(top_pct),
                    )
                )

        if mode == MODE_TOP_VARIANT_COVERAGE:
            # variant-1 coverage desc; ties broken by mm desc (when differential)
            # then by fewer variants, then longer oligo.
            if self._differential:
                candidates.sort(
                    key=lambda h: (-h.top_pct, -h.mm_score, h.variants, -h.oligo_length, h.position)
                )
            else:
                candidates.sort(
                    key=lambda h: (-h.top_pct, h.variants, -h.oligo_length, h.position)
                )
        else:
            if self._differential:
                # variants asc, mm desc, length desc (prefer longer oligo at ties)
                candidates.sort(
                    key=lambda h: (h.variants, -h.mm_score, -h.oligo_length, h.position)
                )
            else:
                candidates.sort(key=lambda h: (h.variants, -h.oligo_length, h.position))

        return candidates[:n]

    @staticmethod
    def _format_mm(grid: LengthGrid, col: int, eff_mm: int, has_signal: bool) -> str:
        if has_signal:
            return f"{eff_mm} mm"
        raw = int(grid.min_mismatches[col])
        if raw == NO_MIN_MM_SENTINEL:
            return "all no-match"
        if raw == SKIPPED_SENTINEL:
            return "—"
        # A real off-target minimum existed, but every aligned off-target
        # fell within the ignore-count threshold.
        return "ignored"

    # ────────────────────────────────────────────────────────
    # List + cycling
    # ────────────────────────────────────────────────────────

    def _populate_list(self) -> None:
        mode = self._mode_combo.currentData()
        self._list.blockSignals(True)
        self._list.clear()
        for i, h in enumerate(self._hits, start=1):
            parts = [f"#{i}", f"L:{h.oligo_length}", f"pos {h.position + 1}"]
            if mode == MODE_TOP_VARIANT_COVERAGE:
                parts.append(f"v1:{h.top_pct:.1f}%")
                parts.append(f"v:{h.variants}")
            else:
                parts.append(f"v:{h.variants}")
            if self._differential:
                parts.append(f"({h.mm_display})")
            item = QListWidgetItem("  ".join(parts))
            item.setData(Qt.ItemDataRole.UserRole, i - 1)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if mode == MODE_TOP_VARIANT_COVERAGE:
            label = "Variant-1 coverage ↑" + (", mm ↑" if self._differential else "")
        else:
            label = "Variants ↓" + (", mm ↑" if self._differential else "")
        self._mode_label.setText(label)

        if self._hits:
            self._list.setCurrentRow(0)
        else:
            self._counter.setText("0 / 0")
        self._update_buttons()

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._hits):
            self._counter.setText("0 / 0")
            self._update_buttons()
            return
        self._counter.setText(f"{row + 1} / {len(self._hits)}")
        self._update_buttons()
        self._emit_selection(self._hits[row])

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self._hits):
            self._emit_selection(self._hits[idx])

    def _emit_selection(self, hit: _Hit) -> None:
        if self._results is None:
            return
        grid = self._results.grids[hit.grid_index]
        if hit.col >= len(grid.details):
            return
        self.positionSelected.emit(grid.details[hit.col], grid.oligo_length)

    def _prev(self) -> None:
        if not self._hits:
            return
        row = (self._list.currentRow() - 1) % len(self._hits)
        self._list.setCurrentRow(row)

    def _next(self) -> None:
        if not self._hits:
            return
        row = (self._list.currentRow() + 1) % len(self._hits)
        self._list.setCurrentRow(row)

    def _update_buttons(self) -> None:
        enabled = bool(self._hits)
        self._prev_btn.setEnabled(enabled)
        self._next_btn.setEnabled(enabled)
