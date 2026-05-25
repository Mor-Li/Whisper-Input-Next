"""Fallback UI backend for platforms without an implemented desktop UI."""

from __future__ import annotations

import time

from src.keyboard.inputState import InputState

try:
    from src.utils.logger import logger
except Exception:  # noqa: BLE001
    import logging

    logger = logging.getLogger(__name__)


class StatusBarController:
    """Status controller that keeps the process alive without desktop UI."""

    def __init__(self) -> None:
        self._state = InputState.IDLE
        self._queue_length = 0

    def start(self) -> None:
        logger.warning("Desktop status UI is unavailable; running without tray UI.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Exiting.")

    def update_state(self, state: InputState, *, queue_length: int = 0) -> None:
        self._state = state
        self._queue_length = max(0, queue_length)

    def show_error(self, message: str) -> None:
        self._state = InputState.ERROR
        logger.error(message)


class FloatingPreviewWindow:
    """No-op floating preview used when no desktop UI backend is available."""

    def show(self) -> None:
        return

    def hide(self) -> None:
        return

    def update_text(self, text: str) -> None:
        return
