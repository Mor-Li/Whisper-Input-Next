#!/usr/bin/env python3
"""
大音频文件转录脚本
- 自动按静音点切分音频（避免切断说话）
- 异步并行转录
- tqdm 进度条显示
- 支持带时间戳输出

用法:
  python transcribe_audio.py <音频文件> [选项]

选项:
  --timestamps, -t    输出带时间戳的版本
  --workers N         并发数量（默认16）
"""

import os
import sys
import asyncio
import tempfile
import subprocess
import argparse
from pathlib import Path

# 设置环境变量（在导入 openai 之前）
os.environ.pop("OPENAI_BASE_URL", None)
official_key = subprocess.run(
    ["zsh", "-c", "source ~/.zshrc && echo $OFFICIAL_OPENAI_API_KEY"],
    capture_output=True, text=True
).stdout.strip()
if official_key:
    os.environ["OPENAI_API_KEY"] = official_key

import httpx
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm_asyncio


# 配置
CHUNK_DURATION = 600  # 目标切分长度（秒），10分钟
SILENCE_THRESH_DB = -35  # 静音检测阈值（dB）
MIN_SILENCE_LEN = 0.5  # 最小静音长度（秒）


def get_audio_duration(audio_path: str) -> float:
    """获取音频时长（秒）"""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def detect_silence_points(audio_path: str) -> list[float]:
    """检测音频中的静音点，返回静音开始时间列表"""
    cmd = [
        "ffmpeg", "-i", audio_path, "-af",
        f"silencedetect=noise={SILENCE_THRESH_DB}dB:d={MIN_SILENCE_LEN}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    silence_points = []
    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            try:
                start = float(line.split("silence_start:")[1].strip().split()[0])
                silence_points.append(start)
            except (IndexError, ValueError):
                continue

    return silence_points


def find_best_split_point(silence_points: list[float], target_time: float,
                          tolerance: float = 60) -> float | None:
    """在目标时间附近找最佳静音切分点"""
    candidates = [p for p in silence_points
                  if target_time - tolerance <= p <= target_time + tolerance]
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x - target_time))


def smart_split_audio(audio_path: str, output_dir: str) -> list[tuple[str, float]]:
    """智能切分音频，返回 [(文件路径, 起始时间), ...]"""
    print("Analyzing silence points...")
    duration = get_audio_duration(audio_path)
    silence_points = detect_silence_points(audio_path)
    print(f"   Found {len(silence_points)} silence points")

    # 计算切分点
    split_points = [0]
    current_pos = 0

    while current_pos + CHUNK_DURATION < duration:
        target = current_pos + CHUNK_DURATION
        best_point = find_best_split_point(silence_points, target)

        if best_point is not None:
            split_points.append(best_point)
            current_pos = best_point
        else:
            split_points.append(target)
            current_pos = target

    split_points.append(duration)

    # 执行切分
    chunk_info = []
    print(f"Splitting into {len(split_points) - 1} chunks...")

    for i in range(len(split_points) - 1):
        start = split_points[i]
        end = split_points[i + 1]
        output_path = os.path.join(output_dir, f"chunk_{i:03d}.mp3")

        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-to", str(end),
            "-c", "copy", output_path
        ]
        subprocess.run(cmd, capture_output=True)
        chunk_info.append((output_path, start))

    return chunk_info


async def transcribe_chunk(client: AsyncOpenAI, chunk_path: str, start_time: float,
                           semaphore: asyncio.Semaphore) -> tuple[int, str, float]:
    """转录单个音频片段"""
    chunk_idx = int(Path(chunk_path).stem.split("_")[1])

    async with semaphore:
        with open(chunk_path, "rb") as f:
            resp = await client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=f,
                language="zh",
            )
        return chunk_idx, resp.text, start_time


async def transcribe_all_chunks(chunk_info: list[tuple[str, float]],
                                max_workers: int) -> list[tuple[str, float]]:
    """并行转录所有音频片段"""
    client = AsyncOpenAI(timeout=httpx.Timeout(300.0, connect=60.0))
    semaphore = asyncio.Semaphore(max_workers)

    tasks = [
        transcribe_chunk(client, path, start_time, semaphore)
        for path, start_time in chunk_info
    ]

    results = await tqdm_asyncio.gather(*tasks, desc="Transcribing")

    # 按索引排序
    results.sort(key=lambda x: x[0])
    return [(text, start_time) for _, text, start_time in results]


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_with_timestamps(results: list[tuple[str, float]]) -> str:
    """格式化带时间戳的输出"""
    lines = []
    for text, start_time in results:
        time_str = format_time(start_time)
        lines.append(f"[{time_str}]\n{text.strip()}")
    return "\n\n".join(lines)


def format_plain_text(results: list[tuple[str, float]]) -> str:
    """输出纯文本"""
    return "\n\n".join(text.strip() for text, _ in results)


def main():
    parser = argparse.ArgumentParser(description="Transcribe large audio files")
    parser.add_argument("audio_path", help="Path to audio file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("-t", "--timestamps", action="store_true",
                        help="Output with timestamps")
    parser.add_argument("-w", "--workers", type=int, default=16,
                        help="Number of concurrent workers (default: 16)")

    args = parser.parse_args()

    audio_path = args.audio_path
    if not os.path.isabs(audio_path):
        audio_path = os.path.abspath(audio_path)

    if not os.path.exists(audio_path):
        print(f"File not found: {audio_path}")
        sys.exit(1)

    # 输出文件路径
    base_name = Path(audio_path).stem
    output_dir = os.path.dirname(audio_path)

    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(output_dir, f"{base_name}_transcript.txt")

    print(f"Input:   {audio_path}")
    print(f"Output:  {output_path}")
    print(f"Workers: {args.workers}")

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"Size:    {file_size_mb:.1f} MB")

    duration = get_audio_duration(audio_path)
    print(f"Duration: {duration/60:.1f} min")

    # 创建临时目录存放切分后的音频
    with tempfile.TemporaryDirectory() as temp_dir:
        chunk_info = smart_split_audio(audio_path, temp_dir)
        print(f"   Split into {len(chunk_info)} chunks")

        print(f"\nStarting transcription ({args.workers} workers)...")
        results = asyncio.run(transcribe_all_chunks(chunk_info, args.workers))

    # 格式化输出
    if args.timestamps:
        output_text = format_with_timestamps(results)
    else:
        output_text = format_plain_text(results)

    # 保存
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"\nDone!")
    print(f"Saved to: {output_path}")
    print(f"\n{'='*50}")
    print("Preview (first 500 chars):")
    print(output_text[:500])
    if len(output_text) > 500:
        print("...")


if __name__ == "__main__":
    main()
