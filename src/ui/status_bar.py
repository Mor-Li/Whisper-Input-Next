"""Platform-selected status controller."""

from __future__ import annotations

import sys

if sys.platform == "darwin":
    from src.ui.status_bar_macos import StatusBarController
elif sys.platform.startswith("linux"):
    from src.ui.qt_backend import StatusBarController
else:
    from src.ui.noop_backend import StatusBarController

__all__ = ["StatusBarController"]
