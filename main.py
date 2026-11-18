import io
import os
import queue
import subprocess
import sys
import threading
import time
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
from src.utils.logger import flush_logs, logger
from src.transcription.local_whisper import LocalWhisperProcessor
from src.transcription.doubao_streaming import DoubaoStreamingProcessor
from src.ui.status_bar import StatusBarController
from src.ui.floating_preview import FloatingPreviewWindow

# 版本信息
__version__ = "3.4.0"
__author__ = "Mor-Li"
__description__ = "macOS 语音输入：豆包流式识别为主，OpenAI 和本地 whisper.cpp 备用"

# 主动请求重启时的退出码。start.sh 里的守护循环看到非 0 退出码就会重新拉起程序。
RESTART_EXIT_CODE = 75
# 请求重启后，最多等这么久让手上的转录收尾，再退出进程（秒）
RESTART_GRACE_SECONDS = 60


@dataclass
class TranscriptionJob:
    audio_bytes: bytes
    processor: str  # "openai" 或 "local"
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
        self._streaming_thread: Optional[threading.Thread] = None
        self._current_streaming_archive_path: Optional[str] = None

        # 根据配置选择 Ctrl+F 的处理方式
        if self.transcription_service == "doubao" and self.doubao_processor:
            self._ctrl_f_start = self.start_doubao_streaming
            self._ctrl_f_stop = self.stop_doubao_streaming
            logger.info("Ctrl+F 使用豆包流式识别")
        else:
            self._ctrl_f_start = self.start_openai_recording
            self._ctrl_f_stop = self.stop_openai_recording
            logger.info("Ctrl+F 使用 OpenAI 批量转录")

        self.keyboard_manager = KeyboardManager(
            on_record_start=self._ctrl_f_start,
            on_record_stop=self._ctrl_f_stop,
            on_local_start=self.start_local_recording,
            on_local_stop=self.stop_local_recording,
            on_state_change=self._on_state_change,
        )

        # 设置自动停止录音的回调
        self.audio_recorder.set_auto_stop_callback(self._handle_auto_stop)

        # 设置设备断开时的回调
        self.audio_recorder.set_device_disconnect_callback(self._handle_device_disconnect)

        # CoreAudio 卡死后本进程再也录不了音，只能重启进程
        self._restart_requested = threading.Event()
        self.audio_recorder.set_wedged_callback(self._on_audio_wedged)

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

        if self._current_state in (InputState.RECORDING, InputState.DOUBAO_STREAMING):
            self._ctrl_f_stop()
        elif self._current_state == InputState.RECORDING_LOCAL:
            self.stop_local_recording()
        else:
            # 非录音状态，只重置
            self.keyboard_manager.reset_state()

    def _on_audio_wedged(self, reason: str):
        """CoreAudio 卡死：等手上的转录收尾后退出进程，由守护循环重新拉起。"""
        if self._restart_requested.is_set():
            return
        self._restart_requested.set()
        logger.error(f"🔁 音频系统卡死（{reason}），将自动重启 Whisper-Input")
        try:
            subprocess.run(
                ["osascript", "-e",
                 'display notification "麦克风卡住了，几秒后自动恢复" with title "Whisper-Input 正在重启"'],
                capture_output=True, timeout=2,
            )
        except Exception:
            pass
        threading.Thread(
            target=self._restart_when_idle, name="restart-when-idle", daemon=True,
        ).start()

    def _restart_when_idle(self):
        deadline = time.time() + RESTART_GRACE_SECONDS
        while time.time() < deadline:
            streaming_busy = self._streaming_thread is not None and self._streaming_thread.is_alive()
            jobs_busy = self.job_queue.unfinished_tasks > 0
            if not streaming_busy and not jobs_busy:
                break
            time.sleep(0.5)
        else:
            logger.warning(f"等待转录收尾超过 {RESTART_GRACE_SECONDS}s，强制重启")
        logger.warning(f"🔁 进程退出（退出码 {RESTART_EXIT_CODE}），由 start.sh 的守护循环重新启动")
        flush_logs()
        # os._exit 不等卡在 CoreAudio 里的线程，也不跑 atexit，所以前面已经手动刷完日志
        os._exit(RESTART_EXIT_CODE)

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
        archive_path: Optional[str] = None,
        max_retries: int = 0,
        attempt: int = 1,
    ) -> None:
        job = TranscriptionJob(
            audio_bytes=audio_bytes,
            processor=processor,
            archive_path=archive_path,
            retries_left=max(0, max_retries),
            attempt=attempt,
        )
        self.job_queue.put(job)
        retry_tag = f" [重试 第{attempt}次]" if attempt > 1 else ""
        logger.info(f"📤 已加入 {processor} 队列{retry_tag}")
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
        logger.info("🎧 开始处理音频 (processor=%s, 尝试 %d)", job.processor, job.attempt)

        processors = {"openai": self.openai_processor, "local": self.local_processor}
        buffer = io.BytesIO(job.audio_bytes)
        try:
            text, error = processors[job.processor].process_audio(buffer)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{job.processor} 转录发生异常: {exc}", exc_info=True)
            self._handle_transcription_failure(job, str(exc))
            return
        finally:
            try:
                buffer.close()
            except Exception:
                pass

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
        )
        self.keyboard_manager.type_text(text)
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
    ) -> None:
        if not archive_path or not transcription_result:
            return
        self.audio_archive.save_transcription_result(
            archive_path,
            transcription_result,
            service=service,
            model=model,
        )

    def _get_job_cache_metadata(self, job: TranscriptionJob) -> tuple[str, str]:
        if job.processor == "openai":
            return "openai", self.openai_processor.DEFAULT_MODEL

        if job.processor == "local":
            model_path = getattr(self.local_processor, "model_path", "")
            model = os.path.basename(model_path) if model_path else "whisper.cpp"
            return "local", model

        return job.processor, "unknown"

    def start_openai_recording(self):
        """开始录音（OpenAI 批量模式，豆包不可用时的 Ctrl+F）"""
        self.audio_recorder.start_recording()

    def stop_openai_recording(self):
        """停止录音并排队转录（OpenAI 批量模式）"""
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
        """开始录音（本地 Whisper 模式 - Ctrl+I）"""
        if self.local_processor is None:
            logger.warning("本地 Whisper 不可用，请使用 Ctrl+F 模式")
            self.keyboard_manager.reset_state()
            return
        self.audio_recorder.start_recording()

    def stop_local_recording(self):
        """停止录音并处理（本地 Whisper 模式 - Ctrl+I）"""
        if self.local_processor is None:
            self.keyboard_manager.reset_state()
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

    def start_doubao_streaming(self):
        """开始豆包流式识别"""
        if self.doubao_processor is None or not self.doubao_processor.is_available():
            logger.warning("豆包流式识别不可用，回退到 OpenAI 模式")
            self.start_openai_recording()
            return

        if self._streaming_thread and self._streaming_thread.is_alive():
            logger.warning("上一轮豆包流式转录仍在清理中，忽略本次启动")
            self.keyboard_manager.reset_state()
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
        latest_preview_text = ""
        text_emitted = False
        stream_failed = False

        def ensure_streaming_archive_path() -> Optional[str]:
            if self._current_streaming_archive_path:
                return self._current_streaming_archive_path

            audio = self.audio_recorder.stop_streaming_recording()
            audio_bytes = self._buffer_to_bytes(audio)
            if audio_bytes:
                self._current_streaming_archive_path = self._archive_audio_bytes(audio_bytes)
            return self._current_streaming_archive_path

        def emit_streaming_text(text: str, reason: str) -> bool:
            nonlocal text_emitted
            text = (text or "").strip()
            if not text or text_emitted:
                return False

            text_emitted = True
            logger.info(f"[最终输入:{reason}] {text}")
            archive_path = ensure_streaming_archive_path()
            self._save_transcription_cache(
                archive_path,
                text,
                service="doubao",
                model="bigmodel",
            )
            self.keyboard_manager.type_text(text)
            return True

        def on_preview_text(text: str):
            """收到文本更新，显示在浮动预览窗口（不输入到目标应用）"""
            nonlocal latest_preview_text
            if text:
                latest_preview_text = text
            self.floating_preview.update_text(text)

        def on_final_text(text: str):
            """流式结束，一次性输入最终文本到目标应用"""
            if stream_failed:
                return
            emit_streaming_text(text, "final")

        def on_complete():
            """转录完成"""
            if stream_failed:
                return
            logger.info("✅ 豆包流式转录完成")
            self.floating_preview.hide()
            # 不在这里 stop_streaming_recording——按键 / auto_stop / disconnect 路径
            # 已经负责把 recording 翻 False 并把 stream 关掉，重复调会和按键线程争锁
            self.keyboard_manager.reset_state()

        def on_error(error: str):
            """发生错误"""
            nonlocal stream_failed
            if stream_failed:
                return
            stream_failed = True
            recovery_text = latest_preview_text.strip()
            recovery_emitted = False
            logger.error(f"❌ 豆包流式转录错误: {error}")
            if recovery_text:
                logger.warning("豆包流式异常，输出本轮最新预览文本以避免丢稿")
                recovery_emitted = emit_streaming_text(recovery_text, f"error:{error}")
            self.floating_preview.hide()
            self.audio_recorder.reset_streaming_state(reason=f"豆包流式错误: {error}")
            self.keyboard_manager.reset_state()
            if recovery_emitted:
                self.keyboard_manager.keep_clipboard_text(recovery_text)

        # 豆包 API 只支持 16000Hz，stream_audio_chunks 会自动重采样
        processor = DoubaoStreamingProcessor()
        try:
            await processor.process_audio_stream(
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

        # 正常情况下由流式线程在收尾时 reset_state。流式线程根本没起来时
        # （比如开流失败或卡死），没人会把状态拉回空闲，图标会一直停在"处理中"。
        if not (self._streaming_thread and self._streaming_thread.is_alive()):
            logger.warning("流式转录线程未在运行，直接恢复空闲状态")
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
        # OpenAI 批量转录：豆包不可用时 Ctrl+F 用它
        try:
            openai_processor = WhisperProcessor()
        except ValueError as e:
            logger.warning(f"OpenAI 转录不可用: {e}")
            openai_processor = None

        # 本地 whisper.cpp（Ctrl+I），没装就禁用
        try:
            local_processor = LocalWhisperProcessor()
        except FileNotFoundError as e:
            logger.warning(f"本地 Whisper 不可用，将禁用本地转录功能: {e}")
            local_processor = None

        # 豆包流式识别（Ctrl+F 默认），没配密钥就退回 OpenAI
        doubao_processor = DoubaoStreamingProcessor()
        if not doubao_processor.is_available():
            logger.warning("豆包流式 ASR 不可用（未配置 API Key），将使用 OpenAI 作为默认转录服务")
            doubao_processor = None
        if doubao_processor is None and openai_processor is None:
            raise RuntimeError("豆包和 OpenAI 的密钥都没有配置，请在 .env 里至少配置一个")

        assistant = VoiceAssistant(openai_processor, local_processor, doubao_processor)
        assistant.run()
    except Exception as e:
        error_msg = str(e)
        if "Input event monitoring will not be possible" in error_msg:
            check_accessibility_permissions()
        elif "无法访问音频设备" in error_msg:
            check_microphone_permissions()
        else:
            logger.error(f"发生错误: {error_msg}", exc_info=True)
        flush_logs()
        sys.exit(1)


if __name__ == "__main__":
    main()
