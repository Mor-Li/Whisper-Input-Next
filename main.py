import io
import os
import queue
import sys
import threading
import asyncio
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from src.audio.recorder import AudioRecorder
from src.audio.archive import AudioArchiveManager
from src.keyboard.listener import KeyboardManager, check_accessibility_permissions
from src.keyboard.inputState import InputState
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger
from src.transcription.local_whisper import LocalWhisperProcessor
from src.transcription.doubao_streaming import DoubaoStreamingProcessor
from src.ui.status_bar import StatusBarController
from src.ui.floating_preview import FloatingPreviewWindow

# 版本信息
__version__ = "3.3.0"
__author__ = "Mor-Li"
__description__ = "Enhanced Voice Transcription Tool with OpenAI GPT-4o Transcribe"


@dataclass
class TranscriptionJob:
    audio_bytes: bytes
    processor: str
    mode: str = "transcriptions"
    archive_path: Optional[str] = None
    retries_left: int = 0
    attempt: int = 1


def check_microphone_permissions():
    """检查麦克风权限并提供指导"""
    logger.warning("\n=== macOS 麦克风权限检查 ===")
    logger.warning("此应用需要麦克风权限才能进行录音。")
    logger.warning("\n请按照以下步骤授予权限：")
    logger.warning("1. 打开 系统偏好设置")
    logger.warning("2. 点击 隐私与安全性")
    logger.warning("3. 点击左侧的 麦克风")
    logger.warning("4. 点击右下角的锁图标并输入密码")
    logger.warning("5. 在右侧列表中找到 Terminal（或者您使用的终端应用）并勾选")
    logger.warning("\n授权后，请重新运行此程序。")
    logger.warning("===============================\n")

