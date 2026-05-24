"""
parrot/poc.py — 语音 Claude Code 代理 POC (双向传话鹦鹉)

按 Ctrl+C 退出。

跑法:
    source ~/.bashrc  # 让 OFFICIAL_OPENAI_API_KEY_XIANYU 可见
    source .venv/bin/activate
    python -m parrot.poc

前置:
    系统设置 → 声音 → 输入 → DJI MIC MINI 设为默认
    (AVAudioEngine 默认抓系统 default input；想换 mic 改这个)
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
from typing import Any

import AVFoundation as AVF
import numpy as np
import sounddevice as sd
from openai import AsyncOpenAI
from scipy.signal import resample_poly

from .logger import SessionLogger

OPENAI_RATE = 24000          # OpenAI Realtime 要求 24kHz int16 PCM
SPEAKER_CHUNK = 2400         # 100ms @ 24kHz
TAP_BUFFER_FRAMES = 4800     # 100ms @ 48kHz (VPIO 通常输出 48kHz)

DEFAULT_SESSION = os.environ.get("COPILOT_TMUX_SESSION", "tiktok-drama")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


# ============ Tools ============

TOOLS = [
    {
        "type": "function",
        "name": "tmux_list_sessions",
        "description": (
            "列出当前 macOS 上所有 tmux session（名字、windows 数、创建时间、是否 attached）。"
            "当用户问'有哪些 session'或想找某个 Claude Code 会话时调用。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "tmux_capture_pane",
        "description": (
            "读取指定 tmux session 最近 N 行的输出（即用户在那个终端能看到的屏幕）。"
            f"用于了解 Claude Code 的最新进展。默认 session 是 '{DEFAULT_SESSION}'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": f"tmux session 名，默认 '{DEFAULT_SESSION}'"},
                "lines": {"type": "integer", "description": "读取最近多少行，默认 80"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "tmux_send_keys",
        "description": (
            "向指定 tmux session 发送一段文字并按回车，相当于用户在那个终端里输入。"
            "用于把用户的口头指令转达给 Claude Code。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": f"tmux session 名，默认 '{DEFAULT_SESSION}'"},
                "text": {"type": "string", "description": "要发送的文字（不要带 Enter，工具自动按回车）"},
            },
            "required": ["text"],
        },
    },
    {
        "type": "function",
        "name": "tmux_send_ctrl_c",
        "description": "向指定 tmux session 发送 Ctrl+C，用于打断/取消 Claude Code 当前任务。",
        "parameters": {
            "type": "object",
            "properties": {"session": {"type": "string"}},
            "required": [],
        },
    },
]


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def call_tool(name: str, args: dict[str, Any]) -> str:
    session = args.get("session") or DEFAULT_SESSION

    if name == "tmux_list_sessions":
        try:
            return subprocess.check_output(["tmux", "ls"], text=True, stderr=subprocess.STDOUT).strip() or "(no sessions)"
        except subprocess.CalledProcessError as e:
            return f"tmux ls error: {e.output}"

    if name == "tmux_capture_pane":
        lines = int(args.get("lines", 80))
        try:
            out = subprocess.check_output(
                ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"],
                text=True, stderr=subprocess.STDOUT,
            )
            return _strip_ansi(out)
        except subprocess.CalledProcessError as e:
            return f"capture-pane error: {e.output}"

    if name == "tmux_send_keys":
        text = args.get("text", "")
        try:
            subprocess.check_call(["tmux", "send-keys", "-t", session, text, "Enter"])
            return f"已发送到 {session}: {text!r}"
        except subprocess.CalledProcessError as e:
            return f"send-keys error: {e}"

    if name == "tmux_send_ctrl_c":
        try:
            subprocess.check_call(["tmux", "send-keys", "-t", session, "C-c"])
            return f"已向 {session} 发送 Ctrl+C"
        except subprocess.CalledProcessError as e:
            return f"send Ctrl+C error: {e}"

    return f"unknown tool: {name}"


# ============ System Prompt ============

SYSTEM_PROMPT = f"""你是用户的语音 Claude Code 代理。用户视力恢复中，闭着眼睛跟你说话。

