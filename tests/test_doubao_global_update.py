"""
测试豆包 ASR 流式识别的全局更新行为。

核心问题：豆包 ASR 在后续语音到来后，是否会回溯修改前面已标记为 definite 的文本？

测试方式：
1. 读取本地 wav 文件
2. 模拟实时流式发送（每 100ms 一个 chunk）
3. 详细打印每次服务端返回的 definite/pending 变化
4. 重点观察 definite 文本是否会在后续包中发生变化（而非只是追加）

用法：
    python test_doubao_global_update.py [audio_file.wav]
"""
import asyncio
import json
import os
import sys
import struct
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import load_dotenv

# 加载 .env 配置
load_dotenv()

# 直接导入豆包流式处理器
sys.path.insert(0, str(Path(__file__).parent))
from src.transcription.doubao_streaming import DoubaoStreamingProcessor, DEFAULT_SAMPLE_RATE, SEGMENT_DURATION_MS


def resample_audio(audio_data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """使用 numpy 线性插值重采样"""
    if orig_sr == target_sr:
        return audio_data
    ratio = target_sr / orig_sr
    new_len = int(len(audio_data) * ratio)
    indices = np.arange(new_len) / ratio
    indices = np.clip(indices, 0, len(audio_data) - 1)
    return np.interp(indices, np.arange(len(audio_data)), audio_data).astype(audio_data.dtype)


async def test_global_update(audio_file: str, simulate_realtime: bool = True):
    """
    测试豆包流式 ASR 是否会全局更新 definite 文本。

    Args:
        audio_file: 音频文件路径
        simulate_realtime: 是否模拟实时发送（加 sleep）
    """
    processor = DoubaoStreamingProcessor()
    if not processor.is_available():
        print("❌ 请配置 DOUBAO_APP_KEY 和 DOUBAO_ACCESS_KEY 环境变量")
        return

    # 读取音频
    audio_data, sample_rate = sf.read(audio_file, dtype='float32')
    duration = len(audio_data) / sample_rate
    print(f"📁 音频文件: {audio_file}")
    print(f"   采样率: {sample_rate}Hz, 时长: {duration:.1f}s, 样本数: {len(audio_data)}")

    # 重采样到 16kHz
    if sample_rate != DEFAULT_SAMPLE_RATE:
        print(f"   重采样: {sample_rate}Hz → {DEFAULT_SAMPLE_RATE}Hz")
        audio_data = resample_audio(audio_data, sample_rate, DEFAULT_SAMPLE_RATE)

    # 转为 int16 PCM
    audio_int16 = (audio_data * 32767).astype(np.int16)

    # 分 chunk
    samples_per_chunk = int(DEFAULT_SAMPLE_RATE * SEGMENT_DURATION_MS / 1000)
    chunks = []
    for i in range(0, len(audio_int16), samples_per_chunk):
        chunk = audio_int16[i:i + samples_per_chunk]
        chunks.append(chunk.tobytes())

    print(f"   分为 {len(chunks)} 个 chunk（每个 {SEGMENT_DURATION_MS}ms）")
    print()

    # ==================== 关键：记录每一次返回的 definite 变化 ====================
    history = []  # 记录每次返回: (timestamp, definite, pending)
    prev_definite = ""
    definite_changes = []  # 记录 definite 变化时刻
    start_time = time.time()

    async def audio_generator():
        """模拟实时音频流"""
        for i, chunk in enumerate(chunks):
            yield chunk
            if simulate_realtime:
                await asyncio.sleep(SEGMENT_DURATION_MS / 1000.0)

    def on_preview_text(text: str):
        """预览回调 - 不在此测试中使用"""
        pass

    def on_final_text(text: str):
        """最终文本回调"""
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"🏁 最终文本 (t={elapsed:.1f}s):")
        print(f"   {text}")
        print(f"{'='*60}")

    def on_complete():
        print("✅ 转录完成")

    def on_error(error: str):
        print(f"❌ 错误: {error}")

    # ==================== 重写 receiver 来详细追踪变化 ====================
    # 我们不直接用 process_audio_stream，而是手动控制流程以获得更细粒度的观察

    print("🚀 开始流式识别...\n")
    print(f"{'序号':>4}  {'时间':>6}  {'类型':<6}  {'Definite':<40}  {'Pending':<30}")
    print("-" * 100)

    # 手动实现流式流程
    processor._sample_rate = DEFAULT_SAMPLE_RATE

    if processor._is_connected or processor._ws or processor._session:
        await processor.disconnect()

    if not await processor.connect():
        print("❌ 连接失败")
        return

    try:
        init_result = await processor.send_initial_request()
        if init_result and init_result.error:
            print(f"❌ 初始化错误: {init_result.error}")
            return

        recv_count = 0
        prev_definite = ""
        has_global_update = False  # 是否观察到全局更新

        async def sender():
            chunk_count = 0
            for chunk in chunks:
                chunk_count += 1
                await processor.send_audio_chunk(chunk, is_last=False)
                if simulate_realtime:
                    await asyncio.sleep(SEGMENT_DURATION_MS / 1000.0)
            await processor.send_audio_chunk(b"", is_last=True)
            print(f"\n📤 发送完成，共 {chunk_count} 个 chunk")

        async def receiver():
            nonlocal recv_count, prev_definite, has_global_update
            while True:
                try:
                    result = await asyncio.wait_for(
                        processor.receive_result(),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    print("⏰ 接收超时")
                    break

                if result is None:
                    continue

                if result.error:
                    print(f"⚠️  错误: {result.error}")
                    if result.is_final:
                        break
                    continue

                recv_count += 1
                elapsed = time.time() - start_time

                # ===== 关键检测：definite 是否发生非追加式变化 =====
                change_type = ""
                if result.definite_text != prev_definite:
                    if not result.definite_text:
                        change_type = "清空"
                    elif result.definite_text.startswith(prev_definite):
                        new_part = result.definite_text[len(prev_definite):]
                        change_type = f"+追加"
                    else:
                        change_type = "🔄全局更新!"
                        has_global_update = True
                    prev_definite = result.definite_text
                else:
                    change_type = "(不变)"

                # 截断显示
                def truncate(s, maxlen=38):
                    if len(s) > maxlen:
                        return s[:maxlen-2] + ".."
                    return s

                definite_display = truncate(result.definite_text) if result.definite_text else "(空)"
                pending_display = truncate(result.pending_text, 28) if result.pending_text else "(空)"

                print(f"{recv_count:>4}  {elapsed:>5.1f}s  {change_type:<6}  {definite_display:<40}  {pending_display:<30}")

                history.append({
                    "seq": recv_count,
                    "time": round(elapsed, 2),
                    "definite": result.definite_text,
                    "pending": result.pending_text,
                    "change": change_type,
                    "is_final": result.is_final,
                })

                if result.is_final:
                    break

        sender_task = asyncio.create_task(sender())
        receiver_task = asyncio.create_task(receiver())
        await asyncio.gather(sender_task, receiver_task)

    finally:
        await processor.disconnect()

    # ==================== 分析结果 ====================
    print(f"\n{'='*60}")
    print("📊 分析结果:")
    print(f"   总共收到 {recv_count} 个响应")

    # 统计 definite 变化
    updates = [h for h in history if "全局更新" in h["change"]]
    appends = [h for h in history if "追加" in h["change"]]

    print(f"   Definite 追加次数: {len(appends)}")
    print(f"   Definite 全局更新次数: {len(updates)}")

    if updates:
        print(f"\n   ✅ 观察到全局更新！豆包确实会回溯修正前面的 definite 文本：")
        for u in updates:
            print(f"      #{u['seq']} (t={u['time']}s): definite='{u['definite']}'")
    else:
        print(f"\n   ⚠️  未观察到全局更新。Definite 文本始终是单调追加的。")
        print(f"   这意味着一旦文本被标记为 definite，后续就不会修改。")

    # 保存详细日志
    log_file = audio_file.rsplit('.', 1)[0] + '_doubao_log.json'
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"\n   详细日志已保存到: {log_file}")


if __name__ == "__main__":
    audio_file = sys.argv[1] if len(sys.argv) > 1 else "audio_archive/recording_20250727_011616.wav"

    if not Path(audio_file).exists():
        print(f"❌ 文件不存在: {audio_file}")
        sys.exit(1)

    asyncio.run(test_global_update(audio_file, simulate_realtime=True))
