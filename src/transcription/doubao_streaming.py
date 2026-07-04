"""
豆包流式语音识别处理器

使用 WebSocket 连接豆包大模型流式语音识别 API，支持：
- 边说边转录
- 实时返回 definite（已确定）和 pending（待确定）文本
- 基于 bigmodel_async 优化版接口
"""

import os
import asyncio
import json
import struct
import gzip
import uuid
import logging
import time
import math
from typing import Optional, Callable, AsyncGenerator
from dataclasses import dataclass

import aiohttp

from ..utils.logger import logger

# 常量定义
DEFAULT_SAMPLE_RATE = 16000
SEGMENT_DURATION_MS = 100  # 每包音频时长（毫秒）
CONNECT_TIMEOUT_SECONDS = 10
INITIAL_RESPONSE_TIMEOUT_SECONDS = 10
SEND_TIMEOUT_SECONDS = 5
DISCONNECT_TIMEOUT_SECONDS = 2
FINAL_RESPONSE_TIMEOUT_SECONDS = 5
RECEIVE_POLL_TIMEOUT_SECONDS = 1
RECEIVE_STALL_TIMEOUT_SECONDS = 10
VOICE_ACTIVITY_RMS_THRESHOLD = 300
MAX_STREAM_RECONNECT_ATTEMPTS = 2
RECONNECT_BACKOFF_SECONDS = 0.5
# stream_audio_chunks 默认每块 200ms；300 块约等于 60s 音频上下文。
REPLAY_BUFFER_MAX_CHUNKS = 300


class ProtocolVersion:
    V1 = 0b0001


class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111


class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011


class SerializationType:
    NO_SERIALIZATION = 0b0000
    JSON = 0b0001


class CompressionType:
    NO_COMPRESSION = 0b0000
    GZIP = 0b0001


@dataclass
class StreamingResult:
    """流式识别结果"""
    definite_text: str = ""  # 已确定的文本（不会再变）
    pending_text: str = ""   # 待确定的文本（可能会变）
    is_final: bool = False   # 是否是最终结果
    error: Optional[str] = None