默认监管的 tmux session 是 '{DEFAULT_SESSION}'，里面跑着 Claude Code。

行为准则：
1. 用户问"Claude 干了啥/最近怎么样/啥情况"时，调用 tmux_capture_pane 读那个 session，然后用语音念给用户。
2. **念稿规则极其重要**：
   - 代码改动 → 一句话总结（"改了 main.py 第 47 行的超时时间"）
   - 文件路径、长 hash、URL → 不要逐字念，只说"读了 N 个文件"或"打开了 main.py"
   - Claude 的纯文字回答 → 可以念全文
   - 报错 → 念关键错误信息，不念 stack trace
   - tool_use 块（看到 "Tool use:" 之类） → 一句话说调了啥工具，跳过参数
3. 用户说"让 Claude 做 XXX/告诉它/帮我问它"时，调用 tmux_send_keys 转发。
4. 用户说"停一下/取消/打断它"时，调用 tmux_send_ctrl_c。
5. 用户跟你聊天/问你（不是要转发）时，直接回答，**不要**调工具。怎么区分？用户明确说"让 Claude" / "告诉它" / "问它" / "发给它" 才是转发；其他都是跟你说。

说话风格：
- 中文，简短，口语化，不啰嗦
- 念 capture-pane 结果时，先总结一句，再问"要细节吗"
- 不要每次都说"好的我帮你看一下"，直接开干
"""


# ============ Mic: AVAudioEngine + VPIO ============

class VPIOMic:
    """系统级 AEC mic。tap callback 把 float32 chunk 推到 asyncio queue。

    - 启用 VPIO (echo cancellation + AGC + noise suppression)
    - ducking 调到 Min (避免压低系统音量)
    - 抓系统 default input device，所以**前置：DJI 设为系统默认**
    - 输出原始 sample rate (通常 48kHz)，由调用方 resample 到 OpenAI 要求的 24kHz
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, out_queue: asyncio.Queue) -> None:
        self.loop = loop
        self.queue = out_queue
        self.engine = AVF.AVAudioEngine.alloc().init()
        self.input_node = self.engine.inputNode()
        self.sample_rate: int = 0  # 启动后填

    def start(self) -> None:
        ok, err = self.input_node.setVoiceProcessingEnabled_error_(True, None)
        if not ok:
            raise RuntimeError(f"VPIO 启用失败: {err}")

        cfg = AVF.AVAudioVoiceProcessingOtherAudioDuckingConfiguration()
        cfg.enableAdvancedDucking = False
        cfg.duckingLevel = AVF.AVAudioVoiceProcessingOtherAudioDuckingLevelMin
        self.input_node.setVoiceProcessingOtherAudioDuckingConfiguration_(cfg)

        fmt = self.input_node.outputFormatForBus_(0)
        self.sample_rate = int(fmt.sampleRate())

        def tap(buffer, when):
            n = buffer.frameLength()
            if n == 0:
                return
            fp = buffer.floatChannelData()
            if fp is None:
                return
            # ch0 是 cleaned mono mic；PyObjC varlist.as_buffer 不严格按 nbytes 限制，
            # 必须 frombuffer(count=n) 否则会读越界
            buf = fp[0].as_buffer(n * 4)
            samples = np.frombuffer(buf, dtype=np.float32, count=n).copy()
            self.loop.call_soon_threadsafe(self._try_put, samples)

        self.input_node.installTapOnBus_bufferSize_format_block_(0, TAP_BUFFER_FRAMES, fmt, tap)

        ok, err = self.engine.startAndReturnError_(None)
        if not ok:
            raise RuntimeError(f"engine start 失败: {err}")

    def _try_put(self, samples: np.ndarray) -> None:
        try:
            self.queue.put_nowait(samples)
        except asyncio.QueueFull:
            pass  # 丢一帧总比堆积好

    def stop(self) -> None:
        try:
            self.input_node.removeTapOnBus_(0)
        except Exception:
            pass
        self.engine.stop()


