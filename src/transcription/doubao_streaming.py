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
from typing import Optional, Callable, AsyncGenerator
from dataclasses import dataclass

import aiohttp

from ..utils.logger import logger

# 常量定义
DEFAULT_SAMPLE_RATE = 16000
SEGMENT_DURATION_MS = 200  # 每包音频时长（毫秒）


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
                "result_type": "full"    # 全量返回
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

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        if not self.is_available():
            logger.error("豆包 API Key 未配置")
            return False

        try:
            self._session = aiohttp.ClientSession()
            headers = {
                "X-Api-Resource-Id": "volc.seedasr.sauc.duration",  # 2.0版本小时版
                "X-Api-Connect-Id": str(uuid.uuid4()),
                "X-Api-Access-Key": self.access_key,
                "X-Api-App-Key": self.app_key
            }

            self._ws = await self._session.ws_connect(
                self.ws_url,
                headers=headers
            )
            self._is_connected = True
            self._seq = 1
            logger.info("豆包流式 ASR 连接成功")
            return True
        except Exception as e:
            logger.error(f"连接豆包 ASR 失败: {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        """断开连接"""
        self._is_connected = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None

    async def send_initial_request(self) -> Optional[StreamingResult]:
        """发送初始请求"""
        if not self._ws:
            return StreamingResult(error="未连接")

        try:
            request = self._build_full_client_request()
            await self._ws.send_bytes(request)
            logger.debug("已发送初始请求")

            # 等待响应
            msg = await self._ws.receive()
            if msg.type == aiohttp.WSMsgType.BINARY:
                return self._parse_response(msg.data)
            else:
                return StreamingResult(error=f"意外的响应类型: {msg.type}")
        except Exception as e:
            return StreamingResult(error=f"发送初始请求失败: {e}")

    async def send_audio_chunk(self, chunk: bytes, is_last: bool = False) -> bool:
        """发送音频数据块"""
        if not self._ws:
            return False

        try:
            request = self._build_audio_request(chunk, is_last)
            await self._ws.send_bytes(request)
            return True
        except Exception as e:
            logger.error(f"发送音频块失败: {e}")
            return False

    async def receive_result(self) -> Optional[StreamingResult]:
        """接收识别结果"""
        if not self._ws:
            return None

        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=5.0)
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
        on_definite_text: Callable[[str], None],
        on_pending_text: Callable[[str], None],
        on_complete: Callable[[], None],
        on_error: Callable[[str], None],
        sample_rate: int = DEFAULT_SAMPLE_RATE
    ):
        """
        流式处理音频

        Args:
            audio_chunk_generator: 异步生成器，yield 音频块 (bytes)
            on_definite_text: 收到已确定的文本时调用
            on_pending_text: 收到未确定的文本时调用（用于状态栏预览）
            on_complete: 转录完成时调用
            on_error: 发生错误时调用
            sample_rate: 音频采样率（默认 16000）
        """
        self._sample_rate = sample_rate
        logger.info(f"使用采样率: {sample_rate}Hz")

        if not await self.connect():
            on_error("连接失败")
            return

        try:
            # 发送初始请求
            init_result = await self.send_initial_request()
            if init_result and init_result.error:
                on_error(init_result.error)
                return

            last_definite = ""

            # 启动发送任务
            chunk_count = 0
            async def sender():
                nonlocal chunk_count
                logger.info("📤 开始发送音频...")
                async for chunk in audio_chunk_generator:
                    chunk_count += 1
                    logger.debug(f"📤 发送音频块 #{chunk_count}: {len(chunk)} bytes")
                    await self.send_audio_chunk(chunk, is_last=False)
                    await asyncio.sleep(SEGMENT_DURATION_MS / 1000)
                # 发送最后一包
                logger.info(f"📤 发送完成，共 {chunk_count} 个音频块，发送结束标记")
                await self.send_audio_chunk(b"", is_last=True)

            # 启动接收任务
            recv_count = 0
            async def receiver():
                nonlocal last_definite, recv_count
                logger.info("📥 开始接收结果...")
                while True:
                    result = await self.receive_result()
                    if result is None:
                        continue

                    recv_count += 1
                    logger.debug(f"📥 收到结果 #{recv_count}: definite='{result.definite_text}' pending='{result.pending_text}' final={result.is_final}")

                    if result.error:
                        on_error(result.error)
                        if result.is_final:
                            break
                        continue

                    # 处理 definite 文本（只输入新增部分）
                    if result.definite_text and result.definite_text != last_definite:
                        if result.definite_text.startswith(last_definite):
                            new_part = result.definite_text[len(last_definite):]
                            if new_part:
                                logger.info(f"✅ 新确定文本: '{new_part}'")
                                on_definite_text(new_part)
                        else:
                            logger.info(f"✅ 确定文本: '{result.definite_text}'")
                            on_definite_text(result.definite_text)
                        last_definite = result.definite_text

                    # 处理 pending 文本（显示在状态栏）
                    if result.pending_text:
                        on_pending_text(result.pending_text)

                    if result.is_final:
                        logger.info(f"📥 接收完成，共收到 {recv_count} 个结果")
                        break

            # 并行执行发送和接收
            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())

            await asyncio.gather(sender_task, receiver_task)
            on_complete()

        except Exception as e:
            on_error(f"处理失败: {e}")
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

    def on_definite(text):
        print(f"[确定] {text}", end="", flush=True)

    def on_pending(text):
        print(f"\r[识别中] {text[:50]}...", end="", flush=True)

    def on_complete():
        print("\n[完成]")

    def on_error(error):
        print(f"\n[错误] {error}")

    await processor.process_audio_stream(
        audio_generator(),
        on_definite,
        on_pending,
        on_complete,
        on_error
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python doubao_streaming.py <音频文件>")
        sys.exit(1)

    asyncio.run(test_streaming(sys.argv[1]))
