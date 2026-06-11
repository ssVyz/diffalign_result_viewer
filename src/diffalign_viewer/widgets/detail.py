"""Detail dock — variants table + exclusivity histogram for the selected cell.

A `QAbstractTableModel`-backed table is used so very long variant lists
(thousands of entries) render lazily without UI hitches.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..colors import base_color
from ..models import (
    AnalysisParams,
    PositionDetail,
    Variant,
)
from ..sequence import AMBIGUITY_CODES, format_sequence_display
from .detail_text import PositionDetailTextDialog, build_detail_text

VARIANT_HEADERS = ["#", "Sequence", "Count", "%", "Cumulative"]


class VariantTableModel(QAbstractTableModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._variants: list[Variant] = []
        self._cumulative: list[float] = []
        self._threshold_index = -1  # 0-based row at the variants_needed boundary
        self._no_match_count = 0
        self._total_sequences = 0
        self._reverse_complement = False
        self._codon_spacing = False

    def set_data(
        self,
        variants: list[Variant],
        threshold_index: int,
        no_match_count: int,
        total_sequences: int,
    ) -> None:
        self.beginResetModel()
        self._variants = variants
        self._cumulative = []
        cum = 0.0
        for v in variants:
            cum += v.percentage
            self._cumulative.append(cum)
        self._threshold_index = threshold_index - 1
        self._no_match_count = no_match_count
        self._total_sequences = total_sequences
        self.endResetModel()

    def set_display(self, reverse_complement: bool, codon_spacing: bool) -> None:
        self._reverse_complement = reverse_complement
        self._codon_spacing = codon_spacing
        if self._variants:
            self.dataChanged.emit(
                self.index(0, 1),
                self.index(self.rowCount() - 1, 1),
                [Qt.ItemDataRole.DisplayRole],
            )

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._variants) + (1 if self._no_match_count > 0 else 0)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return VARIANT_HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        n_variants = len(self._variants)

        if row >= n_variants:
            # No-match row
            if role == Qt.ItemDataRole.DisplayRole:
                if col == 0:
                    return ""
                if col == 1:
                    return "(no match)"
                if col == 2:
                    return f"{self._no_match_count}"
                if col == 3:
                    pct = (
                        self._no_match_count / self._total_sequences * 100.0
                        if self._total_sequences
                        else 0.0
                    )
                    return f"{pct:.1f}%"
                if col == 4:
                    return ""
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(QColor("#e0a040"))
            if role == Qt.ItemDataRole.FontRole and col == 1:
                f = QFont()
                f.setItalic(True)
                return f
            return None

        v = self._variants[row]
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row + 1)
            if col == 1:
                return format_sequence_display(
                    v.sequence, self._reverse_complement, self._codon_spacing
                )
            if col == 2:
                return f"{v.count}"
            if col == 3:
                return f"{v.percentage:.1f}%"
            if col == 4:
                return f"{self._cumulative[row]:.1f}%"

        if role == Qt.ItemDataRole.FontRole and col == 1:
            f = QFont("Cascadia Mono")
            f.setStyleHint(QFont.StyleHint.Monospace)
            return f

        if role == Qt.ItemDataRole.BackgroundRole and row == self._threshold_index:
            return QBrush(QColor(80, 192, 112, 32))

        if role == Qt.ItemDataRole.ForegroundRole and row == self._threshold_index:
            return QBrush(QColor("#7fdd9c"))

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 2, 3, 4):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        return None


class ExclusivityTableModel(QAbstractTableModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buckets: list = []

    def set_data(self, buckets) -> None:
        self.beginResetModel()
        self._buckets = list(buckets)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._buckets)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return ["Mismatches", "Count", "Example"][section]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        bucket = self._buckets[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return "no match" if bucket.is_no_match else str(bucket.mismatches)
            if col == 1:
                return str(bucket.count)
            if col == 2:
                name = bucket.example_name
                return name if len(name) <= 60 else name[:57] + "…"
        if role == Qt.ItemDataRole.ToolTipRole and col == 2:
            return bucket.example_name
        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            if bucket.is_no_match:
                return QBrush(QColor("#7fdd9c"))
            if bucket.mismatches == 0:
                return QBrush(QColor("#e07070"))
            if bucket.mismatches <= 2:
                return QBrush(QColor("#e0a040"))
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (0, 1):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class ColorizedSequenceLabel(QLabel):
    """Renders a sequence with per-base coloring; ambiguity codes are styled."""

    def set_sequence(
        self, sequence: str, reverse_complement: bool, codon_spacing: bool
    ) -> None:
        seq = format_sequence_display(sequence, reverse_complement, codon_spacing)
        parts: list[str] = []
        for c in seq:
            if c == " ":
                parts.append(" ")
                continue
            r, g, b = base_color(c)
            color = f"#{r:02x}{g:02x}{b:02x}"
            if c in AMBIGUITY_CODES:
                parts.append(
                    f'<span style="color:{color}; font-style:italic; '
                    f'text-decoration:underline; font-weight:700;">{c}</span>'
                )
            else:
                parts.append(f'<span style="color:{color}">{c}</span>')
        self.setText("".join(parts))
        self.setTextFormat(Qt.TextFormat.RichText)


class HistogramBar(QFrame):
    """Tiny custom widget that renders the exclusivity mismatch histogram
    as a bar chart with a separate "no match" bucket. Painted directly so
    we don't have to pull in pyqtgraph for one chart."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buckets: list = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, buckets) -> None:
        self._buckets = list(buckets)
        self.update()

    def paintEvent(self, event):  # type: ignore[override]
        from PySide6.QtGui import QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#1a1a26"))

        if not self._buckets:
            painter.setPen(QColor("#6a6a82"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No exclusivity data")
            return

        max_count = max(b.count for b in self._buckets) or 1
        margin = 8
        label_h = 14
        plot_top = margin
        plot_bottom = self.height() - margin - label_h
        plot_h = max(1, plot_bottom - plot_top)

        n = len(self._buckets)
        if n == 0:
            return
        bar_area_w = self.width() - 2 * margin
        bar_w = max(2, bar_area_w // n - 2)
        gap = max(1, (bar_area_w - bar_w * n) // max(1, n))

        painter.setFont(QFont("Cascadia Mono", 8))
        for i, bucket in enumerate(self._buckets):
            x = margin + i * (bar_w + gap)
            h = int(bucket.count / max_count * plot_h)
            y = plot_bottom - h

            if bucket.is_no_match:
                color = QColor("#50c070")  # best — separate bar
            elif bucket.mismatches == 0:
                color = QColor("#e07070")
            elif bucket.mismatches <= 2:
                color = QColor("#e0a040")
            else:
                color = QColor("#5b8af0")

            painter.fillRect(x, y, bar_w, h, color)
            painter.setPen(QPen(color.darker(120), 1))
            painter.drawRect(x, y, bar_w, h)

            painter.setPen(QColor("#a0a0b8"))
            label = "NM" if bucket.is_no_match else str(bucket.mismatches)
            from PySide6.QtCore import QRect

            painter.drawText(
                QRect(x - gap, plot_bottom + 2, bar_w + gap * 2, label_h),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )


class DetailPanel(QWidget):
    """Right-hand dock content: per-cell variants and exclusivity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._params: AnalysisParams | None = None
        self._template_sequence: str = ""

        self._stack = QStackedWidget(self)

        # Empty state
        empty = QWidget()
        empty_l = QVBoxLayout(empty)
        empty_l.addStretch(1)
        msg = QLabel("Hover or click a heatmap cell to see details.")
        msg.setStyleSheet("color: #6a6a82; font-style: italic;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_l.addWidget(msg)
        empty_l.addStretch(1)
        self._stack.addWidget(empty)

        # Detail content
        content = QWidget()
        c_l = QVBoxLayout(content)
        c_l.setContentsMargins(10, 10, 10, 10)
        c_l.setSpacing(8)

        title_row = QHBoxLayout()
        self._title = QLabel()
        title_font = QFont("Segoe UI", 12, QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #e0e0e8;")
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        self._txt_button = QPushButton("Text view…")
        self._txt_button.setToolTip(
            "Open these position details as plain, copy-pastable text"
        )
        self._txt_button.clicked.connect(self._show_text_view)
        title_row.addWidget(self._txt_button)
        c_l.addLayout(title_row)

        self._stats = QLabel()
        self._stats.setStyleSheet("color: #cfcfe0; font-size: 11px;")
        self._stats.setWordWrap(True)
        c_l.addWidget(self._stats)

        # Template oligo display
        template_frame = QFrame()
        template_frame.setObjectName("templateOligoFrame")
        tf_l = QHBoxLayout(template_frame)
        tf_l.setContentsMargins(8, 6, 8, 6)
        label = QLabel("Template oligo:")
        label.setStyleSheet("color: #a0a0b8; font-size: 11px;")
        tf_l.addWidget(label)
        self._template_oligo = ColorizedSequenceLabel()
        self._template_oligo.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; letter-spacing: 0.5px;"
        )
        tf_l.addWidget(self._template_oligo)
        tf_l.addStretch(1)
        c_l.addWidget(template_frame)

        # Display options
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)
        self._chk_revcomp = QCheckBox("Reverse complement")
        self._chk_codon = QCheckBox("Codon spacing")
        self._chk_revcomp.toggled.connect(self._refresh_display_options)
        self._chk_codon.toggled.connect(self._refresh_display_options)
        opts_row.addWidget(self._chk_revcomp)
        opts_row.addWidget(self._chk_codon)
        opts_row.addStretch(1)
        c_l.addLayout(opts_row)

        # Variants table
        var_label = QLabel("Variants")
        var_label.setStyleSheet(
            "color: #a0a0b8; text-transform: uppercase; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;"
        )
        c_l.addWidget(var_label)
        self._variant_model = VariantTableModel()
        self._variant_view = QTableView()
        self._variant_view.setModel(self._variant_model)
        self._variant_view.setAlternatingRowColors(True)
        self._variant_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._variant_view.verticalHeader().setVisible(False)
        self._variant_view.setShowGrid(False)
        self._variant_view.horizontalHeader().setStretchLastSection(False)
        self._variant_view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for col in (0, 2, 3, 4):
            self._variant_view.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._variant_view.setMinimumHeight(180)
        c_l.addWidget(self._variant_view, 2)

        # Exclusivity section
        self._excl_label = QLabel("Exclusivity")
        self._excl_label.setStyleSheet(
            "color: #a0a0b8; text-transform: uppercase; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;"
        )
        c_l.addWidget(self._excl_label)

        self._excl_summary = QLabel()
        self._excl_summary.setStyleSheet("color: #cfcfe0; font-size: 11px;")
        self._excl_summary.setWordWrap(True)
        c_l.addWidget(self._excl_summary)

        self._histogram = HistogramBar()
        c_l.addWidget(self._histogram)

        self._excl_model = ExclusivityTableModel()
        self._excl_view = QTableView()
        self._excl_view.setModel(self._excl_model)
        self._excl_view.setAlternatingRowColors(True)
        self._excl_view.verticalHeader().setVisible(False)
        self._excl_view.setShowGrid(False)
        self._excl_view.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._excl_view.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._excl_view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._excl_view.setMinimumHeight(120)
        c_l.addWidget(self._excl_view, 1)

        self._stack.addWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self._stack.setCurrentIndex(0)
        self._current_detail: PositionDetail | None = None
        self._current_length: int = 0

    def set_context(self, params: AnalysisParams, template_sequence: str) -> None:
        self._params = params
        self._template_sequence = template_sequence

    def show_detail(self, detail: PositionDetail | None, length: int) -> None:
        if detail is None:
            self._stack.setCurrentIndex(0)
            self._current_detail = None
            return

        self._current_detail = detail
        self._current_length = length
        self._stack.setCurrentIndex(1)

        self._title.setText(f"Position {detail.position + 1}  ·  {length} bp")

        if detail.skipped:
            reason = detail.skip_reason or "skipped"
            self._stats.setText(
                f'<span style="color:#e0a040;">Skipped: {reason}</span>'
            )
            self._template_oligo.setText("")
            self._variant_model.set_data([], 0, 0, 0)
            self._excl_label.hide()
            self._excl_summary.hide()
            self._histogram.hide()
            self._excl_view.hide()
            return

        threshold_pct = (
            self._params.coverage_threshold if self._params is not None else 90.0
        )
        nm_pct = (
            (detail.no_match_count / detail.total_sequences) * 100.0
            if detail.total_sequences
            else 0.0
        )
        stats_html = (
            f"Total references: <b>{detail.total_sequences}</b> · "
            f"Matched: <b>{detail.sequences_analyzed}</b>"
        )
        if detail.no_match_count > 0:
            stats_html += (
                f" · <span style='color:#e0a040'>No match: "
                f"{detail.no_match_count} ({nm_pct:.1f}%)</span>"
            )
        stats_html += (
            f"<br/>Variants needed for {threshold_pct:g}% coverage: "
            f"<b>{detail.variants_for_threshold}</b> · "
            f"Coverage at threshold: <b>{detail.coverage_at_threshold:.1f}%</b>"
        )
        self._stats.setText(stats_html)

        # Template oligo for this window
        if self._template_sequence and detail.position + length <= len(
            self._template_sequence
        ):
            template_oligo = self._template_sequence[
                detail.position : detail.position + length
            ]
            self._template_oligo.set_sequence(
                template_oligo,
                self._chk_revcomp.isChecked(),
                self._chk_codon.isChecked(),
            )
        else:
            self._template_oligo.setText("")

        # Variants
        self._variant_model.set_data(
            detail.variants,
            detail.variants_for_threshold,
            detail.no_match_count,
            detail.total_sequences,
        )
        self._variant_model.set_display(
            self._chk_revcomp.isChecked(), self._chk_codon.isChecked()
        )

        # Exclusivity
        if detail.exclusivity is None:
            self._excl_label.hide()
            self._excl_summary.hide()
            self._histogram.hide()
            self._excl_view.hide()
        else:
            self._excl_label.show()
            self._excl_summary.show()
            self._histogram.show()
            self._excl_view.show()

            excl = detail.exclusivity
            if excl.min_mismatches is None:
                summary = (
                    f"Total: {excl.total_sequences} · "
                    f"<span style='color:#7fdd9c'>All exclusivity sequences: no match "
                    f"(fully specific)</span>"
                )
            else:
                summary = (
                    f"Total: {excl.total_sequences} · "
                    f"No-match: {excl.no_match_count} · "
                    f"Min mismatches: <b>{excl.min_mismatches}</b>"
                )
            self._excl_summary.setText(summary)
            self._histogram.set_data(excl.mismatch_histogram)
            self._excl_model.set_data(excl.mismatch_histogram)

    def _refresh_display_options(self) -> None:
        if self._current_detail is None:
            return
        self.show_detail(self._current_detail, self._current_length)

    def _show_text_view(self) -> None:
        if self._current_detail is None:
            return
        text = build_detail_text(
            self._current_detail,
            self._current_length,
            self._params,
            self._template_sequence,
            self._chk_revcomp.isChecked(),
            self._chk_codon.isChecked(),
        )
        dialog = PositionDetailTextDialog(text, self)
        dialog.exec()

    def reset(self) -> None:
        self._stack.setCurrentIndex(0)
        self._current_detail = None
