"""从转录缓存 audio_archive/cache.json 统计使用量，给菜单栏显示。

缓存里每条转录都带时间戳（本机时区），按天汇总条数和字数即可，不另外记账。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Optional, Tuple


@dataclass
class UsageStats:
    daily: Dict[date, Tuple[int, int]] = field(default_factory=dict)  # 某天 -> (条数, 字数)
    total_count: int = 0
    total_chars: int = 0

    @property
    def first_day(self) -> Optional[date]:
        return min(self.daily) if self.daily else None

    @property
    def active_days(self) -> int:
        """有转录记录的天数"""
        return len(self.daily)

    def day(self, d: date) -> Tuple[int, int]:
        return self.daily.get(d, (0, 0))

    def window(self, days: int, today: date) -> Tuple[int, int]:
        """最近 days 天（含今天）的 (条数, 字数)"""
        count = chars = 0
        for i in range(days):
            c, n = self.day(today - timedelta(days=i))
            count += c
            chars += n
        return count, chars

    def series(self, days: int, today: date) -> list[Tuple[date, int]]:
        """最近 days 天每天的条数，从早到晚"""
        start = today - timedelta(days=days - 1)
        return [(start + timedelta(days=i), self.day(start + timedelta(days=i))[0]) for i in range(days)]


def compute_usage_stats(cache: dict) -> UsageStats:
    stats = UsageStats()
    daily: Dict[date, list] = {}
    for entry in cache.values():
        if not isinstance(entry, dict):
            continue
        try:
            d = date.fromisoformat(str(entry.get("timestamp", ""))[:10])
        except ValueError:
            continue
        chars = len(entry.get("transcription") or "")
        bucket = daily.setdefault(d, [0, 0])
        bucket[0] += 1
        bucket[1] += chars
        stats.total_count += 1
        stats.total_chars += chars
    stats.daily = {d: (c, n) for d, (c, n) in daily.items()}
    return stats


class UsageStatsReader:
    """按文件修改时间缓存统计结果，缓存文件没变就不重新解析。"""

    def __init__(self, cache_path: str = os.path.join("audio_archive", "cache.json")):
        self.cache_path = cache_path
        self._mtime: Optional[float] = None
        self._stats = UsageStats()

    def read(self) -> UsageStats:
        try:
            mtime = os.path.getmtime(self.cache_path)
        except OSError:
            return self._stats
        if mtime != self._mtime:
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, ValueError):
                # 读不动就沿用上一次的结果，菜单栏统计不值得为此报错
                return self._stats
            self._stats = compute_usage_stats(cache)
            self._mtime = mtime
        return self._stats


def format_chars(n: int) -> str:
    """字数写成 3,456 字 / 12.3 万字"""
    if n >= 10000:
        return f"{n / 10000:.1f} 万字"
    return f"{n:,} 字"