class VoiceAssistant:
    def __init__(self, openai_processor, local_processor, doubao_processor):
        self.audio_recorder = AudioRecorder()
        self.audio_archive = AudioArchiveManager()
        self.openai_processor = openai_processor  # OpenAI GPT-4o transcribe
        self.local_processor = local_processor    # 本地 whisper
        self.doubao_processor = doubao_processor  # 豆包流式 ASR
        self.job_queue: queue.Queue[TranscriptionJob] = queue.Queue()
        self._current_state = InputState.IDLE

        self.status_controller = StatusBarController()
        self.floating_preview = FloatingPreviewWindow()
        self.max_auto_retries = int(os.getenv("AUTO_RETRY_LIMIT", "5"))

        # 转录服务配置: "doubao" (默认，流式) 或 "openai" (批量)
        self.transcription_service = os.getenv("TRANSCRIPTION_SERVICE", "doubao")

        # 流式转录相关
        self._streaming_task: Optional[asyncio.Task] = None
        self._streaming_loop: Optional[asyncio.AbstractEventLoop] = None
        self._streaming_thread: Optional[threading.Thread] = None
        self._current_streaming_archive_path: Optional[str] = None

        # 根据配置选择默认转录快捷键的处理方式
        if self.transcription_service == "doubao" and self.doubao_processor and self.doubao_processor.is_available():
            default_transcription_start = self.start_doubao_streaming
            default_transcription_stop = self.stop_doubao_streaming
            logger.info("默认转录快捷键使用豆包流式识别")
        elif self.openai_processor is not None:
            default_transcription_start = self.start_openai_recording
            default_transcription_stop = self.stop_openai_recording
            logger.info("默认转录快捷键使用 OpenAI 批量转录")
        else:
            default_transcription_start = self._show_transcription_unavailable
            default_transcription_stop = self._show_transcription_unavailable
            logger.warning("默认转录快捷键不可用：豆包和 OpenAI 均未配置")

        self.keyboard_manager = KeyboardManager(
            on_record_start=default_transcription_start,
            on_record_stop=default_transcription_stop,
            on_translate_start=self.start_translation_recording,  # 保留翻译功能
            on_translate_stop=self.stop_translation_recording,
            on_kimi_start=self.start_local_recording,       # 修饰键+I: Local Whisper
            on_kimi_stop=self.stop_local_recording,
            on_reset_state=self.reset_state,
            on_state_change=self._on_state_change,
        )

        # 使用状态栏反馈状态，不再向输入框输出"0"/"1"
        self.keyboard_manager.set_state_symbol_enabled(False)

        # 设置自动停止录音的回调
        self.audio_recorder.set_auto_stop_callback(self._handle_auto_stop)

        # 设置设备断开时的回调
        self.audio_recorder.set_device_disconnect_callback(self._handle_device_disconnect)

        # 后台转录线程
        self._worker_thread = threading.Thread(
            target=self._job_worker,
            name="transcription-worker",
            daemon=True,
        )
        self._worker_thread.start()

        # 初始化状态栏显示
        self._notify_status()

    def _handle_auto_stop(self):
        """处理自动停止录音的情况"""
        logger.warning("⏰ 录音时间已达到最大限制，自动中止录音！")

        # 中止录音（不进行转录）
        if self._current_state == InputState.DOUBAO_STREAMING:
            self.audio_recorder.stop_streaming_recording(abort=True)
        else:
            self.audio_recorder.stop_recording(abort=True)

        # 重置键盘状态
        self.keyboard_manager.reset_state()

        logger.info("💡 录音已中止，状态已重置")

    def _handle_device_disconnect(self):
        """处理设备断开时的录音停止（保存并转录已录制内容）"""
        logger.warning("设备断开，触发停止录音并转录")

        # 根据当前状态调用相应的 stop 方法
        if (
            self._current_state == InputState.RECORDING
            and self.transcription_service == "doubao"
            and self.doubao_processor
            and self.doubao_processor.is_available()
        ):
            self.stop_doubao_streaming()
        elif self._current_state == InputState.RECORDING:
            self.stop_openai_recording()
        elif self._current_state == InputState.RECORDING_TRANSLATE:
            self.stop_translation_recording()
        elif self._current_state == InputState.RECORDING_KIMI:
            self.stop_local_recording()
        elif self._current_state == InputState.DOUBAO_STREAMING:
            self.stop_doubao_streaming()
        else:
            # 非录音状态，只重置
            self.keyboard_manager.reset_state()

    def _on_state_change(self, new_state: InputState):
        self._current_state = new_state
        self._notify_status()

    def _notify_status(self):
        queue_length = self.job_queue.qsize()
        try:
            self.status_controller.update_state(
                self._current_state,
                queue_length=queue_length,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"更新状态栏失败: {exc}")

    def _show_transcription_unavailable(self):
        logger.error("转录服务不可用：请配置豆包或 OpenAI")
        self.status_controller.show_error("转录服务不可用")
        self.keyboard_manager.reset_state()

    def _buffer_to_bytes(self, audio_buffer: Optional[io.BytesIO]) -> Optional[bytes]:
        if audio_buffer is None:
            return None
        try:
            audio_buffer.seek(0)
            return audio_buffer.read()
        finally:
            try:
                audio_buffer.close()
            except Exception:
                pass

    def _queue_job(
        self,
        audio_bytes: bytes,
        processor: str,
        *,
        mode: str = "transcriptions",
        archive_path: Optional[str] = None,
        max_retries: int = 0,
        attempt: int = 1,
    ) -> None:
        job = TranscriptionJob(
            audio_bytes=audio_bytes,
            processor=processor,
            mode=mode,
            archive_path=archive_path,
            retries_left=max(0, max_retries),
            attempt=attempt,
        )
        self.job_queue.put(job)
        retry_tag = f" [重试 第{attempt}次]" if attempt > 1 else ""
        logger.info(f"📤 已加入 {processor} 队列 (mode: {mode}){retry_tag}")
        self._notify_status()

    def _job_worker(self):
        while True:
            job = self.job_queue.get()
            try:
                self._run_job(job)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"转录任务处理失败: {exc}", exc_info=True)
            finally:
                self.job_queue.task_done()
                self._notify_status()

    def _run_job(self, job: TranscriptionJob):
        logger.info(
            "🎧 开始处理音频 (processor=%s, mode=%s, 尝试 %d)",
            job.processor,
            job.mode,
            job.attempt,
        )

        buffer = io.BytesIO(job.audio_bytes)
        try:
            if job.processor == "openai":
                if self.openai_processor is None:
                    raise RuntimeError("OpenAI 转录服务未配置")
                processor_result = self.openai_processor.process_audio(
                    buffer,
                    mode=job.mode,
                    prompt="",
                    archive_path=job.archive_path,
                )
            elif job.processor == "local":
                if self.local_processor is None:
                    raise RuntimeError("本地 Whisper 不可用")
                processor_result = self.local_processor.process_audio(
                    buffer,
                    mode=job.mode,
                    prompt="",
                    archive_path=job.archive_path,
                )
            else:
                raise ValueError(f"未知的处理器: {job.processor}")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{job.processor} 转录发生异常: {exc}", exc_info=True)
            self._handle_transcription_failure(job, str(exc))
            return
        finally:
            try:
                buffer.close()
            except Exception:
                pass

        text, error = (
            processor_result
            if isinstance(processor_result, tuple)
            else (processor_result, None)
        )

        if error:
            logger.error(f"{job.processor} 转录失败: {error}")
            self._handle_transcription_failure(job, str(error))
            return

        service, model = self._get_job_cache_metadata(job)
        self._save_transcription_cache(
            job.archive_path,
            text,
            service=service,
            model=model,
            mode=job.mode,
        )
        self.keyboard_manager.type_text(text, error)
        logger.info(f"✅ 转录成功 (尝试 {job.attempt})")
        self._notify_status()

    def _handle_transcription_failure(self, job: TranscriptionJob, error_message: str):
        if job.retries_left > 0:
            logger.warning(
                "⚠️ %s 转录失败 (尝试 %d)，将在 %d 次内自动重试",
                job.processor,
                job.attempt,
                job.retries_left,
            )
            self._schedule_retry(job)
            self._notify_status()
            return

        logger.error(
            "❌ %s 转录失败 (尝试 %d)，自动重试已用尽: %s",
            job.processor,
            job.attempt,
            error_message,
        )
        self.keyboard_manager.show_error("❌ 自动转录失败")
        self._notify_status()

    def _schedule_retry(self, job: TranscriptionJob):
        next_retries = max(0, job.retries_left - 1)
        self._queue_job(
            job.audio_bytes,
            job.processor,
            mode=job.mode,
            archive_path=job.archive_path,
            max_retries=next_retries,
            attempt=job.attempt + 1,
        )

    def _archive_audio_bytes(self, audio_bytes: Optional[bytes]) -> Optional[str]:
        if not audio_bytes:
            return None
        return self.audio_archive.save_audio_bytes(audio_bytes)

    def _save_transcription_cache(
        self,
        archive_path: Optional[str],
        transcription_result: Optional[str],
        *,
        service: str,
        model: str,
        mode: str = "transcriptions",
    ) -> None:
        if not archive_path or not transcription_result:
            return
        self.audio_archive.save_transcription_result(
            archive_path,
            transcription_result,
            service=service,
            model=model,
            mode=mode,
        )

    def _get_job_cache_metadata(self, job: TranscriptionJob) -> tuple[str, str]:
        if job.processor == "openai":
            service = getattr(self.openai_processor, "service_platform", "openai")
            model = getattr(self.openai_processor, "DEFAULT_MODEL", "unknown") or "unknown"
            return service, model

        if job.processor == "local":
            model_path = getattr(self.local_processor, "model_path", "")
            model = os.path.basename(model_path) if model_path else "whisper.cpp"
            return "local", model

        return job.processor, "unknown"

    def start_openai_recording(self):
        """开始录音（OpenAI GPT-4o transcribe 模式）"""
        if self.openai_processor is None:
            logger.warning("OpenAI 转录不可用，请配置 OFFICIAL_OPENAI_API_KEY 或使用豆包")
            self.status_controller.show_error("OpenAI 转录不可用")
            self.keyboard_manager.reset_state()
            return
        self.audio_recorder.start_recording()

    def stop_openai_recording(self):
        """停止录音并处理（OpenAI GPT-4o transcribe 模式）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
            return

        audio_bytes = self._buffer_to_bytes(audio)
        if not audio_bytes:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
            return

        archive_path = self._archive_audio_bytes(audio_bytes)
        self._queue_job(
            audio_bytes,
            "openai",
            archive_path=archive_path,
            max_retries=self.max_auto_retries,
        )

    def start_local_recording(self):
        """开始录音（本地 Whisper 模式）"""
        if self.local_processor is None:
            logger.warning("本地 Whisper 不可用，请使用默认转录快捷键")
            self.status_controller.show_error("Local Whisper 不可用")
            return
        self.audio_recorder.start_recording()

    def stop_local_recording(self):
        """停止录音并处理（本地 Whisper 模式）"""
        if self.local_processor is None:
            return
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
            return

        audio_bytes = self._buffer_to_bytes(audio)
        if not audio_bytes:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
            return

        archive_path = self._archive_audio_bytes(audio_bytes)
        self._queue_job(audio_bytes, "local", archive_path=archive_path)

    def start_translation_recording(self):
        """开始录音（翻译模式）"""
        if self.openai_processor is None:
            logger.warning("翻译模式需要 OpenAI，请配置 OFFICIAL_OPENAI_API_KEY")
            self.status_controller.show_error("翻译模式需要 OpenAI")
            self.keyboard_manager.reset_state()
            return
        self.audio_recorder.start_recording()

    def stop_translation_recording(self):
        """停止录音并处理（翻译模式）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
            return

        audio_bytes = self._buffer_to_bytes(audio)
        if not audio_bytes:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
            return

        archive_path = self._archive_audio_bytes(audio_bytes)
        self._queue_job(
            audio_bytes,
            "openai",
            mode="translations",
            archive_path=archive_path,
            max_retries=self.max_auto_retries,
        )

    def start_doubao_streaming(self):
        """开始豆包流式识别"""
        if self.doubao_processor is None or not self.doubao_processor.is_available():
            logger.warning("豆包流式识别不可用，回退到 OpenAI 模式")
            self.start_openai_recording()
            return

        # 启动流式录音（recorder 内部会处理残留状态）
        error = self.audio_recorder.start_streaming_recording()
        if error:
            logger.error(f"启动流式录音失败: {error}")
            self.keyboard_manager.reset_state()
            return

        self._current_streaming_archive_path = None
        self._current_state = InputState.DOUBAO_STREAMING
        self._notify_status()

        # 在新线程中运行异步流式转录
        def run_streaming():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._streaming_loop = loop

            try:
                loop.run_until_complete(self._run_doubao_streaming())
            except Exception as e:
                logger.error(f"流式转录异常: {e}", exc_info=True)
            finally:
                loop.close()
                self._streaming_loop = None
                if self._streaming_thread is threading.current_thread():
                    self._streaming_thread = None

        self._streaming_thread = threading.Thread(
            target=run_streaming,
            name="doubao-streaming",
            daemon=True,
        )
        self._streaming_thread.start()

    async def _run_doubao_streaming(self):
        """运行豆包流式转录"""
        logger.info("🎤 开始豆包流式转录...")

        # 显示浮动预览窗口
        self.floating_preview.show()

        def on_preview_text(text: str):
            """收到文本更新，显示在浮动预览窗口（不输入到目标应用）"""
            self.floating_preview.update_text(text)

        def on_final_text(text: str):
            """流式结束，一次性输入最终文本到目标应用"""
            if text:
                logger.info(f"[最终输入] {text}")
                self._save_transcription_cache(
                    self._current_streaming_archive_path,
                    text,
                    service="doubao",
                    model="bigmodel",
                    mode="transcriptions",
                )
                self.keyboard_manager.type_text(text, None)

        def on_complete():
            """转录完成"""
            logger.info("✅ 豆包流式转录完成")
            self.floating_preview.hide()
            self.audio_recorder.stop_streaming_recording()
            self.keyboard_manager.reset_state()

        def on_error(error: str):
            """发生错误"""
            logger.error(f"❌ 豆包流式转录错误: {error}")
            self.floating_preview.hide()
            self.audio_recorder.reset_streaming_state(reason=f"豆包流式错误: {error}")
            self.keyboard_manager.reset_state()

        # 豆包 API 只支持 16000Hz，stream_audio_chunks 会自动重采样
        try:
            await self.doubao_processor.process_audio_stream(
                self.audio_recorder.stream_audio_chunks(target_sample_rate=16000),
                on_preview_text,
                on_final_text,
                on_complete,
                on_error,
                sample_rate=16000,
            )
        except Exception as exc:
            self.audio_recorder.reset_streaming_state(reason=f"豆包流式运行异常: {exc}")
            self.keyboard_manager.reset_state()
            raise

    def stop_doubao_streaming(self):
        """停止豆包流式识别"""
        logger.info("🛑 停止豆包流式转录...")
        self.floating_preview.hide()
        audio = self.audio_recorder.stop_streaming_recording()
        audio_bytes = self._buffer_to_bytes(audio)
        if audio_bytes:
            self._current_streaming_archive_path = self._archive_audio_bytes(audio_bytes)

    def reset_state(self):
        """重置状态"""
        self.keyboard_manager.reset_state()
    
    def run(self):
        """运行语音助手"""
        logger.info(f"=== 语音助手已启动 (v{__version__}) ===")
        keyboard_thread = threading.Thread(
            target=self.keyboard_manager.start_listening,
            name="keyboard-listener",
            daemon=True,
        )
        keyboard_thread.start()

        # 阻塞在状态栏事件循环，直到用户退出
        self.status_controller.start()

