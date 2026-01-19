"""浮动预览窗口，显示流式识别中的 pending 文字。"""

from __future__ import annotations

from typing import Optional, Tuple
import traceback

from AppKit import (
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSMakeSize,
    NSPanel,
    NSTextField,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    kAXFocusedUIElementAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    AXValueGetValue,
    kAXValueTypeCGPoint,
    kAXValueTypeCGSize,
)
from Cocoa import (
    NSColor,
    NSScreen,
)
from PyObjCTools import AppHelper


def _get_caret_position() -> Tuple[float, float, float, float]:
    """
    获取当前光标/输入框的位置。

    Returns:
        (x, y, width, height)
        注意：y 坐标是从屏幕底部算起的（macOS 坐标系）

    Raises:
        RuntimeError: 如果无法获取位置
    """
    # 获取当前激活的应用
    workspace = NSWorkspace.sharedWorkspace()
    front_app = workspace.frontmostApplication()
    if front_app is None:
        raise RuntimeError("无法获取当前激活的应用")

    pid = front_app.processIdentifier()
    app_name = front_app.localizedName()
    print(f"[FloatingPreview] 当前应用: {app_name} (pid={pid})")

    # 创建 AXUIElement
    app_element = AXUIElementCreateApplication(pid)
    if app_element is None:
        raise RuntimeError(f"无法为 {app_name} 创建 AXUIElement")

    # 获取焦点元素
    err, focused_element = AXUIElementCopyAttributeValue(
        app_element, kAXFocusedUIElementAttribute, None
    )
    if err != 0:
        raise RuntimeError(f"无法获取焦点元素, error={err}")
    if focused_element is None:
        raise RuntimeError("焦点元素为 None")

    print(f"[FloatingPreview] 焦点元素: {focused_element}")

    # 获取位置
    err, position_value = AXUIElementCopyAttributeValue(
        focused_element, kAXPositionAttribute, None
    )
    if err != 0:
        raise RuntimeError(f"无法获取位置属性, error={err}")
    if position_value is None:
        raise RuntimeError("位置属性为 None")

    # 获取尺寸
    err, size_value = AXUIElementCopyAttributeValue(
        focused_element, kAXSizeAttribute, None
    )
    if err != 0:
        raise RuntimeError(f"无法获取尺寸属性, error={err}")
    if size_value is None:
        raise RuntimeError("尺寸属性为 None")

    # 解析位置（CGPoint）- PyObjC 返回 (success, CGPoint)
    success, point = AXValueGetValue(position_value, kAXValueTypeCGPoint, None)
    if not success:
        raise RuntimeError("无法解析位置值")

    # 解析尺寸（CGSize）
    success, size = AXValueGetValue(size_value, kAXValueTypeCGSize, None)
    if not success:
        raise RuntimeError("无法解析尺寸值")

    print(f"[FloatingPreview] AX坐标: x={point.x}, y={point.y}, w={size.width}, h={size.height}")

    # 将屏幕坐标从左上角原点转换为左下角原点（macOS 窗口坐标系）
    screen = NSScreen.mainScreen()
    screen_height = screen.frame().size.height

    # AX 坐标是从屏幕左上角算起的，需要转换
    y_from_bottom = screen_height - point.y - size.height

    print(f"[FloatingPreview] 转换后: x={point.x}, y={y_from_bottom}")

    return (point.x, y_from_bottom, size.width, size.height)


