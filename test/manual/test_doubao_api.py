#!/usr/bin/env python3
"""
豆包流式 ASR API 完整测试脚本
测试流程：
1. 连接测试
2. 使用本地音频文件测试流式转录
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import soundfile as sf
from src.transcription.doubao_streaming import DoubaoStreamingProcessor


async def test_connection():
    """测试 1: WebSocket 连接"""
    print("=" * 50)
    print("测试 1: WebSocket 连接")
    print("=" * 50)

    processor = DoubaoStreamingProcessor()

    print(f"APP_KEY: {processor.app_key[:4]}***" if processor.app_key else "APP_KEY: 未配置")
    print(f"ACCESS_KEY: {processor.access_key[:4]}***" if processor.access_key else "ACCESS_KEY: 未配置")
    print(f"is_available: {processor.is_available()}")

    if not processor.is_available():
        print("❌ API Key 未配置")
        return False

    print("正在连接...")
    connected = await processor.connect()

    if connected:
        print("✅ 连接成功!")

        # 发送初始请求测试
        print("发送初始请求...")
        result = await processor.send_initial_request()

        if result and result.error:
            print(f"❌ 初始请求失败: {result.error}")
            await processor.disconnect()
            return False
        else:
            print("✅ 初始请求成功!")

        await processor.disconnect()
        return True
    else:
        print("❌ 连接失败")
        return False


async def test_streaming_with_file(audio_path: str):
    """测试 2: 使用音频文件测试完整流式转录"""
    print()
    print("=" * 50)
    print(f"测试 2: 流式转录 ({audio_path})")
    print("=" * 50)

    if not os.path.exists(audio_path):
        print(f"❌ 音频文件不存在: {audio_path}")
        return False

    processor = DoubaoStreamingProcessor()

    if not processor.is_available():
        print("❌ API Key 未配置")
        return False

    # 读取音频文件
    print(f"读取音频文件...")
    audio_data, sample_rate = sf.read(audio_path, dtype='int16')
    duration = len(audio_data) / sample_rate
    print(f"  采样率: {sample_rate}Hz")
    print(f"  长度: {len(audio_data)} 采样点")
    print(f"  时长: {duration:.2f}秒")

    # 如果不是 16000Hz，需要重采样
    target_rate = 16000
    if sample_rate != target_rate:
        print(f"  重采样: {sample_rate}Hz -> {target_rate}Hz")
        # 简单线性插值重采样
        target_length = int(len(audio_data) * target_rate / sample_rate)
        indices = np.linspace(0, len(audio_data) - 1, target_length)
        audio_data = np.interp(indices, np.arange(len(audio_data)), audio_data.astype(float))
        audio_data = audio_data.astype(np.int16)
        sample_rate = target_rate
        print(f"  重采样后长度: {len(audio_data)} 采样点")

    # 准备音频块生成器
    chunk_duration_ms = 200
    samples_per_chunk = int(sample_rate * chunk_duration_ms / 1000)

    async def audio_generator():
        """模拟实时音频流"""
        chunks_sent = 0
        for i in range(0, len(audio_data), samples_per_chunk):
            chunk = audio_data[i:i + samples_per_chunk]
            chunks_sent += 1
            yield chunk.tobytes()
            # 模拟实时发送间隔
            await asyncio.sleep(chunk_duration_ms / 1000 * 0.5)  # 比实时快一点
        print(f"  📤 共发送 {chunks_sent} 个音频块")

    # 收集结果
    all_definite = []
    all_pending = []
    errors = []

    def on_definite(text):
        all_definite.append(text)
        print(f"  ✅ [确定] {text}")

    def on_pending(text):
        all_pending.append(text)
        # 只打印最新的 pending
        display = text[:40] + "..." if len(text) > 40 else text
        print(f"  🔄 [识别中] {display}", end="\r")

    def on_complete():
        print()  # 换行
        print("  ✅ 转录完成")

    def on_error(error):
        errors.append(error)
        print(f"\n  ❌ 错误: {error}")

    print("开始流式转录...")
    await processor.process_audio_stream(
        audio_generator(),
        on_definite,
        on_pending,
        on_complete,
        on_error,
        sample_rate=sample_rate
    )

    # 汇总结果
    print()
    print("-" * 40)
    print("转录结果汇总:")
    final_text = "".join(all_definite)
    if final_text:
        print(f"  最终文本: {final_text}")
        print(f"  ✅ 测试通过!")
        return True
    else:
        print(f"  ❌ 没有识别到任何文本")
        if errors:
            print(f"  错误: {errors}")
        return False


async def main():
    """运行所有测试"""
    print("豆包流式 ASR API 测试")
    print()

    # 测试 1: 连接
    conn_ok = await test_connection()
    if not conn_ok:
        print("\n❌ 连接测试失败，终止后续测试")
        return False

    # 测试 2: 流式转录
    test_audio = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "audio", "test_audio.wav")
    if os.path.exists(test_audio):
        stream_ok = await test_streaming_with_file(test_audio)
    else:
        print(f"\n⚠️ 测试音频文件不存在: {test_audio}")
        print("请先创建测试音频: say -o test.aiff '你好' && ffmpeg -i test.aiff -ar 16000 -ac 1 test/test_audio.wav")
        stream_ok = False

    # 总结
    print()
    print("=" * 50)
    print("测试总结:")
    print(f"  连接测试: {'✅ 通过' if conn_ok else '❌ 失败'}")
    print(f"  流式转录: {'✅ 通过' if stream_ok else '❌ 失败'}")
    print("=" * 50)

    return conn_ok and stream_ok


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
