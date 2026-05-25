"""Linux Qt UI backend.

The backend intentionally avoids precise caret tracking. Linux support varies
by display server and application accessibility implementation, so the preview
uses a stable top-center placement.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.keyboard.inputState import InputState

try:
    from src.utils.logger import logger
except Exception:  # noqa: BLE001
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StateVisual:
    color: str
    tooltip: str


_STATE_VISUALS = {
    InputState.IDLE: _StateVisual("#2f8f46", "Whisper-Input - idle"),
    InputState.RECORDING: _StateVisual("#c43131", "Whisper-Input - recording"),
    InputState.RECORDING_TRANSLATE: _StateVisual(
        "#c43131",
        "Whisper-Input - recording translate",
    ),
    InputState.RECORDING_KIMI: _StateVisual(
        "#d97917",
        "Whisper-Input - recording local",
    ),
    InputState.DOUBAO_STREAMING: _StateVisual("#23845d", "Whisper-Input - streaming"),
    InputState.PROCESSING: _StateVisual("#2f6fb4", "Whisper-Input - transcribing"),
    InputState.PROCESSING_KIMI: _StateVisual(
        "#2f6fb4",
        "Whisper-Input - transcribing local",
    ),
    InputState.TRANSLATING: _StateVisual("#b19625", "Whisper-Input - translating"),
    InputState.WARNING: _StateVisual("#b19625", "Whisper-Input - warning"),
    InputState.ERROR: _StateVisual("#b3261e", "Whisper-Input - error"),
}


class _QtRuntime:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = InputState.IDLE
        self._queue_length = 0
        self._error_message: Optional[str] = None
        self._preview_visible = False
        self._preview_text = "Listening..."

        self._qt: Optional[dict[str, Any]] = None
        self._app: Any = None
        self._tray: Any = None
        self._preview: Any = None
        self._timer: Any = None
        self._last_snapshot: Optional[tuple[InputState, int, Optional[str], bool, str]] = None
        self._last_notified_error: Optional[str] = None

    def update_state(self, state: InputState, queue_length: int = 0) -> None:
        with self._lock:
            self._state = state
            self._queue_length = max(0, queue_length)

    def show_error(self, message: str) -> None:
        with self._lock:
            self._state = InputState.ERROR
            self._error_message = message

    def show_preview(self) -> None:
        with self._lock:
            self._preview_visible = True
            self._preview_text = "Listening..."

    def hide_preview(self) -> None:
        with self._lock:
            self._preview_visible = False

    def update_preview_text(self, text: str) -> None:
        with self._lock:
            self._preview_text = text or "Listening..."

    def start(self) -> None:
        if not self._has_display():
            self._block_without_ui("DISPLAY/WAYLAND_DISPLAY is not set")
            return

        qt = self._load_qt()
        if qt is None:
            self._block_without_ui("PyQt5 is not available")
            return

        self._qt = qt
        try:
            self._start_qt(qt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Qt UI failed to start: {exc}")
            self._block_without_ui(str(exc))

    def _start_qt(self, qt: dict[str, Any]) -> None:
        QApplication = qt["QApplication"]
        QSystemTrayIcon = qt["QSystemTrayIcon"]
        QMenu = qt["QMenu"]
        QAction = qt["QAction"]
        QTimer = qt["QTimer"]

        app = QApplication.instance()
        if app is None:
            app = QApplication(["whisper-input-next"])
        app.setQuitOnLastWindowClosed(False)
        self._app = app

        if QSystemTrayIcon.isSystemTrayAvailable():
            menu = QMenu()
            quit_action = QAction("Quit Whisper-Input")
            quit_action.triggered.connect(app.quit)
            menu.addAction(quit_action)

            visual = _STATE_VISUALS[InputState.IDLE]
            self._tray = QSystemTrayIcon(self._make_icon(visual.color, qt))
            self._tray.setContextMenu(menu)
            self._tray.setToolTip(visual.tooltip)
            self._tray.show()
        else:
            logger.warning("System tray is not available in this desktop session.")

        self._timer = QTimer()
        self._timer.timeout.connect(self._apply_snapshot)
        self._timer.start(100)
        self._apply_snapshot()

        logger.info("Qt desktop UI started.")
        app.exec_()

    def _apply_snapshot(self) -> None:
        if self._qt is None:
            return

        with self._lock:
            snapshot = (
                self._state,
                self._queue_length,
                self._error_message,
                self._preview_visible,
                self._preview_text,
            )

        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot

        state, queue_length, error_message, preview_visible, preview_text = snapshot
        self._update_tray(state, queue_length, error_message)
        self._update_preview(preview_visible, preview_text)

    def _update_tray(
        self,
        state: InputState,
        queue_length: int,
        error_message: Optional[str],
    ) -> None:
        if self._tray is None or self._qt is None:
            return

        visual = _STATE_VISUALS.get(state, _STATE_VISUALS[InputState.IDLE])
        tooltip = visual.tooltip
        if queue_length:
            tooltip = f"{tooltip} | queued {queue_length}"
        if error_message:
            tooltip = f"{tooltip} | {error_message}"

        self._tray.setIcon(self._make_icon(visual.color, self._qt))
        self._tray.setToolTip(tooltip)

        if (
            error_message
            and error_message != self._last_notified_error
            and self._qt["QSystemTrayIcon"].supportsMessages()
        ):
            self._tray.showMessage("Whisper-Input", error_message)
            self._last_notified_error = error_message

    def _update_preview(self, visible: bool, text: str) -> None:
        if self._qt is None:
            return

        if self._preview is None:
            self._preview = _PreviewWidget(self._qt)

        if not visible:
            self._preview.hide()
            return

        display_text = text
        if len(display_text) > 100:
            display_text = "..." + display_text[-97:]

        self._preview.set_text(display_text or "Listening...")
        self._preview.show_at_default_position()

    def _make_icon(self, color: str, qt: dict[str, Any]) -> Any:
        Qt = qt["Qt"]
        QColor = qt["QColor"]
        QIcon = qt["QIcon"]
        QPainter = qt["QPainter"]
        QPixmap = qt["QPixmap"]

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(8, 8, 48, 48)
        painter.end()

        return QIcon(pixmap)

    def _load_qt(self) -> Optional[dict[str, Any]]:
        try:
            from PyQt5.QtCore import Qt, QTimer
            from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
            from PyQt5.QtWidgets import (
                QAction,
                QApplication,
                QLabel,
                QMenu,
                QSystemTrayIcon,
                QVBoxLayout,
                QWidget,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PyQt5 desktop UI backend unavailable: {exc}")
            return None

        return {
            "QAction": QAction,
            "QApplication": QApplication,
            "QColor": QColor,
            "QFont": QFont,
            "QIcon": QIcon,
            "QLabel": QLabel,
            "QMenu": QMenu,
            "QPainter": QPainter,
            "QPixmap": QPixmap,
            "QSystemTrayIcon": QSystemTrayIcon,
            "QTimer": QTimer,
            "QVBoxLayout": QVBoxLayout,
            "QWidget": QWidget,
            "Qt": Qt,
        }

    def _has_display(self) -> bool:
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    def _block_without_ui(self, reason: str) -> None:
        logger.warning(f"Desktop UI disabled ({reason}); running without tray or preview.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Exiting.")


class _PreviewWidget:
    def __init__(self, qt: dict[str, Any]) -> None:
        Qt = qt["Qt"]
        QLabel = qt["QLabel"]
        QFont = qt["QFont"]
        QVBoxLayout = qt["QVBoxLayout"]
        QWidget = qt["QWidget"]

        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if hasattr(Qt, "WindowDoesNotAcceptFocus"):
            flags |= Qt.WindowDoesNotAcceptFocus

        self._qt = qt
        self._widget = QWidget(None, flags)
        self._widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._widget.setStyleSheet(
            "QWidget { background: rgba(20, 20, 20, 218); "
            "border-radius: 8px; }"
        )

        self._label = QLabel("Listening...")
        self._label.setWordWrap(True)
        self._label.setFont(QFont("", 12))
        self._label.setStyleSheet("QLabel { color: white; padding: 8px 12px; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._widget.setLayout(layout)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        self._widget.setFixedWidth(420)
        self._widget.adjustSize()

    def show_at_default_position(self) -> None:
        QApplication = self._qt["QApplication"]
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            geometry = screen.availableGeometry()
            size = self._widget.sizeHint()
            x = geometry.x() + max(0, (geometry.width() - size.width()) // 2)
            y = geometry.y() + 72
            self._widget.move(x, y)

        self._widget.show()
        self._widget.raise_()

    def hide(self) -> None:
        self._widget.hide()


_runtime = _QtRuntime()


class StatusBarController:
    """Qt-backed status controller for Linux desktop sessions."""

    def start(self) -> None:
        _runtime.start()

    def update_state(self, state: InputState, *, queue_length: int = 0) -> None:
        _runtime.update_state(state, queue_length)

    def show_error(self, message: str) -> None:
        logger.error(message)
        _runtime.show_error(message)


class FloatingPreviewWindow:
    """Qt-backed floating preview window for Linux desktop sessions."""

    def show(self) -> None:
        _runtime.show_preview()

    def hide(self) -> None:
        _runtime.hide_preview()

    def update_text(self, text: str) -> None:
        _runtime.update_preview_text(text)
