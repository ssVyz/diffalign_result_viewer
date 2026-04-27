"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .style import STYLESHEET
from .widgets.main_window import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("diffalign result viewer")
    app.setOrganizationName("diffalign")
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 9))

    window = MainWindow()
    if len(sys.argv) > 1:
        window.load_file(sys.argv[1])
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
