"""菜单栏下拉菜单里的小柱状图：最近 N 天每天转录了多少条。

颜色全部用系统动态色（labelColor / controlAccentColor 等），深浅色模式由 AppKit 自动处理。
"""

from __future__ import annotations

from datetime import date
from typing import List, Tuple

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSView,
)
from Foundation import NSAttributedString, NSMakePoint, NSMakeRect

CHART_WIDTH = 300.0
CHART_HEIGHT = 118.0


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


class DailyBarChartView(NSView):
    def initWithFrame_(self, frame):  # noqa: N802  ObjC 指定初始化器
        self = objc.super(DailyBarChartView, self).initWithFrame_(frame)
        if self is not None:
            self.series = []
        return self

    @objc.python_method
    def set_series(self, series: List[Tuple[date, int]]) -> None:
        """series: [(日期, 条数)]，从早到晚，最后一个是今天。只在主线程调用。"""
        self.series = series
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):  # noqa: N802  ObjC 绘制回调
        w = self.bounds().size.width
        h = self.bounds().size.height
        pad_l, pad_r, pad_t, pad_b = 14.0, 14.0, 20.0, 18.0
        x0, y0 = pad_l, pad_b
        cw, ch = w - pad_l - pad_r, h - pad_t - pad_b

        label = NSColor.secondaryLabelColor()
        faint = NSColor.tertiaryLabelColor()
        accent = NSColor.controlAccentColor()

        series = self.series
        if not series:
            _draw_text("暂无转录记录", x0 + cw / 2, y0 + ch / 2 - 6, 10.0, label, align="center")
            return

        peak = max(c for _, c in series)
        _draw_text(f"最近 {len(series)} 天每天条数", x0, h - 15, 10.0, label)
        _draw_text(f"最多 {peak} 条", x0 + cw, h - 15, 10.0, label, align="right")

        # 底线
        base = NSBezierPath.bezierPath()
        base.moveToPoint_(NSMakePoint(x0, y0))
        base.lineToPoint_(NSMakePoint(x0 + cw, y0))
        base.setLineWidth_(0.5)
        faint.setStroke()
        base.stroke()

        n = len(series)
        slot = cw / n
        bar_w = max(1.0, slot * 0.72)
        for i, (_, count) in enumerate(series):
            if count <= 0 or peak <= 0:
                continue
            bar_h = max(1.5, count / peak * ch)
            x = x0 + i * slot + (slot - bar_w) / 2
            is_today = i == n - 1
            (accent if is_today else accent.colorWithAlphaComponent_(0.45)).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y0, bar_w, bar_h), 1.2, 1.2
            ).fill()

        # 底部日期：最早一天、中间一天、今天
        def day_label(d: date) -> str:
            return f"{d.month}/{d.day}"

        _draw_text(day_label(series[0][0]), x0, 2.0, 9.0, label)
        mid = n // 2
        _draw_text(day_label(series[mid][0]), x0 + (mid + 0.5) * slot, 2.0, 9.0, label, align="center")
        _draw_text("今天", x0 + cw, 2.0, 9.0, label, align="right")