class FloatingPreviewWindow:
    """浮动预览窗口，用于显示流式识别中未确定的文字。"""

    def __init__(self, max_width: int = 600, font_size: float = 16.0) -> None:
        self._panel: Optional[NSPanel] = None
        self._text_field: Optional[NSTextField] = None
        self._max_width = max_width
        self._font_size = font_size
        self._is_visible = False
        self._follow_caret = True  # 是否跟随光标
        self._padding_h = 12  # 水平内边距
        self._padding_v = 8   # 垂直内边距

    def show(self) -> None:
        """显示浮动窗口"""
        def _show() -> None:
            if self._panel is None:
                self._create_panel()

            # 清空上次的文字
            if self._text_field is not None:
                self._text_field.setStringValue_("正在聆听...")

            # 尝试定位到光标位置
            self._position_near_caret()

            self._panel.orderFront_(None)
            self._is_visible = True

        AppHelper.callAfter(_show)

    def hide(self) -> None:
        """隐藏浮动窗口"""
        def _hide() -> None:
            if self._panel is not None:
                self._panel.orderOut_(None)
            self._is_visible = False

        AppHelper.callAfter(_hide)

    def update_text(self, text: str) -> None:
        """更新显示的文字"""
        def _update() -> None:
            if self._text_field is None:
                return

            # 限制显示长度
            display_text = text
            if len(text) > 100:
                display_text = "..." + text[-97:]

            self._text_field.setStringValue_(display_text if display_text else "正在聆听...")

            # 调整窗口大小
            self._adjust_size()

        AppHelper.callAfter(_update)

    def _position_near_caret(self) -> None:
        """将窗口定位到光标/输入框附近"""
        if self._panel is None:
            return

        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        panel_frame = self._panel.frame()
        panel_height = panel_frame.size.height
        panel_width = panel_frame.size.width

        try:
            caret_x, caret_y, caret_width, caret_height = _get_caret_position()

            # 将窗口放在输入框下方，左对齐
            new_x = caret_x
            new_y = caret_y - panel_height - 5  # 输入框下方 5px

            # 如果下方空间不够，放到上方
            if new_y < 50:
                new_y = caret_y + caret_height + 5

            # 确保不超出屏幕右边界
            if new_x + panel_width > screen_frame.size.width:
                new_x = screen_frame.size.width - panel_width - 10

            # 确保不超出屏幕左边界
            if new_x < 10:
                new_x = 10

        except Exception as e:
            print(f"[FloatingPreview] ❌ 获取光标位置失败: {e}")
            traceback.print_exc()
            # 失败时放在屏幕上方居中
            new_x = (screen_frame.size.width - panel_width) / 2
            new_y = screen_frame.size.height - 150

        self._panel.setFrame_display_(
            NSMakeRect(new_x, new_y, panel_width, panel_height),
            True,
        )

    def _create_panel(self) -> None:
        """创建浮动面板"""
        # 获取屏幕尺寸
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()

        # 初始窗口大小
        width = 300
        height = 50

        # 默认位置：屏幕上方居中（后续会调整到光标位置）
        x = (screen_frame.size.width - width) / 2
        y = screen_frame.size.height - 150

        # 创建无边框浮动面板
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style_mask,
            2,  # NSBackingStoreBuffered
            False,
        )

        # 设置面板属性
        self._panel.setLevel_(NSFloatingWindowLevel)  # 浮动在所有窗口之上
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.1, 0.85))
        self._panel.setHasShadow_(True)
        self._panel.setMovableByWindowBackground_(True)  # 可拖动

        # 创建圆角内容视图
        content_view = self._panel.contentView()
        content_view.setWantsLayer_(True)
        layer = content_view.layer()
        layer.setCornerRadius_(10.0)
        layer.setMasksToBounds_(True)

        # 创建文本标签
        padding_h = 12  # 水平内边距
        padding_v = 8   # 垂直内边距
        self._text_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(padding_h, padding_v, width - padding_h * 2, height - padding_v * 2)
        )
        self._text_field.setStringValue_("正在聆听...")
        self._text_field.setBezeled_(False)
        self._text_field.setDrawsBackground_(False)
        self._text_field.setEditable_(False)
        self._text_field.setSelectable_(False)
        self._text_field.setTextColor_(NSColor.whiteColor())
        self._text_field.setFont_(NSFont.systemFontOfSize_(self._font_size))
        self._text_field.setAlignment_(1)  # NSTextAlignmentCenter

        # 启用自动换行
        self._text_field.cell().setWraps_(True)
        self._text_field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping

        content_view.addSubview_(self._text_field)

        # 保存内边距供后续使用
        self._padding_h = padding_h
        self._padding_v = padding_v

    def _adjust_size(self) -> None:
        """根据文字内容调整窗口大小（保持当前位置）"""
        if self._panel is None or self._text_field is None:
            return

        text = self._text_field.stringValue()
        if not text:
            return

        cell = self._text_field.cell()

        # 先用最大宽度计算文本需要的高度
        max_text_width = self._max_width - self._padding_h * 2
        cell_size_at_max = cell.cellSizeForBounds_(NSMakeRect(0, 0, max_text_width, 10000))

        # 判断是否需要换行（高度超过单行）
        single_line_height = self._font_size + 6
        needs_wrap = cell_size_at_max.height > single_line_height * 1.5

        if needs_wrap:
            # 需要换行：使用最大宽度
            new_width = self._max_width
            text_height = cell_size_at_max.height
        else:
            # 单行：根据内容调整宽度
            # 计算单行文本的实际宽度
            cell_size_single = cell.cellSizeForBounds_(NSMakeRect(0, 0, 10000, single_line_height))
            content_width = cell_size_single.width + self._padding_h * 2 + 10
            new_width = max(min(content_width, self._max_width), 200)
            text_height = single_line_height

        # 窗口高度 = 文本高度 + 上下内边距
        new_height = text_height + self._padding_v * 2
        new_height = max(new_height, 36)  # 最小高度

        # 获取当前位置
        frame = self._panel.frame()

        # 高度变化时，调整 y 坐标使窗口向下扩展（保持顶部位置不变）
        new_y = frame.origin.y + frame.size.height - new_height

        # 更新窗口大小
        self._panel.setFrame_display_(
            NSMakeRect(frame.origin.x, new_y, new_width, new_height),
            True,
        )

        # 更新文本框大小
        self._text_field.setFrame_(
            NSMakeRect(self._padding_h, self._padding_v, new_width - self._padding_h * 2, new_height - self._padding_v * 2)
        )
