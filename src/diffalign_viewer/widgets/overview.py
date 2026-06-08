"""Overview window — a whole-template bird's-eye of the heatmap.

The template is almost always far wider than the screen, so the overview
compresses the entire position axis into the available pixel width. Each
pixel column stands for a *bucket* of template positions; rather than
averaging the bucket (which would wash good spots out into the surrounding
mediocrity) we pick the single **best-fitting** position in the bucket and
colour the column with it. That way a lone good oligo position in an
otherwise poor region still lights up green, so the user can spot the
good stretches at a glance.

A translucent rectangle marks the slice currently shown in the main
heatmap. Dragging (or clicking) it scrolls the heatmap to match, and the
heatmap scrolling back updates the rectangle.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from ..colors import (
    NO_DATA,
    colorize_grid_differential_rgba,
    colorize_grid_rgba,
)
from ..models import ScreeningResults, effective_min_mismatches
from .heatmap import HeatmapView

OV_LEFT_GUTTER = 52
OV_RIGHT_MARGIN = 8
OV_TOP_RULER = 18
OV_BOTTOM_MARGIN = 6
OV_ROW_GAP = 1

# "best position in this bucket" is undefined when nothing in the bucket is
# usable; such columns get the no-data colour.
_INF = np.inf


# ── shared bird's-eye rendering ──────────────────────────────
# These module-level helpers build the compressed (n_rows × n_cols) colour
# buffer that the overview paints. They are shared with the image exporter so
# the exported picture is coloured identically to the on-screen overview.


def _rank_array(grid, view: HeatmapView) -> np.ndarray:
    """Lower is better. ``+inf`` for positions that can't host an oligo
    (skipped, or no variant data)."""
    active = (~grid.skipped) & (grid.variants_needed > 0)
    variants = grid.variants_needed.astype(np.float64)
    if view.differential_mode:
        eff_mm, has_signal = effective_min_mismatches(
            grid.excl_mm_levels,
            grid.excl_mm_cumcount,
            view.diff_ignore_count,
        )
        mm = eff_mm.astype(np.float64)
        # No surviving off-target signal == maximally discriminating.
        mm[~has_signal] = 1e9
        # Higher mm is better, then fewer variants. Encode both so smaller
        # ranks are the better positions.
        rank = -mm * 1e6 + variants
    else:
        nm = np.where(
            grid.total_sequences > 0,
            grid.no_match_count / np.maximum(grid.total_sequences, 1),
            0.0,
        )
        # Fewer variants first, less no-match as a tie-breaker.
        rank = variants + nm * 1e-3
    rank = np.where(active, rank, _INF)
    return rank


def _segment_best(rank: np.ndarray, edges: np.ndarray, n_cols: int) -> np.ndarray:
    """Global index of the lowest-rank position in each bucket."""
    best = np.empty(n_cols, dtype=np.int64)
    last = rank.shape[0] - 1
    for c in range(n_cols):
        lo = int(edges[c])
        hi = int(edges[c + 1])
        if hi <= lo:
            # Defensive: an empty bucket reuses the previous position so we
            # never call argmin on an empty slice.
            best[c] = min(lo, last)
            continue
        seg = rank[lo:hi]
        best[c] = lo + int(np.argmin(seg))
    return best


def _colorize_subset(grid, idx: np.ndarray, view: HeatmapView) -> np.ndarray:
    vn = grid.variants_needed[idx]
    nm = grid.no_match_count[idx]
    ts = grid.total_sequences[idx]
    sk = grid.skipped[idx]
    if view.differential_mode:
        return colorize_grid_differential_rgba(
            vn, nm, ts, sk,
            grid.excl_mm_levels[idx],
            grid.excl_mm_cumcount[idx],
            view.diff_green_at,
            view.diff_red_at,
            view.color_green_at,
            view.color_red_at,
            view.nomatch_ok_pct,
            view.nomatch_bad_pct,
            view.diff_ignore_count,
        )
    return colorize_grid_rgba(
        vn, nm, ts, sk,
        view.color_green_at,
        view.color_red_at,
        view.nomatch_ok_pct,
        view.nomatch_bad_pct,
    )


def build_overview_buffer(grids, view: HeatmapView, n_cols: int) -> np.ndarray:
    """Compress every grid's position axis into ``n_cols`` buckets, colouring
    each bucket with its single best-fitting position. Returns an
    ``(len(grids), n_cols, 4)`` uint8 RGBA buffer."""
    buf = np.empty((len(grids), n_cols, 4), dtype=np.uint8)
    for ri, grid in enumerate(grids):
        grid_n = int(grid.variants_needed.shape[0])
        if grid_n == 0:
            buf[ri, :] = (NO_DATA[0], NO_DATA[1], NO_DATA[2], 255)
            continue
        # Each grid may have a different number of positions (longer oligos
        # have fewer valid start sites), so bucket each over its own length.
        edges = np.linspace(0, grid_n, n_cols + 1).astype(np.int64)
        rank = _rank_array(grid, view)
        best = _segment_best(rank, edges, n_cols)
        buf[ri] = _colorize_subset(grid, best, view)
    return buf


class OverviewPanel(QWidget):
    """The painted bird's-eye widget. Lives inside :class:`OverviewWindow`."""

    # Emitted while the user drags/clicks the viewport rectangle. Carries the
    # template *column index* that should become the left edge of the heatmap.
    viewportDragged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 120)
        self.setMouseTracking(True)

        self._results: ScreeningResults | None = None
        self._view = HeatmapView()
        # Position axis for the slice rectangle / ruler — taken from the first
        # grid, exactly like the heatmap.
        self._n_positions = 0
        # Shortest grid's position count. Longer oligos have fewer valid start
        # positions, so this bounds how many buckets we can safely cut without
        # producing empty ones in the shortest grid.
        self._min_positions = 0
        self._first_positions: np.ndarray | None = None

        # Visible-slice rectangle, in template column indices.
        self._vis_start = 0
        self._vis_end = 0

        # Rendered colour cache: (n_rows, n_cols, 4) uint8, plus the n_cols it
        # was built for. Invalidated on results/view/size change.
        self._buf: np.ndarray | None = None
        self._cache_cols = -1

        self._dragging = False
        self._grab_dx = 0.0

        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("#14141e"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    # ── public API ──────────────────────────────────────────

    def set_results(self, results: ScreeningResults | None) -> None:
        self._results = results
        if results is not None and results.grids:
            self._first_positions = results.grids[0].positions
            self._n_positions = int(self._first_positions.shape[0])
            self._min_positions = min(
                int(g.positions.shape[0]) for g in results.grids
            )
        else:
            self._first_positions = None
            self._n_positions = 0
            self._min_positions = 0
        self._invalidate()
        self.update()

    def set_view(self, view: HeatmapView) -> None:
        self._view = view
        self._invalidate()
        self.update()

    def refresh(self) -> None:
        """Force a re-render (e.g. after the coverage threshold changed the
        underlying ``variants_needed`` arrays in place)."""
        self._invalidate()
        self.update()

    def set_visible_range(self, col_start: int, col_end: int) -> None:
        self._vis_start = int(col_start)
        self._vis_end = int(col_end)
        self.update()

    # ── geometry helpers ────────────────────────────────────

    def _content_rect(self) -> QRect:
        w = max(0, self.width() - OV_LEFT_GUTTER - OV_RIGHT_MARGIN)
        h = max(0, self.height() - OV_TOP_RULER - OV_BOTTOM_MARGIN)
        return QRect(OV_LEFT_GUTTER, OV_TOP_RULER, w, h)

    def _n_cols(self, content_w: int) -> int:
        if self._min_positions == 0 or content_w <= 0:
            return 0
        # Bound by the shortest grid so per-grid bucket edges never collapse.
        return min(content_w, self._min_positions)

    def _col_to_x(self, col: float, content: QRect) -> float:
        if self._n_positions == 0:
            return content.left()
        return content.left() + col / self._n_positions * content.width()

    def _x_to_col(self, x: float, content: QRect) -> int:
        if self._n_positions == 0 or content.width() == 0:
            return 0
        col = int(round((x - content.left()) / content.width() * self._n_positions))
        return max(0, min(self._n_positions - 1, col))

    def _rect_bounds(self, content: QRect) -> tuple[float, float]:
        x1 = self._col_to_x(self._vis_start, content)
        x2 = self._col_to_x(self._vis_end + 1, content)
        return x1, max(x1 + 2.0, x2)

    # ── cache / rendering ───────────────────────────────────

    def _invalidate(self) -> None:
        self._buf = None
        self._cache_cols = -1

    def _ensure_buffer(self, n_cols: int) -> None:
        if self._buf is not None and self._cache_cols == n_cols:
            return
        if self._results is None or not self._results.grids or n_cols <= 0:
            self._buf = None
            self._cache_cols = n_cols
            return
        self._buf = build_overview_buffer(self._results.grids, self._view, n_cols)
        self._cache_cols = n_cols

    # ── painting ────────────────────────────────────────────

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#14141e"))

        if self._results is None or not self._results.grids:
            painter.setPen(QColor("#6a6a82"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No results loaded"
            )
            return

        content = self._content_rect()
        n_cols = self._n_cols(content.width())
        if n_cols == 0 or content.height() <= 0:
            return
        self._ensure_buffer(n_cols)
        if self._buf is None:
            return

        n_rows = self._buf.shape[0]
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        qimg = QImage(
            self._buf.data,
            n_cols,
            n_rows,
            n_cols * 4,
            QImage.Format.Format_RGBA8888,
        )
        painter.drawImage(content, qimg)

        self._paint_ruler(painter, content)
        self._paint_row_labels(painter, content, n_rows)
        self._paint_viewport_rect(painter, content)

    def _paint_ruler(self, painter: QPainter, content: QRect) -> None:
        positions = self._first_positions
        if positions is None:
            return
        painter.setPen(QColor("#a0a0b8"))
        painter.setFont(QFont("Cascadia Mono", 8))
        # A label roughly every 130 px.
        n_ticks = max(2, content.width() // 130)
        for i in range(n_ticks + 1):
            frac = i / n_ticks
            col = min(self._n_positions - 1, int(frac * self._n_positions))
            pos_val = int(positions[col]) + 1
            x = int(content.left() + frac * content.width())
            align = Qt.AlignmentFlag.AlignVCenter
            if i == 0:
                rect = QRect(x, 0, 80, OV_TOP_RULER)
                align |= Qt.AlignmentFlag.AlignLeft
            elif i == n_ticks:
                rect = QRect(x - 80, 0, 80, OV_TOP_RULER)
                align |= Qt.AlignmentFlag.AlignRight
            else:
                rect = QRect(x - 40, 0, 80, OV_TOP_RULER)
                align |= Qt.AlignmentFlag.AlignHCenter
            painter.drawText(rect, align, f"{pos_val:,}")
            painter.setPen(QColor("#33334a"))
            painter.drawLine(x, OV_TOP_RULER - 2, x, content.bottom())
            painter.setPen(QColor("#a0a0b8"))

    def _paint_row_labels(self, painter: QPainter, content: QRect, n_rows: int) -> None:
        painter.setPen(QColor("#cfcfe0"))
        painter.setFont(QFont("Cascadia Mono", 8))
        row_h = content.height() / n_rows
        for ri, grid in enumerate(self._results.grids):
            y = content.top() + ri * row_h
            painter.drawText(
                QRect(0, int(y), OV_LEFT_GUTTER - 4, int(row_h) + 1),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{grid.oligo_length}",
            )

    def _paint_viewport_rect(self, painter: QPainter, content: QRect) -> None:
        if self._n_positions == 0:
            return
        x1, x2 = self._rect_bounds(content)
        top = content.top()
        bottom = content.bottom() + 1
        # Dim the regions outside the visible slice.
        shade = QColor(10, 10, 16, 130)
        if x1 > content.left():
            painter.fillRect(
                QRect(content.left(), top, int(x1 - content.left()), bottom - top),
                shade,
            )
        if x2 < content.right():
            painter.fillRect(
                QRect(int(x2), top, int(content.right() - x2) + 1, bottom - top),
                shade,
            )
        # Bright frame around the visible slice.
        painter.setPen(QPen(QColor("#f0f0ff"), 1))
        painter.drawRect(QRect(int(x1), top, max(1, int(x2 - x1)), bottom - top - 1))

    # ── mouse interaction ───────────────────────────────────

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._n_positions == 0:
            return
        content = self._content_rect()
        if content.width() <= 0:
            return
        x = event.position().x()
        x1, x2 = self._rect_bounds(content)
        if x1 <= x <= x2:
            # Grab the rectangle where the user clicked and slide it.
            self._grab_dx = x - x1
        else:
            # Clicked outside — recentre the slice on the cursor.
            self._grab_dx = (x2 - x1) / 2.0
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._emit_left_for(x, content)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        content = self._content_rect()
        if self._dragging:
            self._emit_left_for(event.position().x(), content)
            return
        if self._n_positions:
            x = event.position().x()
            x1, x2 = self._rect_bounds(content)
            inside = x1 <= x <= x2 and content.top() <= event.position().y() <= content.bottom()
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if inside else Qt.CursorShape.ArrowCursor
            )

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _emit_left_for(self, x: float, content: QRect) -> None:
        left_col = self._x_to_col(x - self._grab_dx, content)
        self.viewportDragged.emit(left_col)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._invalidate()


class OverviewWindow(QDialog):
    """Non-modal floating window wrapping :class:`OverviewPanel`."""

    viewportDragged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Overview")
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Tool)
        self.resize(900, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        self._panel = OverviewPanel()
        layout.addWidget(self._panel, 1)

        hint = QLabel("Each column shows the best-fitting position in its slice. Drag the box to navigate.")
        hint.setStyleSheet("color: #8a8aa0; font-size: 10px;")
        layout.addWidget(hint)

        self._panel.viewportDragged.connect(self.viewportDragged.emit)

    # Delegate to the panel.
    def set_results(self, results: ScreeningResults | None) -> None:
        self._panel.set_results(results)

    def set_view(self, view: HeatmapView) -> None:
        self._panel.set_view(view)

    def set_visible_range(self, col_start: int, col_end: int) -> None:
        self._panel.set_visible_range(col_start, col_end)

    def refresh(self) -> None:
        self._panel.refresh()
