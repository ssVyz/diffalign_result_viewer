"""QThread wrapper that runs the streaming JSON loader off the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..loader import LoadCancelled, load_results
from ..models import ScreeningResults


class LoaderWorker(QObject):
    progress = Signal(int, int, str)  # current_bytes, total_bytes, message
    finished = Signal(object)  # ScreeningResults
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = load_results(
                self._path,
                progress_cb=self._on_progress,
                cancel_cb=lambda: self._cancel,
            )
            self.finished.emit(results)
        except LoadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 — surface anything to the UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)


class LoaderController(QObject):
    """Manages a LoaderWorker on its own QThread."""

    progress = Signal(int, int, str)
    finished = Signal(object)  # ScreeningResults
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: LoaderWorker | None = None

    def start(self, path: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        thread = QThread(self)
        worker = LoaderWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        self._thread = thread
        self._worker = worker
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()

    def _on_finished(self, results: ScreeningResults) -> None:
        self._cleanup()
        self.finished.emit(results)

    def _on_failed(self, message: str) -> None:
        self._cleanup()
        self.failed.emit(message)

    def _on_cancelled(self) -> None:
        self._cleanup()
        self.cancelled.emit()

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
