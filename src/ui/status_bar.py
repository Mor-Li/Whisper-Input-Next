"""macOS 状态栏控制器，显示 Whisper-Input 的运行状态。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple

from AppKit import NSImageOnly, NSImageScaleProportionallyDown
from Cocoa import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSMakeRect, NSObject, NSUserDefaults
from PyObjCTools import AppHelper

from src.audio.usage_stats import UsageStatsReader, format_chars
from src.keyboard.inputState import InputState
from src.ui.usage_chart import CHART_HEIGHT, CHART_WIDTH, DailyBarChartView

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CACHE_PATH = os.path.join(_REPO_ROOT, "audio_archive", "cache.json")
CHART_DAYS = 30

# 菜单栏图标的固定名字。macOS 按「进程名 + 这个名字」记住图标位置，
# 不设的话默认叫 Item-0，会和别的 python 菜单栏小工具（比如 llm-spend）抢同一条位置记录。
STATUS_ITEM_NAME = "WhisperInputNext"
# 第一次出现时离屏幕右边缘的距离（点）。菜单栏太挤时，新图标默认排在最左边，
# 会被刘海挡住看不见，所以给一个靠右的初始位置。之后按住 Cmd 拖动，系统会记住新位置。
DEFAULT_POSITION_FROM_RIGHT = 360


@dataclass(frozen=True)
class _StateVisual:
    fallback_text: str
    description: str
    env_key: str


_STATE_VISUALS = {
    InputState.IDLE: _StateVisual("🎙️", "空闲", "IDLE"),
    InputState.RECORDING: _StateVisual("🔴", "录音中", "RECORDING"),
    InputState.RECORDING_LOCAL: _StateVisual("🟠", "录音中 (本地 Whisper)", "RECORDING"),
    InputState.DOUBAO_STREAMING: _StateVisual("🟢", "流式识别中 (豆包)", "RECORDING"),
    InputState.PROCESSING: _StateVisual("🔵", "转录处理中", "PROCESSING"),
    InputState.PROCESSING_LOCAL: _StateVisual("🔵", "转录处理中", "PROCESSING"),
    InputState.WARNING: _StateVisual("⚠️", "警告", "PROCESSING"),
    InputState.ERROR: _StateVisual("❗️", "错误", "PROCESSING"),
}


class _MenuDelegate(NSObject):
    """菜单打开前回调，用来现算使用统计。"""

    def menuWillOpen_(self, _menu):  # noqa: N802  NSMenuDelegate
        self.on_open()


class StatusBarController:
    """管理状态栏图标、提示信息和点开后的使用统计菜单。"""

    def __init__(self) -> None:
        self._status_item = None
        self._menu = None
        self._current_state: InputState = InputState.IDLE
        self._queue_length: int = 0

        self._custom_icons: Dict[str, NSImage] = {}
        self._load_custom_icons()

        self._stats_reader = UsageStatsReader(_CACHE_PATH)
        self._stat_items: Dict[str, NSMenuItem] = {}
        self._state_item = None
        self._chart = None
        self._menu_delegate = None

    def start(self) -> None:
        """启动状态栏控件并进入事件循环。"""
        # 必须跑完整的 NSApplication 事件循环。以前用的 runConsoleEventLoop 只转 run loop、
        # 不派发鼠标事件，图标能显示能变色，但点了没有任何反应。
        # Accessory：不在 Dock 里出现，但能弹出菜单栏菜单（Prohibited 弹不出）。
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        AppHelper.callAfter(self._setup)
        AppHelper.runEventLoop(
            installInterrupt=True,             # 在 tmux 里按 Ctrl+C 能正常退出
            unexpectedErrorAlert=lambda: True,  # 回调里出异常只打日志、继续运行，不弹对话框
            main=lambda _argv: app.run(),
        )

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        defaults = NSUserDefaults.standardUserDefaults()
        position_key = f"NSStatusItem Preferred Position {STATUS_ITEM_NAME}"
        if defaults.objectForKey_(position_key) is None:
            defaults.setDouble_forKey_(DEFAULT_POSITION_FROM_RIGHT, position_key)

        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)
        self._status_item.setAutosaveName_(STATUS_ITEM_NAME)
        self._status_item.setVisible_(True)

        button = self._status_item.button()
        if button is not None:
            button.setTitle_("🎙️")
            button.setToolTip_("Whisper-Input - 空闲")

        self._status_item.setMenu_(self._build_menu())
        self._refresh()

    def _info_item(self, title: str = "") -> NSMenuItem:
        """只显示文字的菜单行（没有 action，系统会显示成灰色）"""
        return NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")

    def _build_menu(self) -> NSMenu:
        menu = NSMenu.alloc().init()
        for key in ("today", "week", "month", "total", "since"):
            item = self._info_item()
            self._stat_items[key] = item
            menu.addItem_(item)

        chart_item = self._info_item()
        self._chart = DailyBarChartView.alloc().initWithFrame_(
            NSMakeRect(0, 0, CHART_WIDTH, CHART_HEIGHT)
        )
        chart_item.setView_(self._chart)
        menu.addItem_(chart_item)

        menu.addItem_(NSMenuItem.separatorItem())
        self._state_item = self._info_item()
        menu.addItem_(self._state_item)
        menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出", "terminate:", "q")
        )

        self._menu_delegate = _MenuDelegate.alloc().init()
        self._menu_delegate.on_open = self._refresh_menu
        menu.setDelegate_(self._menu_delegate)
        self._menu = menu
        self._refresh_menu()
        return menu

    def _refresh_menu(self) -> None:
        """菜单打开时现算统计。缓存文件没变就复用上次的结果。"""
        stats = self._stats_reader.read()
        today = date.today()

        count, chars = stats.day(today)
        self._stat_items["today"].setTitle_(f"今天  {count:,} 条 · {format_chars(chars)}")
        count, _ = stats.window(7, today)
        self._stat_items["week"].setTitle_(f"最近 7 天  {count:,} 条")
        count, _ = stats.window(30, today)
        self._stat_items["month"].setTitle_(f"最近 30 天  {count:,} 条")
        self._stat_items["total"].setTitle_(
            f"累计  {stats.total_count:,} 条 · {format_chars(stats.total_chars)}"
        )
        first = stats.first_day
        if first:
            span = (today - first).days + 1
            self._stat_items["since"].setTitle_(
                f"{first.year}/{first.month}/{first.day} 起 {span} 天，其中 {stats.active_days} 天在用"
            )
        else:
            self._stat_items["since"].setTitle_("还没有转录记录")

        self._chart.set_series(stats.series(CHART_DAYS, today) if stats.total_count else [])

        visual = _STATE_VISUALS.get(self._current_state, _STATE_VISUALS[InputState.IDLE])
        state_text = f"状态：{visual.description}"
        if self._queue_length:
            state_text += f" · 待处理 {self._queue_length}"
        self._state_item.setTitle_(state_text)

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

        for env_key in {visual.env_key for visual in _STATE_VISUALS.values()}:
            _try_load(env_key)
