"""Main window — assembles the heatmap, detail panel, controls and status bar."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..loader import recompute_variants_for_threshold
from ..models import ScreeningResults
from .controls import ParamsPanel, ViewControls
from .detail import DetailPanel
from .heatmap import HeatmapView, HeatmapWidget
from .legend import LegendWidget
from .loader_worker import LoaderController
from .search import SearchPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("diffalign result viewer")
        self.resize(1400, 860)

        self._results: ScreeningResults | None = None
        self._current_path: str | None = None
        self._loader = LoaderController(self)
        self._settings = QSettings("diffalign", "result-viewer")

        self._build_ui()
        self._connect_signals()
        self._update_actions()

        # Restore window geometry
        geom = self._settings.value("window/geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self._settings.value("window/state")
        if state:
            self.restoreState(state)

    # ────────────────────────────────────────────────────────
    # UI construction
    # ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Toolbar
        self._toolbar = QToolBar("Main")
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)

        self._action_open = QAction("Open…", self)
        self._action_open.setShortcut(QKeySequence.StandardKey.Open)
        self._action_close = QAction("Close file", self)
        self._action_close.setShortcut(QKeySequence("Ctrl+W"))
        self._action_quit = QAction("Quit", self)
        self._action_quit.setShortcut(QKeySequence.StandardKey.Quit)

        self._toolbar.addAction(self._action_open)
        self._toolbar.addAction(self._action_close)
        self._toolbar.addSeparator()

        self._cancel_button = QPushButton("Cancel load")
        self._cancel_button.setVisible(False)
        self._toolbar.addWidget(self._cancel_button)

        # Menus
        menu_file = self.menuBar().addMenu("&File")
        menu_file.addAction(self._action_open)
        self._recent_menu = menu_file.addMenu("Open &recent")
        menu_file.addAction(self._action_close)
        menu_file.addSeparator()
        menu_file.addAction(self._action_quit)

        menu_view = self.menuBar().addMenu("&View")
        # Dock toggle actions are appended later

        # Central widget — heatmap + legend
        central = QWidget()
        c_layout = QVBoxLayout(central)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        self._legend = LegendWidget()
        c_layout.addWidget(self._legend)

        self._heatmap = HeatmapWidget()
        c_layout.addWidget(self._heatmap, 1)

        self.setCentralWidget(central)

        # Right dock — details
        self._detail = DetailPanel()
        right_dock = QDockWidget("Details", self)
        right_dock.setObjectName("detailDock")
        right_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        right_dock.setWidget(self._detail)
        right_dock.setMinimumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)
        menu_view.addAction(right_dock.toggleViewAction())

        # Left dock — controls + params + search
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._controls = ViewControls()
        self._params = ParamsPanel()
        self._search = SearchPanel()

        # Stack with splitter so user can reshape the side panel.
        side_splitter = QSplitter(Qt.Orientation.Vertical)
        side_splitter.addWidget(self._params)
        side_splitter.addWidget(self._controls)
        side_splitter.addWidget(self._search)
        side_splitter.setStretchFactor(0, 0)
        side_splitter.setStretchFactor(1, 0)
        side_splitter.setStretchFactor(2, 1)
        left_layout.addWidget(side_splitter)

        left_dock = QDockWidget("Controls", self)
        left_dock.setObjectName("controlsDock")
        left_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        left_dock.setWidget(left_panel)
        left_dock.setMinimumWidth(320)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)
        menu_view.addAction(left_dock.toggleViewAction())

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_label = QLabel("Ready")
        self._file_label = QLabel("")
        self._file_label.setStyleSheet("color: #a0a0b8;")
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setVisible(False)
        sb.addWidget(self._status_label, 1)
        sb.addPermanentWidget(self._progress_bar)
        sb.addPermanentWidget(self._file_label)

        self._refresh_recent_menu()

    def _connect_signals(self) -> None:
        self._action_open.triggered.connect(self._open_file_dialog)
        self._action_close.triggered.connect(self._close_file)
        self._action_quit.triggered.connect(self.close)
        self._cancel_button.clicked.connect(self._cancel_load)

        self._loader.progress.connect(self._on_load_progress)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.failed.connect(self._on_load_failed)
        self._loader.cancelled.connect(self._on_load_cancelled)

        self._controls.viewChanged.connect(self._refresh_view)
        self._controls.zoomChanged.connect(self._on_zoom_changed)
        self._controls.differentialToggled.connect(self._refresh_view)
        self._controls.coverageThresholdChanged.connect(self._on_coverage_changed)

        self._heatmap.cellClicked.connect(self._detail.show_detail)
        # Hover does not update the detail panel (it would thrash large
        # variant lists); the heatmap shows a tooltip with the summary instead.

        self._search.matchesUpdated.connect(self._heatmap.set_search_matches)
        self._search.matchActivated.connect(self._heatmap.jump_to_position)

    def _update_actions(self) -> None:
        has_results = self._results is not None
        self._action_close.setEnabled(has_results)

    # ────────────────────────────────────────────────────────
    # File loading
    # ────────────────────────────────────────────────────────

    def _open_file_dialog(self) -> None:
        last_dir = self._settings.value("paths/last_open", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open diffalign result file",
            str(last_dir),
            "JSON results (*.json);;All files (*)",
        )
        if not path:
            return
        self.load_file(path)

    def load_file(self, path: str) -> None:
        if not os.path.exists(path):
            QMessageBox.warning(self, "File not found", f"Could not find:\n{path}")
            return

        self._settings.setValue("paths/last_open", str(Path(path).parent))
        self._add_to_recent(path)

        self._cancel_button.setVisible(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        self._status_label.setText(f"Loading {os.path.basename(path)}…")
        self._action_open.setEnabled(False)
        self._loader.start(path)
        self._current_path = path

    def _cancel_load(self) -> None:
        self._loader.cancel()
        self._status_label.setText("Cancelling…")

    def _on_load_progress(self, current: int, total: int, message: str) -> None:
        # QProgressBar takes a 32-bit signed int; for >2 GiB files we scale
        # to 0–10000 ticks so the bar still tracks accurately.
        if total > 0:
            ticks = 10_000
            self._progress_bar.setRange(0, ticks)
            self._progress_bar.setValue(min(ticks, int(current * ticks / total)))
        else:
            self._progress_bar.setRange(0, 0)
        if message:
            self._status_label.setText(message)

    def _on_load_finished(self, results: ScreeningResults) -> None:
        self._cancel_button.setVisible(False)
        self._progress_bar.setVisible(False)
        self._action_open.setEnabled(True)
        self._set_results(results)
        self._status_label.setText("Loaded")

    def _on_load_failed(self, message: str) -> None:
        self._cancel_button.setVisible(False)
        self._progress_bar.setVisible(False)
        self._action_open.setEnabled(True)
        self._status_label.setText("Load failed")
        QMessageBox.critical(self, "Load failed", message)

    def _on_load_cancelled(self) -> None:
        self._cancel_button.setVisible(False)
        self._progress_bar.setVisible(False)
        self._action_open.setEnabled(True)
        self._status_label.setText("Load cancelled")
        self._current_path = None

    def _close_file(self) -> None:
        self._set_results(None)
        self._current_path = None
        self._status_label.setText("File closed")

    # ────────────────────────────────────────────────────────
    # Apply results
    # ────────────────────────────────────────────────────────

    def _set_results(self, results: ScreeningResults | None) -> None:
        self._results = results
        self._params.set_results(results)
        self._heatmap.set_results(results)
        self._search.set_template(results.template_sequence if results else "")
        self._detail.reset()

        if results is None:
            self._file_label.setText("")
            self._update_actions()
            self._refresh_view()
            return

        self._detail.set_context(results.params, results.template_sequence)
        self._controls.apply_results(results)

        # Coverage threshold spin defaults to file value, recompute summary so
        # the heatmap reflects whatever the user later changes.
        for grid in results.grids:
            recompute_variants_for_threshold(grid, self._controls.coverage_threshold())

        n_pos = len(results.grids[0].positions) if results.grids else 0
        self._file_label.setText(
            f"{os.path.basename(self._current_path or '')}  ·  "
            f"{results.template_length:,} bp  ·  "
            f"{len(results.grids)} lengths  ·  "
            f"{n_pos:,} positions × length"
        )
        self.setWindowTitle(
            f"diffalign result viewer — {os.path.basename(self._current_path or '')}"
        )

        self._update_actions()
        self._refresh_view()

    # ────────────────────────────────────────────────────────
    # View updates
    # ────────────────────────────────────────────────────────

    def _on_coverage_changed(self, threshold: float) -> None:
        if self._results is None:
            return
        for grid in self._results.grids:
            recompute_variants_for_threshold(grid, threshold)
        # Refresh detail panel if visible
        self._heatmap.viewport().update()

    def _on_zoom_changed(self, factor: float) -> None:
        view = self._make_view()
        view.zoom_level = factor
        self._heatmap.set_view(view)

    def _make_view(self) -> HeatmapView:
        return HeatmapView(
            zoom_level=self._controls.zoom(),
            color_green_at=self._controls.green_at(),
            color_red_at=self._controls.red_at(),
            nomatch_ok_pct=self._controls.nomatch_ok(),
            nomatch_bad_pct=self._controls.nomatch_bad(),
            differential_mode=self._controls.differential(),
            diff_green_at=self._controls.diff_green(),
            diff_red_at=self._controls.diff_red(),
            diff_ignore_count=self._controls.diff_ignore(),
        )

    def _refresh_view(self) -> None:
        view = self._make_view()
        self._heatmap.set_view(view)
        self._legend.set_state(view.color_green_at, view.color_red_at, view.differential_mode)

    # ────────────────────────────────────────────────────────
    # Recent files
    # ────────────────────────────────────────────────────────

    def _add_to_recent(self, path: str) -> None:
        items: list[str] = list(self._settings.value("recent_files", []) or [])
        if path in items:
            items.remove(path)
        items.insert(0, path)
        items = items[:8]
        self._settings.setValue("recent_files", items)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        items: list[str] = list(self._settings.value("recent_files", []) or [])
        if not items:
            no_recent = QAction("(no recent files)", self)
            no_recent.setEnabled(False)
            self._recent_menu.addAction(no_recent)
            return
        for path in items:
            act = QAction(path, self)
            act.triggered.connect(lambda _checked=False, p=path: self.load_file(p))
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear = QAction("Clear list", self)
        clear.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear)

    def _clear_recent(self) -> None:
        self._settings.remove("recent_files")
        self._refresh_recent_menu()

    # ────────────────────────────────────────────────────────
    # Window persistence
    # ────────────────────────────────────────────────────────

    def closeEvent(self, event):  # type: ignore[override]
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        super().closeEvent(event)
