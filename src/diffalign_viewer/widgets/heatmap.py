"""Heatmap widget — viewport-based rendering for very large templates.

Design notes:

* The widget is a `QAbstractScrollArea` so we get free scrollbars without
  having to allocate a giant pixmap. We only ever paint the visible
  columns × rows.
* Cell colors are computed in vectorized numpy via
  `colors.colorize_grid_*_rgba` and uploaded to a small per-row QImage
  that's blitted with `drawImage`. For 10k positions × 8 rows this is
  ~320 KB per repaint instead of the multi-MB canvas the old Tauri
  program built.
* Search-highlight overlays, annotation bars and the sequence ruler are
  drawn as cheap vector primitives during paint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QToolTip, QWidget

from ..colors import (
    base_color,
    colorize_grid_differential_rgba,
    colorize_grid_rgba,
)
from ..models import (
    Annotation,
    LengthGrid,
    PositionDetail,
    ScreeningResults,
)
from ..sequence import SearchMatch

ROW_LABEL_WIDTH = 64
HEADER_HEIGHT = 24
BASE_CELL_WIDTH = 14
CELL_HEIGHT = 22
POSITION_ROW_HEIGHT = 18
TEMPLATE_ROW_HEIGHT = 22
ANNOTATION_ROW_HEIGHT = 18
ANNOTATION_GAP = 2

ANNOTATION_PALETTE = [
    QColor("#5b8af0"),
    QColor("#e07040"),
    QColor("#50c070"),
    QColor("#c060c0"),
    QColor("#e0c040"),
    QColor("#40b0b0"),
]


@dataclass(slots=True)
class HeatmapView:
    """Mutable settings the heatmap reads on every repaint."""

    zoom_level: float = 1.0
    color_green_at: int = 1
    color_red_at: int = 10
    nomatch_ok_pct: float = 5.0
    nomatch_bad_pct: float = 50.0
    differential_mode: bool = False
    diff_green_at: int = 5
    diff_red_at: int = 0
    diff_ignore_count: int = 0


@dataclass(slots=True)
class _AnnLayout:
    annotation: Annotation
    col_start: int
    col_end: int
    row: int
    palette_idx: int


class HeatmapWidget(QAbstractScrollArea):
    """Large-data-friendly heatmap viewer."""

    cellClicked = Signal(object, int)  # (PositionDetail, oligo_length)
    cellHovered = Signal(object, int)  # (PositionDetail or None, length)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)

        self._results: ScreeningResults | None = None
        self._search_matches: list[SearchMatch] = []
        self._annotations: list[Annotation] = []
        self._ann_layout: list[_AnnLayout] = []
        self._ann_area_height = 0
        self.view = HeatmapView()

        # Cache the position→column lookup for the (uniform) first grid.
        self._n_positions = 0
        self._first_positions: np.ndarray | None = None  # int32 array of template positions

        # Remember last hovered cell so we don't spam tooltip updates.
        self._last_hover: tuple[int, int] | None = None

        # Background fill so the viewport doesn't show OS-default white during resize.
        pal = self.viewport().palette()
        pal.setColor(self.viewport().backgroundRole(), QColor("#1a1a26"))
        self.viewport().setPalette(pal)
        self.viewport().setAutoFillBackground(True)

        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)

    # ────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────

    def set_results(self, results: ScreeningResults | None) -> None:
        self._results = results
        if results is not None and results.grids:
            self._first_positions = results.grids[0].positions
            self._n_positions = self._first_positions.shape[0]
            self._annotations = list(results.annotations)
        else:
            self._first_positions = None
            self._n_positions = 0
            self._annotations = []
        self._search_matches = []
        self._ann_layout = []
        self._ann_area_height = 0
        self._rebuild_annotation_layout()
        self._update_scroll_ranges()
        self.viewport().update()

    def set_view(self, view: HeatmapView) -> None:
        self.view = view
        self._update_scroll_ranges()
        self.viewport().update()

    def set_search_matches(self, matches: list[SearchMatch]) -> None:
        self._search_matches = matches
        self.viewport().update()

    def set_annotations(self, annotations: list[Annotation]) -> None:
        self._annotations = list(annotations)
        self._rebuild_annotation_layout()
        self._update_scroll_ranges()
        self.viewport().update()

    def jump_to_position(self, position: int) -> None:
        if self._first_positions is None or self._n_positions == 0:
            return
        col = int(np.searchsorted(self._first_positions, position))
        col = max(0, min(self._n_positions - 1, col))
        cell_w = self._cell_width()
        x = ROW_LABEL_WIDTH + col * cell_w
        viewport_w = self.viewport().width()
        target = max(0, x - viewport_w // 3)
        self.horizontalScrollBar().setValue(target)

    # ────────────────────────────────────────────────────────
    # Geometry
    # ────────────────────────────────────────────────────────

    def _cell_width(self) -> int:
        return max(1, round(BASE_CELL_WIDTH * self.view.zoom_level))

    def _grid_top_y(self) -> int:
        return self._ann_area_height + HEADER_HEIGHT + POSITION_ROW_HEIGHT + TEMPLATE_ROW_HEIGHT

    def _virtual_size(self) -> QSize:
        if self._results is None or not self._results.grids:
            return QSize(0, 0)
        n_rows = len(self._results.grids)
        cell_w = self._cell_width()
        width = ROW_LABEL_WIDTH + self._n_positions * cell_w + 8
        height = self._grid_top_y() + n_rows * CELL_HEIGHT + 8
        return QSize(width, height)

    def _update_scroll_ranges(self) -> None:
        size = self._virtual_size()
        viewport = self.viewport().size()
        self.horizontalScrollBar().setPageStep(viewport.width())
        self.verticalScrollBar().setPageStep(viewport.height())
        self.horizontalScrollBar().setRange(0, max(0, size.width() - viewport.width()))
        self.verticalScrollBar().setRange(0, max(0, size.height() - viewport.height()))
        # Single-step ≈ one cell; lets keyboard arrows feel right.
        cell_w = self._cell_width()
        self.horizontalScrollBar().setSingleStep(cell_w)
        self.verticalScrollBar().setSingleStep(CELL_HEIGHT)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._update_scroll_ranges()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(400, 200)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(900, 360)

    # ────────────────────────────────────────────────────────
    # Annotations layout
    # ────────────────────────────────────────────────────────

    def _rebuild_annotation_layout(self) -> None:
        self._ann_layout = []
        self._ann_area_height = 0
        if self._first_positions is None or not self._annotations:
            return

        # Build a lookup from template-position → column index using the
        # first grid (all grids share the same `positions` resolution by
        # construction).
        positions = self._first_positions
        items: list[_AnnLayout] = []
        for idx, ann in enumerate(self._annotations):
            # cols whose template position is in [start, end)
            mask = (positions >= ann.start) & (positions < ann.end)
            if not mask.any():
                continue
            cols = np.flatnonzero(mask)
            items.append(
                _AnnLayout(
                    annotation=ann,
                    col_start=int(cols[0]),
                    col_end=int(cols[-1]),
                    row=0,
                    palette_idx=idx % len(ANNOTATION_PALETTE),
                )
            )

        # Greedy layout into rows so overlapping annotations stack.
        for item in items:
            row = 0
            while True:
                clash = any(
                    other is not item
                    and other.row == row
                    and other.col_start <= item.col_end
                    and other.col_end >= item.col_start
                    for other in items
                )
                if not clash:
                    break
                row += 1
            item.row = row

        self._ann_layout = items
        n_rows = (max((it.row for it in items), default=-1) + 1)
        self._ann_area_height = n_rows * (ANNOTATION_ROW_HEIGHT + ANNOTATION_GAP)

    # ────────────────────────────────────────────────────────
    # Painting
    # ────────────────────────────────────────────────────────

    def paintEvent(self, event):  # type: ignore[override]
        if self._results is None or not self._results.grids:
            painter = QPainter(self.viewport())
            painter.fillRect(self.viewport().rect(), QColor("#1a1a26"))
            painter.setPen(QColor("#6a6a82"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, "No results loaded"
            )
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.viewport().rect(), QColor("#1a1a26"))

        cell_w = self._cell_width()
        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        viewport_w = self.viewport().width()
        viewport_h = self.viewport().height()

        # Determine visible columns.
        col_start = max(0, (scroll_x - ROW_LABEL_WIDTH) // cell_w)
        col_end = min(
            self._n_positions - 1,
            (scroll_x + viewport_w - ROW_LABEL_WIDTH) // cell_w,
        )
        # Pad a little so we don't get tear-edges
        col_start = max(0, col_start - 1)
        col_end = min(self._n_positions - 1, col_end + 1)

        grid_top = self._grid_top_y()
        n_rows = len(self._results.grids)

        # ── Annotation bars ──────────────────────────────────
        if self._ann_layout:
            self._paint_annotations(painter, scroll_x, col_start, col_end, cell_w, viewport_w)

        # ── Position numbers ────────────────────────────────
        self._paint_position_ruler(painter, scroll_x, col_start, col_end, cell_w)

        # ── Template bases ──────────────────────────────────
        self._paint_template_row(painter, scroll_x, col_start, col_end, cell_w)

        # ── Search overlay on template row ──────────────────
        if self._search_matches:
            self._paint_search_overlay(painter, scroll_x, col_start, col_end, cell_w)

        # ── Heatmap rows ────────────────────────────────────
        for row_idx, grid in enumerate(self._results.grids):
            y = grid_top + row_idx * CELL_HEIGHT - scroll_y
            if y + CELL_HEIGHT < 0 or y > viewport_h:
                continue
            self._paint_grid_row(
                painter, grid, row_idx, y, scroll_x, col_start, col_end, cell_w
            )

        # ── Row label gutter (cover any pixel-bleed from cells) ─
        gutter_rect = QRect(0, 0, ROW_LABEL_WIDTH - 2, viewport_h)
        painter.fillRect(gutter_rect, QColor("#1a1a26"))
        # Top corner block
        corner_rect = QRect(0, 0, viewport_w, grid_top - scroll_y)
        if corner_rect.height() > 0 and corner_rect.bottom() > 0:
            # only fill the gutter part
            painter.fillRect(QRect(0, 0, ROW_LABEL_WIDTH - 2, max(0, grid_top - scroll_y)), QColor("#1a1a26"))

        # Row labels (draw on top of the gutter)
        painter.setPen(QColor("#cfcfe0"))
        painter.setFont(QFont("Cascadia Mono", 9))
        fm = QFontMetrics(painter.font())
        for row_idx, grid in enumerate(self._results.grids):
            y = grid_top + row_idx * CELL_HEIGHT - scroll_y
            if y + CELL_HEIGHT < 0 or y > viewport_h:
                continue
            text = f"{grid.oligo_length} bp"
            tw = fm.horizontalAdvance(text)
            painter.drawText(
                ROW_LABEL_WIDTH - tw - 6, y + (CELL_HEIGHT + fm.ascent()) // 2 - 1, text
            )

    def _paint_annotations(
        self,
        painter: QPainter,
        scroll_x: int,
        col_start: int,
        col_end: int,
        cell_w: int,
        viewport_w: int,
    ) -> None:
        scroll_y = self.verticalScrollBar().value()
        for item in self._ann_layout:
            if item.col_end < col_start or item.col_start > col_end:
                continue
            color = ANNOTATION_PALETTE[item.palette_idx]
            y = item.row * (ANNOTATION_ROW_HEIGHT + ANNOTATION_GAP) - scroll_y
            x1 = ROW_LABEL_WIDTH + item.col_start * cell_w - scroll_x
            x2 = ROW_LABEL_WIDTH + (item.col_end + 1) * cell_w - 1 - scroll_x
            w = max(1, x2 - x1)

            fill = QColor(color)
            fill.setAlpha(80)
            painter.fillRect(x1, y, w, ANNOTATION_ROW_HEIGHT, fill)
            painter.setPen(QPen(color, 1))
            painter.drawRect(x1, y, w - 1, ANNOTATION_ROW_HEIGHT - 1)

            arrow = "→" if item.annotation.direction == "sense" else "←"
            label = f"{arrow} {item.annotation.name}"
            painter.setPen(color)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.save()
            painter.setClipRect(x1, y, w, ANNOTATION_ROW_HEIGHT)
            painter.drawText(x1 + 4, y + ANNOTATION_ROW_HEIGHT - 5, label)
            painter.restore()

    def _paint_position_ruler(
        self,
        painter: QPainter,
        scroll_x: int,
        col_start: int,
        col_end: int,
        cell_w: int,
    ) -> None:
        y = self._ann_area_height + HEADER_HEIGHT - self.verticalScrollBar().value()
        if y + POSITION_ROW_HEIGHT < 0:
            return
        painter.setPen(QColor("#a0a0b8"))
        painter.setFont(QFont("Cascadia Mono", 8))
        # Draw position numbers at every cell when zoomed in enough,
        # otherwise every 5 or every 10.
        if cell_w >= 32:
            stride = 1
        elif cell_w >= 18:
            stride = 5
        else:
            stride = 10
        positions = self._first_positions
        if positions is None:
            return
        for col in range(col_start, col_end + 1):
            pos_val = int(positions[col])
            if pos_val % stride != 0 and col != 0:
                continue
            x = ROW_LABEL_WIDTH + col * cell_w + cell_w // 2 - scroll_x
            painter.drawText(
                QRect(x - 30, y, 60, POSITION_ROW_HEIGHT),
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                str(pos_val + 1),
            )

    def _paint_template_row(
        self,
        painter: QPainter,
        scroll_x: int,
        col_start: int,
        col_end: int,
        cell_w: int,
    ) -> None:
        if self._results is None:
            return
        y = (
            self._ann_area_height
            + HEADER_HEIGHT
            + POSITION_ROW_HEIGHT
            - self.verticalScrollBar().value()
        )
        if y + TEMPLATE_ROW_HEIGHT < 0:
            return
        seq = self._results.template_sequence
        positions = self._first_positions
        if positions is None or not seq:
            return

        font_size = max(7, min(11, cell_w - 2))
        painter.setFont(QFont("Cascadia Mono", font_size, QFont.Weight.Bold))
        for col in range(col_start, col_end + 1):
            pos_val = int(positions[col])
            if pos_val < 0 or pos_val >= len(seq):
                continue
            base = seq[pos_val]
            r, g, b = base_color(base)
            painter.setPen(QColor(r, g, b))
            x = ROW_LABEL_WIDTH + col * cell_w - scroll_x
            painter.drawText(
                QRect(x, y, cell_w, TEMPLATE_ROW_HEIGHT),
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                base,
            )

    def _paint_search_overlay(
        self,
        painter: QPainter,
        scroll_x: int,
        col_start: int,
        col_end: int,
        cell_w: int,
    ) -> None:
        positions = self._first_positions
        if positions is None:
            return

        first_pos = int(positions[col_start])
        last_pos = int(positions[col_end])

        y = (
            self._ann_area_height
            + HEADER_HEIGHT
            + POSITION_ROW_HEIGHT
            - self.verticalScrollBar().value()
        )
        highlight = QColor(224, 160, 64, 120)
        for match in self._search_matches:
            if match.end <= first_pos or match.start > last_pos:
                continue
            # Map [match.start, match.end) → columns in the heatmap. Because
            # the position grid is uniform with stride `params.resolution`,
            # we can find the column of any template position with searchsorted.
            lo = int(np.searchsorted(positions, match.start))
            hi = int(np.searchsorted(positions, match.end - 1, side="right"))
            if hi <= lo:
                continue
            x1 = ROW_LABEL_WIDTH + lo * cell_w - scroll_x
            x2 = ROW_LABEL_WIDTH + hi * cell_w - scroll_x
            painter.fillRect(x1, y, max(1, x2 - x1), TEMPLATE_ROW_HEIGHT, highlight)

    def _paint_grid_row(
        self,
        painter: QPainter,
        grid: LengthGrid,
        row_idx: int,
        y: int,
        scroll_x: int,
        col_start: int,
        col_end: int,
        cell_w: int,
    ) -> None:
        if col_end < col_start:
            return

        # Slice grid arrays for visible columns.
        s = slice(col_start, col_end + 1)
        if self.view.differential_mode:
            rgba = colorize_grid_differential_rgba(
                grid.variants_needed[s],
                grid.no_match_count[s],
                grid.total_sequences[s],
                grid.skipped[s],
                grid.min_mismatches[s],
                grid.excl_total[s],
                grid.excl_no_match[s],
                self.view.diff_green_at,
                self.view.diff_red_at,
                self.view.color_green_at,
                self.view.color_red_at,
                self.view.nomatch_ok_pct,
                self.view.nomatch_bad_pct,
                self.view.diff_ignore_count,
            )
        else:
            rgba = colorize_grid_rgba(
                grid.variants_needed[s],
                grid.no_match_count[s],
                grid.total_sequences[s],
                grid.skipped[s],
                self.view.color_green_at,
                self.view.color_red_at,
                self.view.nomatch_ok_pct,
                self.view.nomatch_bad_pct,
            )

        # Paint each cell as a filled rect (cheap enough for visible-column counts).
        x0 = ROW_LABEL_WIDTH + col_start * cell_w - scroll_x
        gap = 1 if cell_w >= 6 else 0
        cell_height = CELL_HEIGHT - 1
        for i in range(rgba.shape[0]):
            r, g, b, _a = rgba[i]
            painter.fillRect(
                x0 + i * cell_w,
                y,
                cell_w - gap,
                cell_height,
                QColor(int(r), int(g), int(b)),
            )

        # Variant count labels (when cells are wide enough).
        if cell_w >= 16:
            painter.setPen(QColor("#fafafa"))
            painter.setFont(QFont("Cascadia Mono", min(9, cell_w - 4)))
            variants_needed = grid.variants_needed[s]
            skipped = grid.skipped[s]
            for i in range(variants_needed.shape[0]):
                count = int(variants_needed[i])
                if count <= 0 or skipped[i]:
                    continue
                painter.drawText(
                    QRect(x0 + i * cell_w, y, cell_w - gap, cell_height),
                    Qt.AlignmentFlag.AlignCenter,
                    str(count),
                )

    # ────────────────────────────────────────────────────────
    # Mouse interaction
    # ────────────────────────────────────────────────────────

    def _hit_test(self, pos: QPoint) -> tuple[int, int] | None:
        if self._results is None or not self._results.grids:
            return None
        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        cell_w = self._cell_width()

        x = pos.x() + scroll_x
        y = pos.y() + scroll_y
        if x < ROW_LABEL_WIDTH:
            return None
        col = (x - ROW_LABEL_WIDTH) // cell_w
        row = (y - self._grid_top_y()) // CELL_HEIGHT
        if not (0 <= col < self._n_positions):
            return None
        if not (0 <= row < len(self._results.grids)):
            return None
        return int(col), int(row)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        hit = self._hit_test(event.position().toPoint())
        if hit is None:
            QToolTip.hideText()
            self._last_hover = None
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.cellHovered.emit(None, 0)
            return

        col, row = hit
        if self._results is None:
            return
        grid = self._results.grids[row]
        if col >= len(grid.details):
            return
        detail = grid.details[col]
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        if self._last_hover != hit:
            self._last_hover = hit
            tooltip = self._format_tooltip(detail, grid.oligo_length)
            QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)
            self.cellHovered.emit(detail, grid.oligo_length)

    def leaveEvent(self, event):  # type: ignore[override]
        QToolTip.hideText()
        self._last_hover = None
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.cellHovered.emit(None, 0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        hit = self._hit_test(event.position().toPoint())
        if hit is None:
            return
        col, row = hit
        if self._results is None:
            return
        grid = self._results.grids[row]
        if col >= len(grid.details):
            return
        self.cellClicked.emit(grid.details[col], grid.oligo_length)

    def wheelEvent(self, event: QWheelEvent):  # type: ignore[override]
        # Hold Ctrl: zoom. Hold Shift or no modifier with horizontal delta:
        # horizontal scroll. Plain wheel: vertical scroll (default).
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            factor = 1.1 if delta > 0 else 1 / 1.1
            new_zoom = max(0.3, min(4.0, self.view.zoom_level * factor))
            self.view.zoom_level = new_zoom
            self._update_scroll_ranges()
            self.viewport().update()
            event.accept()
            return

        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier or abs(delta_x) > abs(delta_y):
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - (delta_x or delta_y))
            event.accept()
            return
        super().wheelEvent(event)

    @staticmethod
    def _format_tooltip(detail: PositionDetail, length: int) -> str:
        if detail.skipped:
            reason = detail.skip_reason or "skipped"
            return f"Pos {detail.position + 1}, {length} bp\nSkipped: {reason}"
        nm_pct = (
            (detail.no_match_count / detail.total_sequences) * 100.0
            if detail.total_sequences
            else 0.0
        )
        lines = [
            f"Pos {detail.position + 1}, {length} bp",
            f"{detail.variants_for_threshold} variants needed for {detail.coverage_at_threshold:.1f}%",
            f"{detail.no_match_count}/{detail.total_sequences} no-match ({nm_pct:.1f}%)",
        ]
        if detail.exclusivity is not None:
            mm = detail.exclusivity.min_mismatches
            mm_text = "all no-match" if mm is None else str(mm)
            lines.append(f"Min exclusivity MM: {mm_text}")
        return "\n".join(lines)
