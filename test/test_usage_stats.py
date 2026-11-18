"""菜单栏使用统计的单元测试，只用临时文件，不碰真实缓存。"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.audio.usage_stats import UsageStatsReader, compute_usage_stats, format_chars  # noqa: E402


def entry(ts, text):
    return {"transcription": text, "service": "doubao", "model": "bigmodel", "timestamp": ts}


class UsageStatsTests(unittest.TestCase):
    def setUp(self):
        self.cache = {
            "a.wav": entry("2026-11-17T09:00:00", "你好"),
            "b.wav": entry("2026-11-19T01:00:00.123456", "今天第一条"),
            "c.wav": entry("2026-11-19T23:59:59", "abc"),
            "bad_ts.wav": entry("not-a-date", "跳过"),
            "not_dict.wav": "跳过",
        }
        self.today = date(2026, 11, 19)

    def test_daily_counts_and_chars(self):
        stats = compute_usage_stats(self.cache)
        self.assertEqual(stats.day(self.today), (2, 8))
        self.assertEqual(stats.day(date(2026, 11, 18)), (0, 0))
        self.assertEqual(stats.total_count, 3)
        self.assertEqual(stats.total_chars, 10)
        self.assertEqual(stats.first_day, date(2026, 11, 17))
        self.assertEqual(stats.active_days, 2)

    def test_window_and_series(self):
        stats = compute_usage_stats(self.cache)
        self.assertEqual(stats.window(1, self.today), (2, 8))
        self.assertEqual(stats.window(3, self.today), (3, 10))
        series = stats.series(3, self.today)
        self.assertEqual(series, [(date(2026, 11, 17), 1), (date(2026, 11, 18), 0), (self.today, 2)])

    def test_reader_reparses_only_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cache.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
            reader = UsageStatsReader(path)
            self.assertEqual(reader.read().total_count, 3)

            self.cache["d.wav"] = entry("2026-11-19T10:00:00", "新的一条")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
            os.utime(path, (1, 1))  # 强制 mtime 变化
            self.assertEqual(reader.read().total_count, 4)

            with open(path, "w", encoding="utf-8") as f:
                f.write("{坏掉的 json")
            os.utime(path, (2, 2))
            self.assertEqual(reader.read().total_count, 4, "读不动时沿用上一次结果")

    def test_missing_file_gives_empty_stats(self):
        reader = UsageStatsReader("/nonexistent/cache.json")
        self.assertEqual(reader.read().total_count, 0)

    def test_format_chars(self):
        self.assertEqual(format_chars(999), "999 字")
        self.assertEqual(format_chars(12345), "1.2 万字")
        self.assertEqual(format_chars(2503955), "250.4 万字")


if __name__ == "__main__":
    unittest.main()
