"""macOS 状态栏控制器，显示 Whisper-Input 的运行状态。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from Cocoa import (
    NSApplication,
    NSApplicationActivationPolicyProhibited,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from PyObjCTools import AppHelper

from src.keyboard.inputState import InputState


@dataclass(frozen=True)
class _StateVisual:
    fallback_text: str
    description: str
    env_key: str


_STATE_VISUALS = {
    InputState.IDLE: _StateVisual("🎙️", "空闲", "IDLE"),
    InputState.RECORDING: _StateVisual("🔴", "录音中 (OpenAI)", "RECORDING"),
    InputState.RECORDING_TRANSLATE: _StateVisual("🔴", "录音中 (翻译)", "RECORDING_TRANSLATE"),
    InputState.RECORDING_KIMI: _StateVisual("🟠", "录音中 (本地 Whisper)", "RECORDING_KIMI"),
    InputState.PROCESSING: _StateVisual("🔵", "转录中 (OpenAI)", "PROCESSING"),
    InputState.PROCESSING_KIMI: _StateVisual("🔵", "转录中 (本地 Whisper)", "PROCESSING_KIMI"),
    InputState.TRANSLATING: _StateVisual("🟡", "翻译中", "TRANSLATING"),
    InputState.WARNING: _StateVisual("⚠️", "警告", "WARNING"),
    InputState.ERROR: _StateVisual("❗️", "错误", "ERROR"),
}

_RETRY_VISUAL = _StateVisual("🔁", "等待重试，请按 Ctrl+F 继续", "RETRY")


class StatusBarController:
    """管理状态栏图标和提示信息。"""

    def __init__(self) -> None:
        self._status_item = None
        self._menu = None
        self._current_state: InputState = InputState.IDLE
        self._queue_length: int = 0
        self._awaiting_retry: bool = False

        self._custom_icons: Dict[str, NSImage] = {}
        self._load_custom_icons()

    def start(self) -> None:
        """启动状态栏控件并进入事件循环。"""
        AppHelper.callAfter(self._setup)
        AppHelper.runConsoleEventLoop()

    def update_state(
        self,
        state: InputState,
        *,
        queue_length: int = 0,
        awaiting_retry: bool = False,
    ) -> None:
        """更新状态显示"""

        queue_length = max(0, queue_length)

        def _apply() -> None:
            self._current_state = state
            self._queue_length = queue_length
            self._awaiting_retry = awaiting_retry
            self._refresh()

        AppHelper.callAfter(_apply)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)

        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)

        button = self._status_item.button()
        if button is not None:
            button.setTitle_("🎙️")
            button.setToolTip_("Whisper-Input - 空闲")

        self._menu = NSMenu.alloc().init()
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Whisper-Input", "terminate:", ""
        )
        self._menu.addItem_(quit_item)
        self._status_item.setMenu_(self._menu)

        self._refresh()

    def _refresh(self) -> None:
        if self._status_item is None:
            return
        button = self._status_item.button()
        if button is None:
            return

        title, image, tooltip = self._icon_and_tooltip()

        if image is not None:
            button.setImage_(image)
            button.setTitle_(title)
        else:
            button.setImage_(None)
            button.setTitle_(title)

        button.setToolTip_(tooltip)

    def _icon_and_tooltip(self) -> Tuple[str, Optional[NSImage], str]:
        if self._awaiting_retry:
            visual = _RETRY_VISUAL
        else:
            visual = _STATE_VISUALS.get(self._current_state, _STATE_VISUALS[InputState.IDLE])

        image = self._custom_icons.get(visual.env_key)
        title = ""

        if image is None:
            title = visual.fallback_text
            if self._queue_length:
                title = f"{title}{self._queue_length}" if self._queue_length < 10 else f"{title}*"
        elif self._queue_length:
            # 使用自定义图片时将排队数量显示为文字
            title = f" {self._queue_length if self._queue_length < 10 else '*'}"

        tooltip = f"Whisper-Input - {visual.description}"
        if self._queue_length:
            tooltip += f" | 待处理任务 {self._queue_length}"

        return title, image, tooltip

    def _load_custom_icons(self) -> None:
        template_flag = os.getenv("STATUS_ICON_TEMPLATE", "true").lower() == "true"

        def _try_load(env_key: str) -> None:
            path = os.getenv(f"STATUS_ICON_{env_key}")
            if not path:
                return
            image = NSImage.alloc().initWithContentsOfFile_(path)
            if image is None:
                return
            image.setTemplate_(template_flag)
            self._custom_icons[env_key] = image

        for visual in list(_STATE_VISUALS.values()) + [_RETRY_VISUAL]:
            _try_load(visual.env_key)
