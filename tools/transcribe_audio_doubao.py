#!/usr/bin/env python3
"""
Large audio transcription script using Doubao streaming ASR.

Usage:
  python test/transcribe_audio_doubao.py <audio_file> [options]

Options:
  -o, --output PATH       Output transcript path
  --chunk-ms N            PCM chunk size in milliseconds (default: project default)
  --speed N               Send speed relative to realtime; 0 means no pacing (default: 20)
  --realtime              Equivalent to --speed 1
"""

import argparse
import asyncio
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


def load_environment() -> None:
    """Load .env first, then fill missing Doubao vars from ~/.zshrc."""
    load_dotenv(ROOT_DIR / ".env")

    missing = [
        key
        for key in ("DOUBAO_APP_KEY", "DOUBAO_ACCESS_KEY")
        if not os.getenv(key)
    ]
    if not missing:
        return

    command = (
        "source ~/.zshrc >/dev/null 2>&1; "
        "printf '%s\\n' "
        "\"DOUBAO_APP_KEY=$DOUBAO_APP_KEY\" "
        "\"DOUBAO_ACCESS_KEY=$DOUBAO_ACCESS_KEY\""
    )
    result = subprocess.run(
        ["zsh", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in missing and value:
            os.environ[key] = value


def get_audio_duration(audio_path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


async def pcm_chunk_generator(
    audio_path: Path,
    chunk_ms: int,
    speed: float,
):
    """Convert input audio to 16k mono s16le PCM and yield bytes chunks."""
    chunk_size = int(DEFAULT_SAMPLE_RATE * chunk_ms / 1000) * BYTES_PER_SAMPLE * CHANNELS
    if chunk_size <= 0:
        raise ValueError("--chunk-ms must be positive")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        str(CHANNELS),
        "-ar",
        str(DEFAULT_SAMPLE_RATE),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
        return_code = await process.wait()
        if return_code != 0:
            message = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"ffmpeg failed with exit code {return_code}: {message}")


async def transcribe_with_doubao(
    audio_path: Path,
    output_path: Path,
    chunk_ms: int,
    speed: float,
) -> str:
    processor = DoubaoStreamingProcessor()
    if not processor.is_available():
        raise RuntimeError("DOUBAO_APP_KEY and DOUBAO_ACCESS_KEY are not configured")

    latest_preview = ""
    final_text = ""
    errors: list[str] = []

    def on_preview_text(text: str) -> None:
        nonlocal latest_preview
        latest_preview = text
        print(f"\rPreview chars: {len(text)}", end="", flush=True)

    def on_final_text(text: str) -> None:
        nonlocal final_text
        final_text = text

    def on_complete() -> None:
        print("\nDoubao transcription completed")

    def on_error(error: str) -> None:
        errors.append(error)
        print(f"\nDoubao error: {error}", flush=True)

    await processor.process_audio_stream(
        pcm_chunk_generator(audio_path, chunk_ms, speed),
        on_preview_text,
        on_final_text,
        on_complete,
        on_error,
        sample_rate=DEFAULT_SAMPLE_RATE,
    )

    transcript = (final_text or latest_preview).strip()
    if not transcript:
        detail = "; ".join(errors) if errors else "no text returned"
        raise RuntimeError(f"Doubao transcription produced no text: {detail}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript + "\n", encoding="utf-8")
    return transcript


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe audio via Doubao streaming ASR")
    parser.add_argument("audio_path", help="Path to audio file")
    parser.add_argument("-o", "--output", help="Output transcript path")
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=SEGMENT_DURATION_MS,
        help=f"PCM chunk size in milliseconds (default: {SEGMENT_DURATION_MS})",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=20.0,
        help="Send speed relative to realtime; 0 means no pacing (default: 20)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Send audio at realtime speed, equivalent to --speed 1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()

    audio_path = Path(args.audio_path).expanduser().resolve()
    if not audio_path.exists():
        print(f"File not found: {audio_path}", file=sys.stderr)
        return 1

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else audio_path.with_name(f"{audio_path.stem}_doubao_transcript.txt")
    )
    speed = 1.0 if args.realtime else args.speed

    print(f"Input:       {audio_path}")
    print(f"Output:      {output_path}")
    print(f"Sample rate: {DEFAULT_SAMPLE_RATE} Hz")
    print(f"Chunk:       {args.chunk_ms} ms")
    print(f"Speed:       {'unpaced' if speed == 0 else f'{speed:g}x realtime'}")

    duration = get_audio_duration(audio_path)
    if duration is not None:
        print(f"Duration:    {duration / 60:.1f} min")

    transcript = asyncio.run(
        transcribe_with_doubao(audio_path, output_path, args.chunk_ms, speed)
    )

    print(f"Saved to:    {output_path}")
    print("\nPreview:")
    print(transcript[:500])
    if len(transcript) > 500:
        print("...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
