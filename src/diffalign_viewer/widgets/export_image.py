"""Export the whole-template result overview as a standalone image.

The exported picture is coloured by exactly the same bird's-eye logic as the
live :class:`~.overview.OverviewWindow` (see :func:`..overview.build_overview_buffer`),
so the image faithfully reproduces the current display settings. On top of the
heatmap it composes an optional title, a colour legend, a position ruler and a
metadata block describing the analysis parameters and the display settings used
to colour the image.

:func:`render_overview_image` does the painting and is independent of the
dialog, so it can be reused (e.g. for headless/batch export) if needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..colors import NO_DATA, _green_yellow_red_from_t, gradient_legend_swatches
from ..models import ScreeningResults
from .heatmap import HeatmapView
from .overview import build_overview_buffer

# Layout constants (in output pixels).
_MARGIN = 22
_GUTTER = 50  # left strip for oligo-length row labels
_TITLE_H = 30
_SUBTITLE_H = 20
_LEGEND_H = 34
_RULER_H = 20
_META_HEADER_H = 22
_META_LINE_H = 18
_SECTION_GAP = 12
_SKIP_COLOR = (60, 60, 80)


@dataclass
class _Theme:
    bg: QColor
    panel: QColor
    text: QColor
    muted: QColor
    grid: QColor
    swatch_text: QColor


def _theme(light: bool) -> _Theme:
    if light:
        return _Theme(
            bg=QColor("#ffffff"),
            panel=QColor("#f2f2f6"),
            text=QColor("#1a1a24"),
            muted=QColor("#555566"),
            grid=QColor("#cfcfd8"),
            swatch_text=QColor("#101018"),
        )
    return _Theme(
        bg=QColor("#14141e"),
        panel=QColor("#1e1e2e"),
        text=QColor("#e8e8f0"),
        muted=QColor("#a0a0b8"),
        grid=QColor("#33334a"),
        swatch_text=QColor("#fafafa"),
    )


@dataclass
class ImageExportOptions:
    """Everything the export dialog lets the user tweak."""

    width: int = 1600
    row_height: int = 18
    include_title: bool = True
    title: str = "diffalign result overview"
    include_legend: bool = True
    include_ruler: bool = True
    include_metadata: bool = True
    light_background: bool = False


# ── metadata / legend helpers ────────────────────────────────


def _metadata_lines(
    results: ScreeningResults,
    view: HeatmapView,
    coverage_threshold: float | None = None,
) -> list[str]:
    p = results.params
    # The heatmap is coloured with the threshold currently set in the viewer
    # (which may differ from the value recorded in the file), so report that.
    coverage = p.coverage_threshold if coverage_threshold is None else coverage_threshold
    lines: list[str] = []
    lines.append(f"Method:  {p.method.description()}")
    lines.append(
        f"Oligo length:  {p.min_oligo_length}–{p.max_oligo_length} bp"
        + (f" (skip {p.length_skip})" if p.length_skip else "")
    )
    lines.append(
        f"Resolution:  {p.resolution}      "
        f"Coverage threshold:  {coverage:g}%      "
        f"Exclude N:  {'yes' if p.exclude_n else 'no'}"
    )
    lines.append(
        f"Pairwise:  match {p.pairwise.match_score}, "
        f"mismatch {p.pairwise.mismatch_score}, "
        f"gap open {p.pairwise.gap_open_penalty}, "
        f"gap extend {p.pairwise.gap_extend_penalty}, "
        f"max-mm {p.pairwise.max_mismatches}"
    )
    lines.append(
        f"Threads:  {p.thread_count.description()}      "
        f"Template:  {results.template_length:,} bp      "
        f"References:  {results.total_sequences:,}"
    )
    if results.differential_enabled:
        n = results.exclusivity_sequence_count
        lines.append(
            "Differential:  on"
            + (f"      {n:,} exclusivity sequences" if n else "")
        )
    else:
        lines.append("Differential:  off")

    # The display settings actually used to colour this image, so the picture
    # documents itself.
    if view.differential_mode:
        lines.append(
            f"Display:  differential — green at {view.diff_green_at} mm, "
            f"red at {view.diff_red_at} mm, ignore ≤ {view.diff_ignore_count} seqs; "
            f"variant darkening {view.color_green_at}→{view.color_red_at}"
        )
    else:
        lines.append(
            f"Display:  variants — green at {view.color_green_at}, "
            f"red at {view.color_red_at}; "
            f"no-match OK {view.nomatch_ok_pct:g}%, bad {view.nomatch_bad_pct:g}%"
        )
    return lines


def _legend_swatches(view: HeatmapView) -> tuple[str, list[tuple[int, tuple[int, int, int]]]]:
    """Return (label, [(value, rgb), …]) for the legend strip, mode-aware."""
    if not view.differential_mode:
        return (
            "Variants for coverage:",
            gradient_legend_swatches(view.color_green_at, view.color_red_at, 8),
        )

    # Differential: colour encodes off-target min-mismatches — green at high
    # (specific), red at low (off-target match). Invert relative to variants.
    g, r = view.diff_green_at, view.diff_red_at
    lo, hi = min(g, r), max(g, r)
    steps = 8
    span = max(1, hi - lo)
    out: list[tuple[int, tuple[int, int, int]]] = []
    for i in range(steps + 1):
        mm = lo + span * i / steps
        if g <= r:
            t = 0.0 if mm <= g else 1.0
        elif mm >= g:
            t = 0.0
        elif mm <= r:
            t = 1.0
        else:
            t = (g - mm) / (g - r)
        out.append((round(mm), _green_yellow_red_from_t(t)))
    return ("Off-target min-mismatches (green = specific):", out)


# ── rendering ────────────────────────────────────────────────


def render_overview_image(
    results: ScreeningResults,
    view: HeatmapView,
    options: ImageExportOptions,
    current_path: str | None = None,
    coverage_threshold: float | None = None,
) -> QImage:
    """Compose the overview into a single :class:`QImage`.

    ``coverage_threshold`` is the value currently applied in the viewer; when
    given it overrides the file's recorded threshold in the metadata block so
    the label matches the colours actually shown. When ``None`` the recorded
    value is used.
    """
    th = _theme(options.light_background)
    width = max(480, int(options.width))
    content_left = _MARGIN + _GUTTER
    content_right = width - _MARGIN
    content_w = content_right - content_left

    grids = results.grids if results else []
    n_rows = len(grids)
    min_positions = (
        min(int(g.positions.shape[0]) for g in grids) if grids else 0
    )
    n_cols = min(content_w, min_positions) if content_w > 0 else 0

    meta = (
        _metadata_lines(results, view, coverage_threshold)
        if options.include_metadata
        else []
    )

    # ── vertical budget ──
    y = _MARGIN
    title_top = y
    if options.include_title:
        if options.title.strip():
            y += _TITLE_H
        y += _SUBTITLE_H + _SECTION_GAP
    legend_top = y
    if options.include_legend:
        y += _LEGEND_H + _SECTION_GAP
    ruler_top = y
    if options.include_ruler:
        y += _RULER_H
    heatmap_top = y
    heatmap_h = n_rows * options.row_height
    y += heatmap_h + _SECTION_GAP
    meta_top = y
    if options.include_metadata:
        y += _META_HEADER_H + len(meta) * _META_LINE_H
    height = y + _MARGIN

    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(th.bg)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    if n_cols <= 0 or n_rows == 0:
        painter.setPen(th.muted)
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "No results to export")
        painter.end()
        return img

    # ── title + subtitle ──
    if options.include_title:
        ty = title_top
        if options.title.strip():
            painter.setPen(th.text)
            painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            painter.drawText(
                QRect(_MARGIN, ty, width - 2 * _MARGIN, _TITLE_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                options.title.strip(),
            )
            ty += _TITLE_H
        fname = os.path.basename(current_path) if current_path else "(unsaved)"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        subtitle = (
            f"{fname}    ·    exported {stamp}    ·    "
            f"{results.template_length:,} bp  ×  {n_rows} lengths"
        )
        painter.setPen(th.muted)
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRect(_MARGIN, ty, width - 2 * _MARGIN, _SUBTITLE_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            subtitle,
        )

    # ── legend ──
    if options.include_legend:
        _paint_legend(painter, th, view, _MARGIN, legend_top, width - 2 * _MARGIN)

    # ── ruler ──
    positions = grids[0].positions
    n_positions = int(positions.shape[0])
    heatmap_bottom = heatmap_top + heatmap_h
    if options.include_ruler and n_positions > 0:
        painter.setFont(QFont("Cascadia Mono", 8))
        n_ticks = max(2, content_w // 150)
        for i in range(n_ticks + 1):
            frac = i / n_ticks
            col = min(n_positions - 1, int(frac * n_positions))
            pos_val = int(positions[col]) + 1
            x = int(content_left + frac * content_w)
            if i == 0:
                rect = QRect(x, ruler_top, 90, _RULER_H)
                align = Qt.AlignmentFlag.AlignLeft
            elif i == n_ticks:
                rect = QRect(x - 90, ruler_top, 90, _RULER_H)
                align = Qt.AlignmentFlag.AlignRight
            else:
                rect = QRect(x - 45, ruler_top, 90, _RULER_H)
                align = Qt.AlignmentFlag.AlignHCenter
            painter.setPen(th.muted)
            painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, f"{pos_val:,}")
            # Faint gridline down across the heatmap.
            painter.setPen(QPen(th.grid, 1))
            painter.drawLine(x, ruler_top + _RULER_H - 2, x, heatmap_bottom)

    # ── heatmap ──
    buf = build_overview_buffer(grids, view, n_cols)
    qimg = QImage(buf.data, n_cols, n_rows, n_cols * 4, QImage.Format.Format_RGBA8888)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(QRect(content_left, heatmap_top, content_w, heatmap_h), qimg)
    # Thin frame so the heatmap reads as a panel on a light background too.
    painter.setPen(QPen(th.grid, 1))
    painter.drawRect(QRect(content_left, heatmap_top, content_w, heatmap_h))

    # ── row labels (oligo lengths) ──
    painter.setPen(th.text)
    painter.setFont(QFont("Cascadia Mono", 8))
    for ri, grid in enumerate(grids):
        ry = heatmap_top + ri * options.row_height
        painter.drawText(
            QRect(_MARGIN, ry, _GUTTER - 6, options.row_height),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{grid.oligo_length}",
        )

    # ── metadata block ──
    if options.include_metadata:
        painter.setPen(th.text)
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(
            QRect(_MARGIN, meta_top, width - 2 * _MARGIN, _META_HEADER_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Analysis & display settings",
        )
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(th.muted)
        ly = meta_top + _META_HEADER_H
        for line in meta:
            painter.drawText(
                QRect(_MARGIN, ly, width - 2 * _MARGIN, _META_LINE_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                line,
            )
            ly += _META_LINE_H

    painter.end()
    return img


def _paint_legend(
    painter: QPainter, th: _Theme, view: HeatmapView, x0: int, y: int, avail_w: int
) -> None:
    label, swatches = _legend_swatches(view)
    painter.setFont(QFont("Segoe UI", 10))
    painter.setPen(th.muted)
    fm = painter.fontMetrics()
    x = x0
    painter.drawText(
        QRect(x, y, fm.horizontalAdvance(label), _LEGEND_H),
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        label,
    )
    x += fm.horizontalAdvance(label) + 12

    sw_w, sw_h = 38, 22
    sy = y + (_LEGEND_H - sw_h) // 2
    painter.setFont(QFont("Segoe UI", 9))
    for value, (r, g, b) in swatches:
        painter.fillRect(x, sy, sw_w, sw_h, QColor(r, g, b))
        painter.setPen(th.swatch_text)
        painter.drawText(
            QRect(x, sy, sw_w, sw_h), Qt.AlignmentFlag.AlignCenter, str(value)
        )
        x += sw_w + 1

    x += 14
    for tint, text in ((_SKIP_COLOR, "skip"), (NO_DATA, "—")):
        painter.fillRect(x, sy, sw_w, sw_h, QColor(*tint))
        painter.setPen(QColor("#fafafa"))
        painter.drawText(QRect(x, sy, sw_w, sw_h), Qt.AlignmentFlag.AlignCenter, text)
        x += sw_w + 1


# ── dialog ───────────────────────────────────────────────────


class ExportImageDialog(QDialog):
    """Modal dialog with a live preview and export options."""

    _WIDTH_CHOICES = (1200, 1600, 2000, 2400, 3200)

    def __init__(
        self,
        results: ScreeningResults,
        view: HeatmapView,
        current_path: str | None = None,
        parent: QWidget | None = None,
        coverage_threshold: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export as image")
        self.setModal(True)
        self.resize(1080, 720)

        self._results = results
        self._view = view
        self._current_path = current_path
        self._coverage_threshold = coverage_threshold
        self._settings = QSettings("diffalign", "result-viewer")
        self._image: QImage | None = None

        default_title = "diffalign result overview"
        if current_path:
            default_title = Path(current_path).stem

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── preview (left) ──
        self._preview = QLabel("Rendering preview…")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background: #0e0e16; border: 1px solid #33334a;")
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._preview)
        self._scroll.setMinimumWidth(560)
        root.addWidget(self._scroll, 1)

        # ── controls (right) ──
        panel = QWidget()
        panel.setFixedWidth(300)
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)

        content_box = QGroupBox("Content")
        cform = QVBoxLayout(content_box)
        cform.setSpacing(6)

        self._chk_title = QCheckBox("Title")
        self._chk_title.setChecked(True)
        self._title_edit = QLineEdit(default_title)
        self._title_edit.setPlaceholderText("Image title")
        self._chk_legend = QCheckBox("Colour legend")
        self._chk_legend.setChecked(True)
        self._chk_ruler = QCheckBox("Position ruler")
        self._chk_ruler.setChecked(True)
        self._chk_meta = QCheckBox("Metadata (parameters & settings)")
        self._chk_meta.setChecked(True)

        cform.addWidget(self._chk_title)
        cform.addWidget(self._title_edit)
        cform.addWidget(self._chk_legend)
        cform.addWidget(self._chk_ruler)
        cform.addWidget(self._chk_meta)
        side.addWidget(content_box)

        layout_box = QGroupBox("Layout")
        lform = QFormLayout(layout_box)
        lform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._width_combo = QComboBox()
        for w in self._WIDTH_CHOICES:
            self._width_combo.addItem(f"{w} px", w)
        self._width_combo.setCurrentIndex(self._WIDTH_CHOICES.index(1600))

        self._row_h = QSpinBox()
        self._row_h.setRange(6, 60)
        self._row_h.setValue(18)
        self._row_h.setSuffix(" px")

        self._bg_combo = QComboBox()
        self._bg_combo.addItem("Dark", False)
        self._bg_combo.addItem("Light", True)

        lform.addRow("Width", self._width_combo)
        lform.addRow("Row height", self._row_h)
        lform.addRow("Background", self._bg_combo)
        side.addWidget(layout_box)

        self._dims = QLabel("")
        self._dims.setStyleSheet("color: #8a8aa0; font-size: 10px;")
        side.addWidget(self._dims)

        side.addStretch(1)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("Save image…")
        self._save_btn.setDefault(True)
        close_btn = QPushButton("Close")
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(self._save_btn)
        side.addLayout(btn_row)

        root.addWidget(panel, 0)

        # ── signals ──
        for w in (self._chk_title, self._chk_legend, self._chk_ruler, self._chk_meta):
            w.toggled.connect(self._refresh)
        self._title_edit.textChanged.connect(self._refresh)
        self._width_combo.currentIndexChanged.connect(self._refresh)
        self._row_h.valueChanged.connect(self._refresh)
        self._bg_combo.currentIndexChanged.connect(self._refresh)
        self._chk_title.toggled.connect(self._title_edit.setEnabled)
        self._save_btn.clicked.connect(self._save)
        close_btn.clicked.connect(self.reject)

        self._refresh()

    # ── option assembly / render ──

    def _options(self) -> ImageExportOptions:
        return ImageExportOptions(
            width=self._width_combo.currentData(),
            row_height=self._row_h.value(),
            include_title=self._chk_title.isChecked(),
            title=self._title_edit.text(),
            include_legend=self._chk_legend.isChecked(),
            include_ruler=self._chk_ruler.isChecked(),
            include_metadata=self._chk_meta.isChecked(),
            light_background=bool(self._bg_combo.currentData()),
        )

    def _refresh(self) -> None:
        self._image = render_overview_image(
            self._results,
            self._view,
            self._options(),
            self._current_path,
            self._coverage_threshold,
        )
        self._dims.setText(
            f"Output: {self._image.width()} × {self._image.height()} px"
        )
        self._update_preview()

    def _update_preview(self) -> None:
        if self._image is None:
            return
        target = self._scroll.viewport().size()
        if target.width() <= 1 or target.height() <= 1:
            return
        pix = QPixmap.fromImage(self._image).scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(pix)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._update_preview()

    # ── save ──

    def _save(self) -> None:
        if self._image is None:
            return
        last_dir = self._settings.value("paths/last_export", str(Path.home()))
        stem = (
            Path(self._current_path).stem if self._current_path else "overview"
        )
        suggested = str(Path(str(last_dir)) / f"{stem}_overview.png")
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Save overview image",
            suggested,
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg)",
        )
        if not path:
            return

        # Ensure an extension matching the chosen filter if the user omitted one.
        if not Path(path).suffix:
            path += ".jpg" if "jpg" in selected.lower() else ".png"

        image = self._image
        if Path(path).suffix.lower() in (".jpg", ".jpeg"):
            # JPEG has no alpha — flatten onto the chosen background colour.
            flat = QImage(image.size(), QImage.Format.Format_RGB32)
            flat.fill(_theme(self._options().light_background).bg)
            p = QPainter(flat)
            p.drawImage(0, 0, image)
            p.end()
            image = flat

        if image.save(path):
            self._settings.setValue("paths/last_export", str(Path(path).parent))
            self.accept()
        else:
            QMessageBox.warning(
                self, "Save failed", f"Could not write the image to:\n{path}"
            )
