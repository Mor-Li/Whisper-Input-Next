#!/usr/bin/env python3
"""
豆包流式 ASR 带时间戳转录脚本。

跟 transcribe_audio_doubao.py 同源（同一个 DoubaoStreamingProcessor），区别是
monkey-patch `_extract_text_from_response` 把每条 utterance 的原始
start_time / end_time / words[] 都保留，输出 JSON 而非纯文本。

豆包协议层已开 `show_utterances: True`，本来就回吐时间戳，只是默认 wrapper
（StreamingResult 只暴露 definite_text / pending_text）把这层信息丢了。

用法:
  python test/transcribe_audio_doubao_timestamped.py <audio> -o transcript.json
  python test/transcribe_audio_doubao_timestamped.py movie.mp4 -o /tmp/out.json --speed 20

输出 JSON 结构:
  {
    "transcript": "...全文...",
    "duration_ms": 42433,
    "utterances": [
      {
        "text": "大家好，我是...",
        "start_ms": 2050,
        "end_ms": 14270,
        "definite": true,
        "words": [{"w": "大", "s_ms": 7490, "e_ms": 7690}, ...]
      },
      ...
    ],
    "errors": []
  }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.transcription.doubao_streaming import (  # noqa: E402
    DEFAULT_SAMPLE_RATE,
    SEGMENT_DURATION_MS,
    DoubaoStreamingProcessor,
)

BYTES_PER_SAMPLE = 2
CHANNELS = 1

# 按 utterance start_time 索引最新版本（豆包流式同句会反复刷直到 definite）
UTTS_BY_START: dict[int, dict] = {}


def patch_doubao_extractor() -> None:
    """拦截响应解析，把 utterances 原始 dict（含时间戳）留下来。"""
    original = DoubaoStreamingProcessor._extract_text_from_response

    def patched(self, data: dict):
        if "result" in data:
            for utt in data["result"].get("utterances", []) or []:
                start = utt.get("start_time")
                if start is None:
                    continue
                prev = UTTS_BY_START.get(start)
                # definite 版本永远胜过 pending 版本
                if prev is None or (utt.get("definite") and not prev.get("definite")):
                    UTTS_BY_START[start] = {
                        "text": utt.get("text", ""),
                        "start_ms": utt.get("start_time"),
                        "end_ms": utt.get("end_time"),
                        "definite": utt.get("definite", False),
                        "words": [
                            {
                                "w": w.get("text", ""),
                                "s_ms": w.get("start_time"),
                                "e_ms": w.get("end_time"),
                            }
                            for w in (utt.get("words") or [])
                        ],
                    }
        return original(self, data)

    DoubaoStreamingProcessor._extract_text_from_response = patched


def load_environment() -> None:
    """跟 transcribe_audio_doubao.py 一样：先 .env，缺失就 fallback zshrc。"""
    load_dotenv(ROOT_DIR / ".env")
    missing = [k for k in ("DOUBAO_APP_KEY", "DOUBAO_ACCESS_KEY") if not os.getenv(k)]
    if not missing:
        return
    command = (
        "source ~/.zshrc >/dev/null 2>&1; "
        "printf '%s\\n' "
        "\"DOUBAO_APP_KEY=$DOUBAO_APP_KEY\" "
        "\"DOUBAO_ACCESS_KEY=$DOUBAO_ACCESS_KEY\""
    )
    result = subprocess.run(["zsh", "-c", command], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        k, sep, v = line.partition("=")
        if sep and k in missing and v:
            os.environ[k] = v


def get_audio_duration_ms(audio_path: Path) -> int | None:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(audio_path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return int(float(result.stdout.strip()) * 1000)
    except ValueError:
        return None


async def pcm_chunk_generator(audio_path: Path, chunk_ms: int, speed: float):
    chunk_size = int(DEFAULT_SAMPLE_RATE * chunk_ms / 1000) * BYTES_PER_SAMPLE * CHANNELS
    if chunk_size <= 0:
        raise ValueError("--chunk-ms must be positive")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(audio_path),
        "-vn", "-ac", str(CHANNELS), "-ar", str(DEFAULT_SAMPLE_RATE),
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        while True:
            chunk = await process.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
            if speed > 0:
                await asyncio.sleep((chunk_ms / 1000) / speed)
    finally:
        stderr = b""
        if process.stderr is not None:
            stderr = await process.stderr.read()
        rc = await process.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed ({rc}): {stderr.decode('utf-8', errors='ignore').strip()}")


async def transcribe_with_timestamps(audio_path: Path, chunk_ms: int, speed: float) -> dict:
    processor = DoubaoStreamingProcessor()
    if not processor.is_available():
        raise RuntimeError("DOUBAO_APP_KEY / DOUBAO_ACCESS_KEY 未配置")

    latest_preview = ""
    final_text = ""
    errors: list[str] = []

    def on_preview_text(t: str):
        nonlocal latest_preview
        latest_preview = t
        print(f"\rPreview chars: {len(t)}", end="", flush=True)

    def on_final_text(t: str):
        nonlocal final_text
        final_text = t

    def on_complete():
        print("\nDoubao transcription completed")

    def on_error(e: str):
        errors.append(e)
        print(f"\nDoubao error: {e}", flush=True)

    await processor.process_audio_stream(
        pcm_chunk_generator(audio_path, chunk_ms, speed),
        on_preview_text, on_final_text, on_complete, on_error,
        sample_rate=DEFAULT_SAMPLE_RATE,
    )

    transcript = (final_text or latest_preview).strip()
    if not transcript:
        raise RuntimeError(f"Doubao 没返回文本: {'; '.join(errors) or 'no text'}")

    utterances = sorted(UTTS_BY_START.values(), key=lambda u: u["start_ms"])
    return {
        "transcript": transcript,
        "duration_ms": get_audio_duration_ms(audio_path),
        "utterances": utterances,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="豆包流式 ASR 带时间戳转录")
    parser.add_argument("audio_path", help="音频/视频文件路径（ffmpeg 能解的都行）")
    parser.add_argument("-o", "--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--chunk-ms", type=int, default=SEGMENT_DURATION_MS,
                        help=f"PCM chunk 大小 ms（默认 {SEGMENT_DURATION_MS}）")
    parser.add_argument("--speed", type=float, default=20.0,
                        help="发送速度倍率（默认 20x realtime）")
    parser.add_argument("--realtime", action="store_true", help="等同 --speed 1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()
    patch_doubao_extractor()

    audio_path = Path(args.audio_path).expanduser().resolve()
    if not audio_path.exists():
        print(f"File not found: {audio_path}", file=sys.stderr)
        return 1

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    speed = 1.0 if args.realtime else args.speed
    print(f"Input:    {audio_path}")
    print(f"Output:   {out_path}")
    print(f"Speed:    {'unpaced' if speed == 0 else f'{speed:g}x realtime'}")

    result = asyncio.run(transcribe_with_timestamps(audio_path, args.chunk_ms, speed))
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved: {out_path}")
    print(f"transcript ({len(result['transcript'])} chars): {result['transcript'][:200]}...")
    print(f"utterances: {len(result['utterances'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