def main():
    try:
        # 创建三处理器架构：OpenAI + 本地 Whisper + 豆包流式
        original_platform = os.environ.get("SERVICE_PLATFORM")

        # 创建 OpenAI 处理器
        os.environ["SERVICE_PLATFORM"] = "openai"
        try:
            openai_processor = WhisperProcessor()
        except (AssertionError, ValueError) as e:
            logger.warning(f"OpenAI 转录不可用，将禁用批量/翻译模式: {e}")
            openai_processor = None

        # 创建本地 Whisper 处理器（可选，如果不可用则跳过）
        os.environ["SERVICE_PLATFORM"] = "local"
        try:
            local_processor = LocalWhisperProcessor()
        except FileNotFoundError as e:
            logger.warning(f"本地 Whisper 不可用，将禁用本地转录功能: {e}")
            local_processor = None

        # 创建豆包流式处理器（可选，如果 API Key 未配置则跳过）
        doubao_processor = DoubaoStreamingProcessor()
        if not doubao_processor.is_available():
            logger.warning("豆包流式 ASR 不可用（未配置 API Key），将使用 OpenAI 作为默认转录服务")
            doubao_processor = None

        # 恢复原始环境变量
        if original_platform:
            os.environ["SERVICE_PLATFORM"] = original_platform
        else:
            os.environ.pop("SERVICE_PLATFORM", None)

        assistant = VoiceAssistant(openai_processor, local_processor, doubao_processor)
        assistant.run()
    except Exception as e:
        error_msg = str(e)
        if "Input event monitoring will not be possible" in error_msg:
            check_accessibility_permissions()
            sys.exit(1)
        elif "无法访问音频设备" in error_msg:
            check_microphone_permissions()
            sys.exit(1)
        else:
            logger.error(f"发生错误: {error_msg}", exc_info=True)
            sys.exit(1)

if __name__ == "__main__":
    main()