# ============ Main loop ============

async def main() -> None:
    api_key = os.environ.get("OFFICIAL_OPENAI_API_KEY_XIANYU")
    if not api_key:
        print("❌ 没找到 OFFICIAL_OPENAI_API_KEY_XIANYU，先 source ~/.bashrc 再跑")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)
    play_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    print(f"🎙️  连接 gpt-realtime-2... 默认 tmux session: {DEFAULT_SESSION}")

    with SessionLogger() as logger:
        print(f"📝 对话日志: {logger.path}")

        async with client.realtime.connect(model="gpt-realtime-2") as conn:
            await conn.send({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": SYSTEM_PROMPT,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                },
            })

            loop = asyncio.get_running_loop()
            mic_q: asyncio.Queue = asyncio.Queue(maxsize=50)
            mic = VPIOMic(loop, mic_q)
            mic.start()
            print(f"🎤 VPIO mic: {mic.sample_rate} Hz → resample → {OPENAI_RATE} Hz")
            print(f"✅ 已连接。开始说话（Ctrl+C 退出）")

            logger.log(
                "session_start",
                tmux_session=DEFAULT_SESSION,
                model="gpt-realtime-2",
                mic_rate=mic.sample_rate,
            )

            async def mic_task() -> None:
                try:
                    while True:
                        f32 = await mic_q.get()
                        if mic.sample_rate != OPENAI_RATE:
                            f32 = resample_poly(f32, OPENAI_RATE, mic.sample_rate)
                        pcm16 = (np.clip(f32, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                        await conn.send({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm16).decode(),
                        })
                finally:
                    mic.stop()

            async def speaker_task() -> None:
                stream = sd.OutputStream(
                    samplerate=OPENAI_RATE, channels=1, dtype="int16",
                    blocksize=SPEAKER_CHUNK,
                )
                stream.start()
                try:
                    while True:
                        chunk = await play_queue.get()
                        if chunk is None:
                            while not play_queue.empty():
                                try:
                                    play_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            stream.abort()
                            stream.start()
                            continue
                        arr = np.frombuffer(chunk, dtype=np.int16)
                        await loop.run_in_executor(None, stream.write, arr)
                finally:
                    stream.stop()
                    stream.close()

            async def event_loop() -> None:
                async for event in conn:
                    etype = event.type

                    if etype == "response.output_audio.delta":
                        await play_queue.put(base64.b64decode(event.delta))

                    elif etype == "input_audio_buffer.speech_started":
                        print("👂 (听见你说话，打断)")
                        await play_queue.put(None)

                    elif etype == "response.output_audio_transcript.done":
                        print(f"🤖 {event.transcript}")
                        logger.log("assistant_speech", transcript=event.transcript)

                    elif etype == "conversation.item.input_audio_transcription.completed":
                        print(f"👤 {event.transcript}")
                        logger.log("user_speech", transcript=event.transcript)

                    elif etype == "response.function_call_arguments.done":
                        name = event.name
                        args = json.loads(event.arguments)
                        print(f"🔧 {name}({args})")
                        logger.log("tool_call", name=name, args=args)
                        result = await loop.run_in_executor(None, call_tool, name, args)
                        preview = result.replace("\n", " ⏎ ")[:200]
                        print(f"   → {preview}")
                        logger.log("tool_result", name=name, output_preview=preview, output_len=len(result))
                        await conn.send({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": event.call_id,
                                "output": result,
                            },
                        })
                        await conn.send({"type": "response.create"})

                    elif etype == "error":
                        print(f"❌ error: {event.error}")
                        logger.log("error", error=str(event.error))

            try:
                await asyncio.gather(mic_task(), speaker_task(), event_loop())
            finally:
                logger.log("session_end")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 bye")
