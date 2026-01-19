#!/usr/bin/env python3
"""
测试 AudioRecorder 和 DoubaoStreamingProcessor 的集成
模拟麦克风录音场景
"""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import soundfile as sf
from src.audio.recorder import AudioRecorder
from src.transcription.doubao_streaming import DoubaoStreamingProcessor


async def test_recorder_integration():
    """测试 AudioRecorder 的 stream_audio_chunks 方法"""
    print("=" * 50)
    print("测试: AudioRecorder + DoubaoStreamingProcessor 集成")
    print("=" * 50)

    # 读取测试音频
    test_audio_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "audio", "test_audio.wav")
    if not os.path.exists(test_audio_path):
        print(f"❌ 测试音频不存在: {test_audio_path}")
        return False

    audio_data, sample_rate = sf.read(test_audio_path, dtype='float32')
    print(f"测试音频: {sample_rate}Hz, {len(audio_data)} samples, {len(audio_data)/sample_rate:.2f}s")

    # 创建 AudioRecorder
    recorder = AudioRecorder()
    # 设置采样率为测试音频的采样率
    recorder.sample_rate = sample_rate
    recorder.recording = True  # 模拟开始录音

    # 创建 processor
    processor = DoubaoStreamingProcessor()
    if not processor.is_available():
        print("❌ API Key 未配置")
        return False

    # 模拟麦克风输入：把音频数据分块放入 recorder 的队列
    def simulate_microphone():
        """模拟麦克风回调，将音频数据放入队列"""
        chunk_size = 1024  # 每次回调的采样点数（类似真实麦克风）
        for i in range(0, len(audio_data), chunk_size):
            if not recorder.recording:
                break
            chunk = audio_data[i:i + chunk_size]
            recorder.audio_queue.put(chunk.copy())
            time.sleep(chunk_size / sample_rate * 0.5)  # 模拟实时，但比实时快一点
        print("  📥 模拟麦克风输入完成")

    # 在后台线程模拟麦克风
    mic_thread = threading.Thread(target=simulate_microphone, daemon=True)
    mic_thread.start()

    # 收集结果
    all_definite = []
    errors = []

    def on_definite(text):
        all_definite.append(text)
        print(f"  ✅ [确定] {text}")

    def on_pending(text):
        display = text[:40] + "..." if len(text) > 40 else text
        print(f"  🔄 [识别中] {display}", end="\r")

    def on_complete():
        print()
        print("  ✅ 转录完成")

    def on_error(error):
        errors.append(error)
        print(f"\n  ❌ 错误: {error}")

    print("开始流式转录...")
    print(f"  使用 stream_audio_chunks(target_sample_rate=16000)")

    # 设置一个定时器，在音频播放完后停止录音
    async def stop_after_audio():
        await asyncio.sleep(len(audio_data) / sample_rate + 1)  # 等待音频播放完 + 1秒
        recorder.recording = False
        print("  ⏹️ 停止录音")

    # 并行运行转录和停止定时器
    stop_task = asyncio.create_task(stop_after_audio())

    await processor.process_audio_stream(
        recorder.stream_audio_chunks(target_sample_rate=16000),
        on_definite,
        on_pending,
        on_complete,
        on_error,
        sample_rate=16000
    )

    stop_task.cancel()

    # 汇总结果
    print()
    print("-" * 40)
    print("转录结果汇总:")
    final_text = "".join(all_definite)
    if final_text:
        print(f"  最终文本: {final_text}")
        print("  ✅ 集成测试通过!")
        return True
    else:
        print("  ❌ 没有识别到任何文本")
        if errors:
            print(f"  错误: {errors}")
        return False


async def main():
    success = await test_recorder_integration()

    print()
    print("=" * 50)
    print(f"测试结果: {'✅ 通过' if success else '❌ 失败'}")
    print("=" * 50)

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
