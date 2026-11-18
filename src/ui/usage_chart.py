"""菜单栏下拉菜单里的柱状图：从第一天到今天，每天转录了多少条。

图可以左右滑动，打开时停在最右边的今天。鼠标停在某根柱子上，右上角显示那天的日期和条数。
颜色全部用系统动态色（labelColor / controlAccentColor 等），深浅色模式由 AppKit 自动处理。
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSScrollerStyleOverlay,
    NSScrollView,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSTrackingMouseMoved,
    NSView,
)
from Foundation import NSAttributedString, NSMakePoint, NSMakeRect

CHART_WIDTH = 300.0
CHART_HEIGHT = 124.0
HEADER_HEIGHT = 20.0
SIDE_PADDING = 14.0
DAY_SLOT = 9.0          # 每天占的宽度（点），30 天正好铺满一屏
BAR_RATIO = 0.72        # 柱子占格子宽度的比例
LABEL_HEIGHT = 16.0     # 底部日期标签的高度


def _draw_text(text: str, x: float, y: float, size: float, color, *, align: str = "left") -> None:
    attrs = {
        NSFontAttributeName: NSFont.systemFontOfSize_(size),
        NSForegroundColorAttributeName: color,
    }
    s = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
    width = s.size().width
    if align == "center":
        x -= width / 2
    elif align == "right":
        x -= width
    s.drawAtPoint_(NSMakePoint(x, y))


def _day_label(d: date) -> str:
    return f"{d.month}/{d.day}"


class _BarsView(NSView):
    """滚动区域里的内容：所有天的柱子和底部日期。宽度随天数变化。"""

    def initWithFrame_(self, frame):  # noqa: N802  ObjC 指定初始化器
        self = objc.super(_BarsView, self).initWithFrame_(frame)
        if self is not None:
            self.series = []
            self.peak = 0
            self.hover_index = None
            self.on_hover = None
        return self

    @objc.python_method
    def index_at(self, x: float) -> Optional[int]:
        i = int(x // DAY_SLOT)
        return i if 0 <= i < len(self.series) else None

    def updateTrackingAreas(self):  # noqa: N802
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        options = (NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited
                   | NSTrackingActiveAlways | NSTrackingInVisibleRect)
        self.addTrackingArea_(
            NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), options, self, None)
        )
        objc.super(_BarsView, self).updateTrackingAreas()

    def mouseMoved_(self, event):  # noqa: N802
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        index = self.index_at(point.x)
        if index != self.hover_index:
            self.hover_index = index
            self.setNeedsDisplay_(True)
            if self.on_hover:
                self.on_hover(index)

    def mouseExited_(self, _event):  # noqa: N802
        if self.hover_index is not None:
            self.hover_index = None
            self.setNeedsDisplay_(True)
            if self.on_hover:
                self.on_hover(None)

    def drawRect_(self, _rect):  # noqa: N802  ObjC 绘制回调
        h = self.bounds().size.height
        y0 = LABEL_HEIGHT
        ch = h - LABEL_HEIGHT - 2
        n = len(self.series)
        if n == 0 or self.peak <= 0:
            return

        label = NSColor.secondaryLabelColor()
        faint = NSColor.tertiaryLabelColor()
        accent = NSColor.controlAccentColor()

        base = NSBezierPath.bezierPath()
        base.moveToPoint_(NSMakePoint(0, y0))
        base.lineToPoint_(NSMakePoint(n * DAY_SLOT, y0))
        base.setLineWidth_(0.5)
        faint.setStroke()
        base.stroke()

        bar_w = DAY_SLOT * BAR_RATIO
        for i, (d, count) in enumerate(self.series):
            x = i * DAY_SLOT + (DAY_SLOT - bar_w) / 2
            if count > 0:
                bar_h = max(1.5, count / self.peak * ch)
                if i == self.hover_index or i == n - 1:
                    accent.setFill()
                else:
                    accent.colorWithAlphaComponent_(0.45).setFill()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x, y0, bar_w, bar_h), 1.2, 1.2
                ).fill()

            # 每月 1 号和 15 号标日期，最右边写"今天"，离"今天"太近的不标免得挤在一起
            center = i * DAY_SLOT + DAY_SLOT / 2
            if i == n - 1:
                _draw_text("今天", center + DAY_SLOT / 2, 2.0, 9.0, label, align="right")
            elif d.day in (1, 15) and (n - 1 - i) * DAY_SLOT > 30:
                tick = NSBezierPath.bezierPath()
                tick.moveToPoint_(NSMakePoint(center, y0))
                tick.lineToPoint_(NSMakePoint(center, y0 - 3))
                tick.setLineWidth_(0.5)
                faint.setStroke()
                tick.stroke()
                _draw_text(_day_label(d), center, 2.0, 9.0, label, align="center")


class _HorizontalScrollView(NSScrollView):
    """只横向滚动。鼠标滚轮的上下滚动也换算成左右滚动。"""

    def scrollWheel_(self, event):  # noqa: N802
        dx, dy = event.scrollingDeltaX(), event.scrollingDeltaY()
        if abs(dy) <= abs(dx):
            objc.super(_HorizontalScrollView, self).scrollWheel_(event)
            return
        factor = 1.0 if event.hasPreciseScrollingDeltas() else 10.0
        clip = self.contentView()
        max_x = max(0.0, self.documentView().frame().size.width - clip.bounds().size.width)
        x = min(max(0.0, clip.bounds().origin.x - dy * factor), max_x)
        clip.scrollToPoint_(NSMakePoint(x, 0))
        self.reflectScrolledClipView_(clip)


class DailyBarChartView(NSView):
    """放进菜单项的整块视图：上面一行标题，下面是可横向滚动的柱状图。"""

    def initWithFrame_(self, frame):  # noqa: N802  ObjC 指定初始化器
        self = objc.super(DailyBarChartView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.series = []
        self.hover_text = None

        w = frame.size.width
        scroll_h = frame.size.height - HEADER_HEIGHT
        self.scroll_view = _HorizontalScrollView.alloc().initWithFrame_(
            NSMakeRect(SIDE_PADDING, 0, w - 2 * SIDE_PADDING, scroll_h)
        )
        self.scroll_view.setHasHorizontalScroller_(True)
        self.scroll_view.setHasVerticalScroller_(False)
        self.scroll_view.setAutohidesScrollers_(True)
        self.scroll_view.setScrollerStyle_(NSScrollerStyleOverlay)
        self.scroll_view.setDrawsBackground_(False)

        self.bars = _BarsView.alloc().initWithFrame_(NSMakeRect(0, 0, w - 2 * SIDE_PADDING, scroll_h))
        self.bars.on_hover = self._on_hover
        self.scroll_view.setDocumentView_(self.bars)
        self.addSubview_(self.scroll_view)
        return self

    @objc.python_method
    def set_series(self, series: List[Tuple[date, int]]) -> None:
        """series: [(日期, 条数)]，从第一天到今天。只在主线程调用。每次调用都滚回今天。"""
        self.series = series
        self.hover_text = None
        visible_w = self.scroll_view.contentView().bounds().size.width
        height = self.scroll_view.frame().size.height
        doc_w = max(visible_w, len(series) * DAY_SLOT)
        self.bars.series = series
        self.bars.peak = max((c for _, c in series), default=0)
        self.bars.hover_index = None
        self.bars.setFrame_(NSMakeRect(0, 0, doc_w, height))
        self.bars.setNeedsDisplay_(True)

        clip = self.scroll_view.contentView()
        clip.scrollToPoint_(NSMakePoint(max(0.0, doc_w - visible_w), 0))
        self.scroll_view.reflectScrolledClipView_(clip)
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _on_hover(self, index: Optional[int]) -> None:
        if index is None:
            self.hover_text = None
        else:
            d, count = self.series[index]
            self.hover_text = f"{d.year}/{d.month}/{d.day} · {count} 条"
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):  # noqa: N802  ObjC 绘制回调
        w = self.bounds().size.width
        h = self.bounds().size.height
        label = NSColor.secondaryLabelColor()
        if not self.series or self.bars.peak <= 0:
            _draw_text("暂无转录记录", w / 2, h / 2 - 6, 10.0, label, align="center")
            return
        _draw_text("每天条数 · 左右滑动看历史", SIDE_PADDING, h - 15, 10.0, label)
        right = self.hover_text or f"最多 {self.bars.peak} 条"
        _draw_text(right, w - SIDE_PADDING, h - 15, 10.0, label, align="right")
