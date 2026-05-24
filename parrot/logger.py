"""
parrot/logger.py — JSONL 会话日志

每个 session 一个文件 parrot/logs/session_YYYYMMDD-HHMMSS.jsonl，
每行一条 event。line-buffered 写，崩溃也不丢前面的内容。

用法:
    with SessionLogger() as logger:
        logger.log("session_start", tmux_session="tiktok-drama")
        logger.log("user_speech", transcript="...")
        logger.log("tool_call", name="tmux_capture_pane", args={...})
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class SessionLogger:
    def __init__(self, base_dir: str | Path = "parrot/logs") -> None:
        base = Path(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = base / f"session_{ts}.jsonl"
        self.file = open(self.path, "w", encoding="utf-8", buffering=1)

    def log(self, event_type: str, **payload: Any) -> None:
        event = {"ts": _utc_iso(), "type": event_type, **payload}
        self.file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if not self.file.closed:
            self.file.close()

    def __enter__(self) -> SessionLogger:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