class DoubaoStreamingProcessor:
    """豆包流式语音识别处理器"""

    def __init__(self):
        self.app_key = os.getenv("DOUBAO_APP_KEY", "")
        self.access_key = os.getenv("DOUBAO_ACCESS_KEY", "")
        # 使用优化版双向流式接口
        self.ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._seq = 1
        self._is_connected = False
        self._sample_rate = DEFAULT_SAMPLE_RATE  # 默认采样率，会在连接时更新

        if not self.app_key or not self.access_key:
            logger.warning("豆包 API Key 未配置，请设置 DOUBAO_APP_KEY 和 DOUBAO_ACCESS_KEY")

    def is_available(self) -> bool:
        """检查是否可用（API Key 是否配置）"""
        return bool(self.app_key and self.access_key)

    def _gzip_compress(self, data: bytes) -> bytes:
        return gzip.compress(data)

    def _gzip_decompress(self, data: bytes) -> bytes:
        return gzip.decompress(data)

    def _build_header(
        self,
        message_type: int,
        flags: int,
        serialization: int = SerializationType.JSON,
        compression: int = CompressionType.GZIP
    ) -> bytes:
        """构建协议头"""
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)  # version + header size
        header.append((message_type << 4) | flags)
        header.append((serialization << 4) | compression)
        header.append(0x00)  # reserved
        return bytes(header)

    def _build_full_client_request(self) -> bytes:
        """构建初始请求包"""
        header = self._build_header(
            MessageType.CLIENT_FULL_REQUEST,
            MessageTypeSpecificFlags.POS_SEQUENCE
        )

        payload = {
            "user": {
                "uid": "whisper_input_next"
            },
            "audio": {
                "format": "pcm",         # 原始 PCM 格式
                "codec": "raw",
                "rate": self._sample_rate,  # 使用实际采样率
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,      # 文本规范化
                "enable_punc": True,     # 启用标点
                "enable_ddc": True,      # 语义顺滑
                "show_utterances": True, # 显示分句信息
                "result_type": "full",   # 全量返回
                "enable_nonstream": True # 二遍识别：停顿时用 nostream 模型重新识别该句，提升准确率
            }
        }

        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = self._gzip_compress(payload_bytes)

        request = bytearray()
        request.extend(header)
        request.extend(struct.pack('>i', self._seq))  # sequence number
        request.extend(struct.pack('>I', len(compressed_payload)))
        request.extend(compressed_payload)

        self._seq += 1
        return bytes(request)

    def _build_audio_request(self, audio_chunk: bytes, is_last: bool = False) -> bytes:
        """构建音频数据包"""
        if is_last:
            flags = MessageTypeSpecificFlags.NEG_WITH_SEQUENCE
            seq = -self._seq
        else:
            flags = MessageTypeSpecificFlags.POS_SEQUENCE
            seq = self._seq
            self._seq += 1

        header = self._build_header(
            MessageType.CLIENT_AUDIO_ONLY_REQUEST,
            flags,
            serialization=SerializationType.NO_SERIALIZATION,
            compression=CompressionType.GZIP
        )

        compressed_audio = self._gzip_compress(audio_chunk)

        request = bytearray()
        request.extend(header)
        request.extend(struct.pack('>i', seq))
        request.extend(struct.pack('>I', len(compressed_audio)))
        request.extend(compressed_audio)

        return bytes(request)

    def _parse_response(self, msg: bytes) -> StreamingResult:
        """解析服务器响应"""
        result = StreamingResult()

        if len(msg) < 4:
            result.error = "响应数据太短"
            return result

        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_flags = msg[1] & 0x0f
        serialization = msg[2] >> 4
        compression = msg[2] & 0x0f

        payload = msg[header_size * 4:]

        # 解析 flags
        if message_flags & 0x01:  # 有 sequence
            payload = payload[4:]
        if message_flags & 0x02:  # 最后一包
            result.is_final = True

        # 解析 message type
        if message_type == MessageType.SERVER_ERROR_RESPONSE:
            error_code = struct.unpack('>i', payload[:4])[0]
            payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            if compression == CompressionType.GZIP and payload:
                try:
                    payload = self._gzip_decompress(payload)
                except Exception:
                    pass
            result.error = f"服务器错误 {error_code}: {payload.decode('utf-8', errors='ignore')}"
            return result

        if message_type == MessageType.SERVER_FULL_RESPONSE:
            payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]

        if not payload:
            return result

        # 解压缩
        if compression == CompressionType.GZIP:
            try:
                payload = self._gzip_decompress(payload)
            except Exception as e:
                result.error = f"解压缩失败: {e}"
                return result

        # 解析 JSON
        if serialization == SerializationType.JSON:
            try:
                data = json.loads(payload.decode('utf-8'))
                result = self._extract_text_from_response(data)
                result.is_final = message_flags & 0x02
            except Exception as e:
                result.error = f"JSON 解析失败: {e}"

        return result

    def _extract_text_from_response(self, data: dict) -> StreamingResult:
        """从响应数据中提取文本"""
        result = StreamingResult()

        if "result" not in data:
            return result

        response_result = data["result"]

        # 提取完整文本
        full_text = response_result.get("text", "")

        # 解析分句信息
        utterances = response_result.get("utterances", [])

        definite_parts = []
        pending_parts = []

        for utt in utterances:
            text = utt.get("text", "")
            if utt.get("definite", False):
                definite_parts.append(text)
            else:
                pending_parts.append(text)

        result.definite_text = "".join(definite_parts)
        result.pending_text = "".join(pending_parts)

        # 如果没有分句信息，使用完整文本作为 pending
        if not utterances and full_text:
            result.pending_text = full_text

        return result

    def _merge_stream_text(self, prefix: str, session_text: str) -> str:
        """拼接重连前后的 ASR 文本，尽量去掉边界处的重复。"""
        prefix = (prefix or "").strip()
        session_text = (session_text or "").strip()
        if not prefix:
            return session_text
        if not session_text:
            return prefix
        if prefix.endswith(session_text):
            return prefix
        if session_text.startswith(prefix):
            return session_text

        max_overlap = min(len(prefix), len(session_text), 80)
        for size in range(max_overlap, 0, -1):
            if prefix.endswith(session_text[:size]):
                return prefix + session_text[size:]
        return prefix + session_text

    def _is_recoverable_stream_error(self, error: Optional[str]) -> bool:
        if not error:
            return False
        recoverable_markers = (
            "连接失败",
            "发送初始请求超时",
            "发送初始请求失败",
            "接收结果停滞超时",
            "连接已关闭",
            "WebSocket 错误",
            "接收结果失败",
            "发送音频块失败",
            "发送结束标记失败",
            "等待最终识别结果超时",
        )
        return any(marker in error for marker in recoverable_markers)

    def _is_voiced_audio_chunk(self, chunk: bytes) -> bool:
        if len(chunk) < 2:
            return False
        try:
            samples = memoryview(chunk[:len(chunk) - (len(chunk) % 2)]).cast("h")
            if len(samples) == 0:
                return False
            mean_square = sum(sample * sample for sample in samples) / len(samples)
            return math.sqrt(mean_square) >= VOICE_ACTIVITY_RMS_THRESHOLD
        except Exception:
            return True

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        if not self.is_available():
            logger.error("豆包 API Key 未配置")
            return False

        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=CONNECT_TIMEOUT_SECONDS)
            )
            connect_id = str(uuid.uuid4())
            headers = {
                "X-Api-Resource-Id": "volc.seedasr.sauc.duration",  # 2.0版本小时版
                "X-Api-Connect-Id": connect_id,
                "X-Api-Access-Key": self.access_key,
                "X-Api-App-Key": self.app_key
            }

            self._ws = await self._session.ws_connect(
                self.ws_url,
                headers=headers,
                timeout=CONNECT_TIMEOUT_SECONDS,
                heartbeat=20,
            )
            self._is_connected = True
            self._seq = 1
            logger.info("豆包流式 ASR 连接成功")
            return True
        except aiohttp.WSServerHandshakeError as e:
            # 服务端在 WS 握手阶段拒绝（403/401/404 等），response headers 里通常带有
            # X-Tt-Logid / X-Api-Status-Code / X-Api-Message，是排障的关键
            resp_headers = dict(getattr(e, "headers", {}) or {})
            logid = resp_headers.get("X-Tt-Logid") or resp_headers.get("x-tt-logid")
            api_status = resp_headers.get("X-Api-Status-Code") or resp_headers.get("x-api-status-code")
            api_message = resp_headers.get("X-Api-Message") or resp_headers.get("x-api-message")
            app_key_hint = f"{self.app_key[:4]}…{self.app_key[-4:]}" if len(self.app_key) >= 8 else "(too-short)"
            access_key_hint = f"{self.access_key[:4]}…{self.access_key[-4:]}" if len(self.access_key) >= 8 else "(too-short)"
            logger.error(
                "连接豆包 ASR 握手失败 status=%s message=%s | "
                "X-Api-Status-Code=%s X-Api-Message=%s X-Tt-Logid=%s | "
                "connect_id=%s app_key=%s access_key=%s",
                e.status, e.message, api_status, api_message, logid,
                connect_id, app_key_hint, access_key_hint,
            )
            await self.disconnect()
            return False
        except Exception as e:
            logger.error(f"连接豆包 ASR 失败: {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        """断开连接"""
        self._is_connected = False
        try:
            if self._ws and not self._ws.closed:
                await asyncio.wait_for(self._ws.close(), timeout=DISCONNECT_TIMEOUT_SECONDS)
        except Exception:
            pass
        try:
            if self._session and not self._session.closed:
                await asyncio.wait_for(self._session.close(), timeout=DISCONNECT_TIMEOUT_SECONDS)
        except Exception:
            pass
        self._ws = None
        self._session = None

    async def send_initial_request(self) -> Optional[StreamingResult]:
        """发送初始请求"""
        if not self._ws:
            return StreamingResult(error="未连接")

        try:
            request = self._build_full_client_request()
            await asyncio.wait_for(self._ws.send_bytes(request), timeout=SEND_TIMEOUT_SECONDS)
            logger.debug("已发送初始请求")

            # 等待响应
            msg = await asyncio.wait_for(
                self._ws.receive(),
                timeout=INITIAL_RESPONSE_TIMEOUT_SECONDS,
            )
            if msg.type == aiohttp.WSMsgType.BINARY:
                return self._parse_response(msg.data)
            else:
                return StreamingResult(error=f"意外的响应类型: {msg.type}")
        except asyncio.TimeoutError:
            return StreamingResult(error="发送初始请求超时")
        except Exception as e:
            return StreamingResult(error=f"发送初始请求失败: {e}")

    async def send_audio_chunk(self, chunk: bytes, is_last: bool = False) -> bool:
        """发送音频数据块"""
        if not self._ws:
            return False

        try:
            request = self._build_audio_request(chunk, is_last)
            await asyncio.wait_for(self._ws.send_bytes(request), timeout=SEND_TIMEOUT_SECONDS)
            return True
        except asyncio.TimeoutError:
            logger.error("发送音频块超时")
            return False
        except Exception as e:
            logger.error(f"发送音频块失败: {e}")
            return False

    async def receive_result(self, timeout: Optional[float] = None) -> Optional[StreamingResult]:
        """接收识别结果"""
        if not self._ws:
            return None

        try:
            if timeout is not None:
                msg = await self._ws.receive(timeout=timeout)
            else:
                msg = await self._ws.receive()
            if msg.type == aiohttp.WSMsgType.BINARY:
                return self._parse_response(msg.data)
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                return StreamingResult(error="连接已关闭", is_final=True)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                return StreamingResult(error=f"WebSocket 错误: {msg.data}", is_final=True)
            else:
                return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return StreamingResult(error=f"接收结果失败: {e}")

    async def process_audio_stream(
        self,
        audio_chunk_generator: AsyncGenerator[bytes, None],
        on_preview_text: Callable[[str], None],
        on_final_text: Callable[[str], None],
        on_complete: Callable[[], None],
        on_error: Callable[[str], None],
        sample_rate: int = DEFAULT_SAMPLE_RATE
    ):
        """
        流式处理音频

        录音期间所有文本（definite + pending）仅通过 on_preview_text 展示在悬浮框中，
        不会提前输入到目标应用。只有在流式结束后，才通过 on_final_text 一次性输出最终文本。
        这样可以让豆包 ASR 充分利用全局上下文优化，避免前面已输入的文字无法被后续修正。

        Args:
            audio_chunk_generator: 异步生成器，yield 音频块 (bytes)
            on_preview_text: 收到文本更新时调用（definite+pending 全量预览）
            on_final_text: 流式结束后调用，传入最终完整文本
            on_complete: 转录完成时调用
            on_error: 发生错误时调用
            sample_rate: 音频采样率（默认 16000）
        """
        self._sample_rate = sample_rate
        logger.info(f"使用采样率: {sample_rate}Hz")

        error_reported = False
        audio_iter = audio_chunk_generator.__aiter__()
        audio_exhausted = False
        committed_text = ""
        latest_preview_text = ""
        replay_chunks: list[bytes] = []
        reconnect_attempts = 0

        def report_error(error: str) -> None:
            nonlocal error_reported
            if not error_reported:
                on_error(error)
                error_reported = True

        async def run_one_session(initial_replay_chunks: list[bytes]) -> tuple[bool, Optional[str], list[bytes]]:
            nonlocal audio_exhausted, committed_text, latest_preview_text

            # 确保旧连接已清理
            if self._is_connected or self._ws or self._session:
                await self.disconnect()

            if not await self.connect():
                return False, "连接失败", initial_replay_chunks

            # 发送初始请求
            init_result = await self.send_initial_request()
            if init_result and init_result.error:
                return False, init_result.error, initial_replay_chunks

            chunk_count = 0
            recv_count = 0
            stream_error: Optional[str] = None
            session_text = ""
            replay_buffer: list[bytes] = []
            last_voiced_audio_at = 0.0

            def remember_replay_context(chunk: bytes) -> None:
                replay_buffer.append(chunk)
                if len(replay_buffer) > REPLAY_BUFFER_MAX_CHUNKS:
                    del replay_buffer[:len(replay_buffer) - REPLAY_BUFFER_MAX_CHUNKS]

            async def send_regular_chunk(chunk: bytes) -> None:
                nonlocal chunk_count, stream_error, last_voiced_audio_at
                chunk_count += 1
                logger.debug(f"📤 发送音频块 #{chunk_count}: {len(chunk)} bytes")
                remember_replay_context(chunk)
                if self._is_voiced_audio_chunk(chunk):
                    last_voiced_audio_at = time.monotonic()
                if not await self.send_audio_chunk(chunk, is_last=False):
                    stream_error = "发送音频块失败"
                    raise RuntimeError(stream_error)

            async def sender():
                nonlocal audio_exhausted, stream_error
                logger.info("📤 开始发送音频...")

                for chunk in initial_replay_chunks:
                    if stream_error:
                        break
                    await send_regular_chunk(chunk)

                while not stream_error and not audio_exhausted:
                    try:
                        chunk = await audio_iter.__anext__()
                    except StopAsyncIteration:
                        audio_exhausted = True
                        break
                    await send_regular_chunk(chunk)

                if not stream_error and audio_exhausted:
                    logger.info(f"📤 发送完成，共 {chunk_count} 个音频块，发送结束标记")
                    if not await self.send_audio_chunk(b"", is_last=True):
                        stream_error = "发送结束标记失败"
                        raise RuntimeError(stream_error)

            async def receiver():
                nonlocal committed_text, latest_preview_text, recv_count, session_text, stream_error
                logger.info("📥 开始接收结果...")
                last_result_at = time.monotonic()
                while True:
                    result = await self.receive_result(timeout=RECEIVE_POLL_TIMEOUT_SECONDS)
                    if result is None:
                        now = time.monotonic()
                        has_voice_after_last_result = last_voiced_audio_at > last_result_at + 0.2
                        if (
                            (session_text or committed_text)
                            and has_voice_after_last_result
                            and now - last_result_at >= RECEIVE_STALL_TIMEOUT_SECONDS
                        ):
                            stream_error = f"接收结果停滞超时（{RECEIVE_STALL_TIMEOUT_SECONDS}s 无新结果）"
                            break
                        if stream_error:
                            break
                        continue

                    last_result_at = time.monotonic()
                    recv_count += 1
                    logger.debug(f"📥 收到结果 #{recv_count}: definite='{result.definite_text}' pending='{result.pending_text}' final={result.is_final}")

                    if result.error:
                        stream_error = result.error
                        break

                    current_text = result.definite_text + result.pending_text
                    if current_text:
                        session_text = current_text
                        latest_preview_text = self._merge_stream_text(committed_text, session_text)
                        on_preview_text(latest_preview_text)

                    if result.is_final:
                        logger.info(f"📥 接收完成，共收到 {recv_count} 个结果，最终文本: '{session_text}'")
                        break

            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())

            try:
                await sender_task
            except Exception as exc:
                if not stream_error:
                    stream_error = f"发送任务失败: {exc}"

            if stream_error:
                if session_text:
                    committed_text = self._merge_stream_text(committed_text, session_text)
                    latest_preview_text = committed_text
                if not receiver_task.done():
                    receiver_task.cancel()
                    await asyncio.gather(receiver_task, return_exceptions=True)
                return False, stream_error, list(replay_buffer)

            try:
                await asyncio.wait_for(receiver_task, timeout=FINAL_RESPONSE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                stream_error = "等待最终识别结果超时"
                receiver_task.cancel()
                await asyncio.gather(receiver_task, return_exceptions=True)
            except Exception as exc:
                stream_error = f"接收任务异常: {exc}"

            if stream_error:
                if session_text:
                    committed_text = self._merge_stream_text(committed_text, session_text)
                    latest_preview_text = committed_text
                return False, stream_error, list(replay_buffer)

            if session_text:
                committed_text = self._merge_stream_text(committed_text, session_text)
                latest_preview_text = committed_text

            return True, None, []

        try:
            while True:
                success = False
                stream_error: Optional[str] = None
                try:
                    success, stream_error, replay_chunks = await run_one_session(replay_chunks)
                finally:
                    await self.disconnect()

                if success:
                    final_output = latest_preview_text or committed_text
                    if final_output:
                        on_final_text(final_output)
                    on_complete()
                    return

                if (
                    self._is_recoverable_stream_error(stream_error)
                    and reconnect_attempts < MAX_STREAM_RECONNECT_ATTEMPTS
                ):
                    reconnect_attempts += 1
                    logger.warning(
                        "豆包流式连接异常，尝试自动重连 %d/%d: %s",
                        reconnect_attempts,
                        MAX_STREAM_RECONNECT_ATTEMPTS,
                        stream_error,
                    )
                    if replay_chunks:
                        logger.info("将补发最近音频上下文 %d 个块", len(replay_chunks))
                    await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
                    continue

                report_error(stream_error or "流式转录失败")
                return

        except Exception as e:
            report_error(f"处理失败: {e}")
        finally:
            await self.disconnect()


# 测试用的简单命令行入口
async def test_streaming(audio_file: str):
    """测试流式转录"""
    import soundfile as sf
    import numpy as np

    processor = DoubaoStreamingProcessor()

    if not processor.is_available():
        print("请配置 DOUBAO_APP_KEY 和 DOUBAO_ACCESS_KEY 环境变量")
        return

    # 读取音频文件
    audio_data, sample_rate = sf.read(audio_file, dtype='int16')
    if sample_rate != DEFAULT_SAMPLE_RATE:
        print(f"警告: 采样率 {sample_rate} != {DEFAULT_SAMPLE_RATE}")

    # 计算每包的采样点数
    samples_per_chunk = int(DEFAULT_SAMPLE_RATE * SEGMENT_DURATION_MS / 1000)

    async def audio_generator():
        """模拟实时音频流"""
        for i in range(0, len(audio_data), samples_per_chunk):
            chunk = audio_data[i:i + samples_per_chunk]
            yield chunk.tobytes()

    def on_preview(text):
        print(f"\r[预览] {text[:80]}", end="", flush=True)

    def on_final(text):
        print(f"\n[最终] {text}")

    def on_complete():
        print("[完成]")

    def on_error(error):
        print(f"\n[错误] {error}")

    await processor.process_audio_stream(
        audio_generator(),
        on_preview,
        on_final,
        on_complete,
        on_error
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python doubao_streaming.py <音频文件>")
        sys.exit(1)

    asyncio.run(test_streaming(sys.argv[1]))
