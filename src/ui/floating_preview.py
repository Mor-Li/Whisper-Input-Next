"""Platform-selected floating preview window."""

from __future__ import annotations

import sys

if sys.platform == "darwin":
    from src.ui.floating_preview_macos import FloatingPreviewWindow
elif sys.platform.startswith("linux"):
    from src.ui.qt_backend import FloatingPreviewWindow
else:
    from src.ui.noop_backend import FloatingPreviewWindow

__all__ = ["FloatingPreviewWindow"]
