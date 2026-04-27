"""Color legend widget."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..colors import gradient_legend_swatches


class LegendWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._green_at = 1
        self._red_at = 10
        self._differential = False
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_state(self, green_at: int, red_at: int, differential: bool) -> None:
        self._green_at = green_at
        self._red_at = red_at
        self._differential = differential
        self.update()

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(400, 28)

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e2e"))
        painter.setFont(QFont("Segoe UI", 9))

        x = 8
        y = 4
        h = self.height() - 8

        if self._differential:
            label = "Differential: green = high min-MM (specific) → red = low min-MM (off-target match)"
        else:
            label = "Variants for coverage:"
        painter.setPen(QColor("#a0a0b8"))
        painter.drawText(x, y + h - 6, label)
        x += painter.fontMetrics().horizontalAdvance(label) + 12

        swatches = gradient_legend_swatches(self._green_at, self._red_at, 8)
        sw_w = 32
        for value, (r, g, b) in swatches:
            painter.fillRect(x, y, sw_w, h, QColor(r, g, b))
            painter.setPen(QColor("#fafafa"))
            painter.drawText(x, y, sw_w, h, Qt.AlignmentFlag.AlignCenter, str(value))
            x += sw_w + 1

        # Skipped & no-data swatches
        x += 12
        painter.fillRect(x, y, sw_w, h, QColor(60, 60, 80))
        painter.setPen(QColor("#fafafa"))
        painter.drawText(x, y, sw_w, h, Qt.AlignmentFlag.AlignCenter, "skip")
        x += sw_w + 1
        painter.fillRect(x, y, sw_w, h, QColor(40, 40, 40))
        painter.setPen(QColor("#fafafa"))
        painter.drawText(x, y, sw_w, h, Qt.AlignmentFlag.AlignCenter, "—")
