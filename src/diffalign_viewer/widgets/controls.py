"""View / coloring controls and the analysis-params panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import ScreeningResults


class ViewControls(QWidget):
    """Color thresholds, no-match thresholds, differential settings, zoom."""

    viewChanged = Signal()
    coverageThresholdChanged = Signal(float)
    differentialToggled = Signal(bool)
    zoomChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # View settings
        view_box = QGroupBox("View")
        v_form = QFormLayout(view_box)
        v_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        v_form.setHorizontalSpacing(8)
        v_form.setVerticalSpacing(4)

        zoom_row = QHBoxLayout()
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(30, 400)
        self._zoom_slider.setValue(100)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setMinimumWidth(40)
        zoom_row.addWidget(self._zoom_slider)
        zoom_row.addWidget(self._zoom_label)
        zoom_widget = QWidget()
        zoom_widget.setLayout(zoom_row)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        v_form.addRow("Zoom", zoom_widget)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)

        self._coverage = QDoubleSpinBox()
        self._coverage.setRange(1, 100)
        self._coverage.setSingleStep(0.5)
        self._coverage.setValue(95)
        self._coverage.setSuffix(" %")
        # keyboardTracking=False: don't fire on every keystroke while typing
        # (recompute is expensive). Arrow buttons and Enter/focus-loss still fire.
        self._coverage.setKeyboardTracking(False)
        self._coverage.valueChanged.connect(self.coverageThresholdChanged.emit)
        v_form.addRow("Coverage threshold", self._coverage)

        outer.addWidget(view_box)

        # Color thresholds
        color_box = QGroupBox("Color thresholds")
        c_form = QFormLayout(color_box)
        c_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        c_form.setHorizontalSpacing(8)
        c_form.setVerticalSpacing(4)

        self._green_at = QSpinBox()
        self._green_at.setRange(1, 1000)
        self._green_at.setValue(1)
        self._green_at.setSuffix(" variants")
        self._red_at = QSpinBox()
        self._red_at.setRange(1, 1000)
        self._red_at.setValue(10)
        self._red_at.setSuffix(" variants")
        self._nm_ok = QDoubleSpinBox()
        self._nm_ok.setRange(0, 100)
        self._nm_ok.setValue(5)
        self._nm_ok.setSuffix(" %")
        self._nm_bad = QDoubleSpinBox()
        self._nm_bad.setRange(0, 100)
        self._nm_bad.setValue(50)
        self._nm_bad.setSuffix(" %")

        c_form.addRow("Green at", self._green_at)
        c_form.addRow("Red at", self._red_at)
        c_form.addRow("No-match OK", self._nm_ok)
        c_form.addRow("No-match Bad", self._nm_bad)
        outer.addWidget(color_box)

        for w in (self._green_at, self._red_at):
            w.valueChanged.connect(lambda *_: self.viewChanged.emit())
        for w in (self._nm_ok, self._nm_bad):
            w.valueChanged.connect(lambda *_: self.viewChanged.emit())

        # Differential settings
        self._diff_box = QGroupBox("Differential mode")
        d_form = QFormLayout(self._diff_box)
        d_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        d_form.setHorizontalSpacing(8)
        d_form.setVerticalSpacing(4)

        self._diff_enable = QCheckBox("Show exclusivity colors")
        self._diff_enable.toggled.connect(self._on_diff_toggled)
        d_form.addRow(self._diff_enable)

        self._diff_green = QSpinBox()
        self._diff_green.setRange(0, 100)
        self._diff_green.setValue(5)
        self._diff_green.setSuffix(" mm")
        self._diff_red = QSpinBox()
        self._diff_red.setRange(0, 100)
        self._diff_red.setValue(0)
        self._diff_red.setSuffix(" mm")
        self._diff_ignore = QSpinBox()
        self._diff_ignore.setRange(0, 100000)
        self._diff_ignore.setValue(0)
        self._diff_ignore.setSuffix(" seqs")

        d_form.addRow("Green at", self._diff_green)
        d_form.addRow("Red at", self._diff_red)
        d_form.addRow("Ignore if ≤", self._diff_ignore)
        outer.addWidget(self._diff_box)

        for w in (self._diff_green, self._diff_red, self._diff_ignore):
            w.valueChanged.connect(lambda *_: self.viewChanged.emit())

        outer.addStretch(1)
        self._update_diff_enabled()

    def apply_results(self, results: ScreeningResults) -> None:
        self._coverage.blockSignals(True)
        self._coverage.setValue(results.params.coverage_threshold)
        self._coverage.blockSignals(False)

        # Differential subgroup is hidden if file isn't differential.
        self._diff_box.setEnabled(results.differential_enabled)
        if not results.differential_enabled and self._diff_enable.isChecked():
            self._diff_enable.setChecked(False)

    def _on_zoom_changed(self, val: int) -> None:
        self._zoom_label.setText(f"{val}%")
        self.zoomChanged.emit(val / 100.0)

    def _on_diff_toggled(self, checked: bool) -> None:
        self._update_diff_enabled()
        self.differentialToggled.emit(checked)

    def _update_diff_enabled(self) -> None:
        for w in (self._diff_green, self._diff_red, self._diff_ignore):
            w.setEnabled(self._diff_enable.isChecked())

    # Getters used by main window to assemble HeatmapView
    def coverage_threshold(self) -> float:
        return self._coverage.value()

    def green_at(self) -> int:
        return self._green_at.value()

    def red_at(self) -> int:
        return self._red_at.value()

    def nomatch_ok(self) -> float:
        return self._nm_ok.value()

    def nomatch_bad(self) -> float:
        return self._nm_bad.value()

    def differential(self) -> bool:
        return self._diff_enable.isChecked()

    def diff_green(self) -> int:
        return self._diff_green.value()

    def diff_red(self) -> int:
        return self._diff_red.value()

    def diff_ignore(self) -> int:
        return self._diff_ignore.value()

    def zoom(self) -> float:
        return self._zoom_slider.value() / 100.0


class ParamsPanel(QFrame):
    """Read-only summary of analysis parameters from the loaded file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("paramsPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(4)

        title = QLabel("Analysis parameters")
        title.setStyleSheet(
            "color: #a0a0b8; text-transform: uppercase; "
            "font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )
        outer.addWidget(title)

        self._content = QLabel()
        self._content.setStyleSheet("color: #cfcfe0; font-size: 11px;")
        self._content.setTextFormat(Qt.TextFormat.RichText)
        self._content.setWordWrap(True)
        outer.addWidget(self._content)

        self._content.setText("<i>No file loaded.</i>")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def set_results(self, results: ScreeningResults | None) -> None:
        if results is None:
            self._content.setText("<i>No file loaded.</i>")
            return

        p = results.params
        rows: list[str] = []
        rows.append(f"<b>Method:</b> {p.method.description()}")
        rows.append(
            f"<b>Oligo length:</b> {p.min_oligo_length} – {p.max_oligo_length} bp"
            + (f" (skip {p.length_skip})" if p.length_skip else "")
        )
        rows.append(
            f"<b>Resolution:</b> {p.resolution} · "
            f"<b>Coverage:</b> {p.coverage_threshold:g}% · "
            f"<b>Exclude N:</b> {'yes' if p.exclude_n else 'no'}"
        )
        rows.append(
            f"<b>Pairwise:</b> match {p.pairwise.match_score}, "
            f"mismatch {p.pairwise.mismatch_score}, "
            f"gap open {p.pairwise.gap_open_penalty}, "
            f"gap extend {p.pairwise.gap_extend_penalty}, "
            f"max-mm {p.pairwise.max_mismatches}"
        )
        rows.append(
            f"<b>Threads:</b> {p.thread_count.description()} · "
            f"<b>Template:</b> {results.template_length:,} bp · "
            f"<b>References:</b> {results.total_sequences:,}"
        )
        if results.differential_enabled:
            n = results.exclusivity_sequence_count
            rows.append(
                f"<b>Differential:</b> on"
                + (f" · {n:,} exclusivity sequences" if n else "")
            )
        else:
            rows.append("<b>Differential:</b> off")
        self._content.setText("<br/>".join(rows))
