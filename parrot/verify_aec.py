"""
verify_aec.py — 回归测试: macOS VPIO 在本机的 AEC 性能

外放 8 秒 TTS, 用两种方式各录一遍:
    Round A: sounddevice 录 DJI mic（无 AEC, baseline）
    Round B: AVAudioEngine + VPIO 录 DJI mic（系统级 AEC）

输出 RMS 衰减 dB 数 + 两份 wav 供主观对比.

前置: 系统设置 → 声音 → 输入 → DJI MIC MINI 设为默认 (AVAudioEngine 默认抓系统 default input).

跑法: python -m parrot.verify_aec
"""

import os
import subprocess
import sys
import time
import wave

import AVFoundation as AVF
import numpy as np
import sounddevice as sd

from src.audio.recorder import ALLOWED_DEVICE_KEYWORDS

TTS_TEXT = (
    "Twinkle twinkle little star, how I wonder what you are. "
    "Up above the world so high, like a diamond in the sky."
)
TTS_PATH = "/tmp/aec_tts.aiff"
RAW_OUT = "/tmp/aec_RAW.wav"
VPIO_OUT = "/tmp/aec_VPIO.wav"
DURATION = 8.0
SR_24K = 24000  # OpenAI Realtime 同款


def gen_tts() -> None:
    subprocess.run(["say", "-r", "170", "-o", TTS_PATH, TTS_TEXT], check=True)


def save_wav(samples_int16: np.ndarray, path: str, rate: int) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples_int16.tobytes())


def select_dji_index() -> int:
    """复用主项目设备优先级，返回 sounddevice 看到的 DJI index"""
    devs = sd.query_devices()
    for kw in ALLOWED_DEVICE_KEYWORDS:
        for i, d in enumerate(devs):
            if d["max_input_channels"] > 0 and kw.lower() in d["name"].lower():
                return i
    raise RuntimeError("找不到匹配 ALLOWED_DEVICE_KEYWORDS 的输入设备")


def afplay_bg(path: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["afplay", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record_sounddevice(duration: float, out_path: str, dev_idx: int) -> float:
    """Round A: sounddevice 录 8 秒，同时 afplay 外放 TTS。返回 int16 RMS。"""
    afp = afplay_bg(TTS_PATH)
    time.sleep(0.3)
    rec = sd.rec(
        int(duration * SR_24K),
        device=dev_idx,
        samplerate=SR_24K,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    if afp.poll() is None:
        afp.terminate()
    samples = rec.flatten()
    save_wav(samples, out_path, SR_24K)
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def record_vpio(duration: float, out_path: str) -> float:
    """Round B: AVAudioEngine + VPIO + ducking=Min 录 8 秒。返回 int16 RMS。"""
    engine = AVF.AVAudioEngine.alloc().init()
    inp = engine.inputNode()

    ok, err = inp.setVoiceProcessingEnabled_error_(True, None)
    if not ok:
        raise RuntimeError(f"VPIO 启用失败: {err}")

    # ducking 调到 Min，让 AEC 衰减跟 ducking 解耦
    cfg = AVF.AVAudioVoiceProcessingOtherAudioDuckingConfiguration()
    cfg.enableAdvancedDucking = False
    cfg.duckingLevel = AVF.AVAudioVoiceProcessingOtherAudioDuckingLevelMin
    inp.setVoiceProcessingOtherAudioDuckingConfiguration_(cfg)

    # VPIO 启用后 tap 看到的格式（input device 可能是 8/9 channel deinterleaved）。
    # ch0 是 cleaned mono mic, 其余 channel 是同 data 副本或 garbage。
    fmt = inp.outputFormatForBus_(0)
    sr = int(fmt.sampleRate())

    chunks: list[np.ndarray] = []

    def tap(buffer, when):
        n = buffer.frameLength()
        if n == 0:
            return
        fp = buffer.floatChannelData()
        if fp is None:
            return
        # PyObjC varlist.as_buffer 不严格按 nbytes 限制大小，必须用 count=n
        # 显式限制 frombuffer 不读越界（之前 wav 4x 长度 bug 的根源）
        buf = fp[0].as_buffer(n * 4)
        chunks.append(np.frombuffer(buf, dtype=np.float32, count=n).copy())

    inp.installTapOnBus_bufferSize_format_block_(0, 4800, fmt, tap)

    ok, err = engine.startAndReturnError_(None)
    if not ok:
        raise RuntimeError(f"engine start 失败: {err}")

    afp = afplay_bg(TTS_PATH)
    time.sleep(duration + 0.3)
    if afp.poll() is None:
        afp.terminate()

    engine.stop()
    inp.removeTapOnBus_(0)

    arr = np.concatenate(chunks)
    arr_int16 = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
    save_wav(arr_int16, out_path, sr)
    return float(np.sqrt(np.mean(arr_int16.astype(np.float64) ** 2)))


def main() -> int:
    if not os.path.exists(TTS_PATH):
        print("生成 TTS...")
        gen_tts()
    dji = select_dji_index()
    print(f"DJI sounddevice idx = {dji}")
    print()

    print(f"🔴 Round A: sounddevice (无 AEC), 外放 TTS {DURATION:.0f}s, 保持安静...")
    rms_raw = record_sounddevice(DURATION, RAW_OUT, dji)
    print(f"   saved {RAW_OUT}  rms={rms_raw:.0f}")
    print()

    print(f"🟢 Round B: AVAudioEngine + VPIO + ducking=Min, 外放 TTS {DURATION:.0f}s...")
    rms_vpio = record_vpio(DURATION, VPIO_OUT)
    print(f"   saved {VPIO_OUT}  rms={rms_vpio:.0f}")
    print()

    att_db = 20.0 * np.log10(rms_raw / max(rms_vpio, 1.0))
    verdict = "✅ PASS" if att_db >= 20.0 else "⚠️ WEAK"
    print(f"AEC 衰减: {att_db:.1f} dB  ({verdict}, 工业 benchmark: 20-30 dB)")
    print(f"主观验证: afplay {RAW_OUT}  vs  afplay {VPIO_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
