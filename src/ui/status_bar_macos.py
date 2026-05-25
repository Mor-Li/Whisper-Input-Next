"""macOS 状态栏控制器，显示 Whisper-Input 的运行状态。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from AppKit import NSImageOnly, NSImageScaleProportionallyDown
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
    InputState.RECORDING_TRANSLATE: _StateVisual("🔴", "录音中 (翻译)", "RECORDING"),
    InputState.RECORDING_KIMI: _StateVisual("🟠", "录音中 (本地 Whisper)", "RECORDING"),
    InputState.DOUBAO_STREAMING: _StateVisual("🟢", "流式识别中 (豆包)", "RECORDING"),
    InputState.PROCESSING: _StateVisual("🔵", "转录处理中", "PROCESSING"),
    InputState.PROCESSING_KIMI: _StateVisual("🔵", "转录处理中", "PROCESSING"),
    InputState.TRANSLATING: _StateVisual("🟡", "翻译中", "PROCESSING"),
    InputState.WARNING: _StateVisual("⚠️", "警告", "PROCESSING"),
    InputState.ERROR: _StateVisual("❗️", "错误", "PROCESSING"),
}


class StatusBarController:
    """管理状态栏图标和提示信息。"""

    def __init__(self) -> None:
        self._status_item = None
        self._menu = None
        self._current_state: InputState = InputState.IDLE
        self._queue_length: int = 0

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
    ) -> None:
        """更新状态显示"""

        queue_length = max(0, queue_length)

        def _apply() -> None:
            self._current_state = state
            self._queue_length = queue_length
            self._refresh()

        AppHelper.callAfter(_apply)

    def show_error(self, message: str) -> None:
        """显示错误状态。"""
        self.update_state(InputState.ERROR)

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
            image.setSize_((18.0, 18.0))
            button.setImage_(image)
            button.setTitle_(title)
            button.setImageScaling_(NSImageScaleProportionallyDown)
            button.setImagePosition_(NSImageOnly)
        else:
            button.setImage_(None)
            button.setTitle_(title)
            button.setImagePosition_(0)

        button.setToolTip_(tooltip)

    def _icon_and_tooltip(self) -> Tuple[str, Optional[NSImage], str]:
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
        template_flag = os.getenv("STATUS_ICON_TEMPLATE", "false").lower() == "true"

        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icons")
        )

        def _resolve_path(env_key: str) -> Optional[str]:
            env_path = os.getenv(f"STATUS_ICON_{env_key}")
            if env_path:
                return env_path
            default_name = {
                "IDLE": "idle.png",
                "RECORDING": "recording.png",
                "PROCESSING": "transcripting.png",
            }.get(env_key)
            if not default_name:
                return None
            return os.path.join(base_dir, default_name)

        def _try_load(env_key: str) -> None:
            path = _resolve_path(env_key)
            if not path or not os.path.exists(path):
                return
            image = NSImage.alloc().initWithContentsOfFile_(path)
            if image is None:
                print(f"[StatusBar] 图标加载失败: {path}")
                return
            image.setTemplate_(template_flag)
            self._custom_icons[env_key] = image
            print(f"[StatusBar] 已加载图标: {env_key} <- {path}")

        for visual in _STATE_VISUALS.values():
            _try_load(visual.env_key)
