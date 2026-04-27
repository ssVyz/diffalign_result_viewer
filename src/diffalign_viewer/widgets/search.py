"""Sequence search panel — IUPAC-aware exact search across the template."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..sequence import SearchMatch, search_template


class SearchPanel(QWidget):
    matchesUpdated = Signal(list)  # list[SearchMatch]
    matchActivated = Signal(int)  # template position

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._template = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        title = QLabel("Search sequence")
        title.setStyleSheet(
            "color: #a0a0b8; text-transform: uppercase; "
            "font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )
        outer.addWidget(title)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("ACGT, IUPAC codes…")
        self._input.returnPressed.connect(self._run)
        self._search = QPushButton("Search")
        self._search.clicked.connect(self._run)
        self._clear = QPushButton("Clear")
        self._clear.clicked.connect(self._clear_search)
        row.addWidget(self._input, 1)
        row.addWidget(self._search)
        row.addWidget(self._clear)
        outer.addLayout(row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #a0a0b8; font-size: 11px;")
        outer.addWidget(self._status)

        self._results = QListWidget()
        self._results.setStyleSheet(
            "QListWidget { background: #1a1a26; color: #e0e0e8; "
            "border: 1px solid #3a3a52; }"
        )
        self._results.itemActivated.connect(self._on_activated)
        self._results.itemDoubleClicked.connect(self._on_activated)
        self._results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._results, 1)

    def set_template(self, template: str) -> None:
        self._template = template
        self._input.clear()
        self._results.clear()
        self._status.clear()
        self.matchesUpdated.emit([])

    def _run(self) -> None:
        if not self._template:
            return
        matches: list[SearchMatch] = search_template(self._template, self._input.text())
        self._results.clear()
        if not matches:
            self._status.setText("No matches found")
            self.matchesUpdated.emit([])
            return
        self._status.setText(
            f"{len(matches)} match{'es' if len(matches) != 1 else ''} found "
            "(double-click to jump)"
        )
        for m in matches:
            arrow = "→" if m.direction == "sense" else "←"
            item = QListWidgetItem(f"{arrow}  {m.start + 1} – {m.end}  ({m.direction})")
            item.setData(0x100, m.start)
            self._results.addItem(item)
        self.matchesUpdated.emit(matches)

    def _clear_search(self) -> None:
        self._input.clear()
        self._results.clear()
        self._status.clear()
        self.matchesUpdated.emit([])

    def _on_activated(self, item: QListWidgetItem) -> None:
        pos = item.data(0x100)
        if isinstance(pos, int):
            self.matchActivated.emit(pos)
