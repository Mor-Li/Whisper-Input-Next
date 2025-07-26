import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.audio.recorder import AudioRecorder
from src.keyboard.listener import KeyboardManager, check_accessibility_permissions
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger
from src.transcription.senseVoiceSmall import SenseVoiceSmallProcessor
from src.transcription.local_whisper import LocalWhisperProcessor


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
    def __init__(self, openai_processor, local_processor):
        self.audio_recorder = AudioRecorder()
        self.openai_processor = openai_processor  # OpenAI GPT-4 transcribe
        self.local_processor = local_processor    # 本地 whisper
        self.keyboard_manager = KeyboardManager(
            on_record_start=self.start_openai_recording,    # Ctrl+F: OpenAI
            on_record_stop=self.stop_openai_recording,
            on_translate_start=self.start_translation_recording,  # 保留翻译功能
            on_translate_stop=self.stop_translation_recording,
            on_kimi_start=self.start_local_recording,       # Ctrl+I: Local Whisper
            on_kimi_stop=self.stop_local_recording,
            on_reset_state=self.reset_state
        )
    
    def start_openai_recording(self):
        """开始录音（OpenAI GPT-4 transcribe模式 - Ctrl+F）"""
        self.audio_recorder.start_recording()
    
    def stop_openai_recording(self):
        """停止录音并处理（OpenAI GPT-4 transcribe模式 - Ctrl+F）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
        elif audio:
            result = self.openai_processor.process_audio(
                audio,
                mode="transcriptions",
                prompt=""
            )
            # 解构返回值
            text, error = result if isinstance(result, tuple) else (result, None)
            self.keyboard_manager.type_text(text, error)
        else:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
    
    def start_local_recording(self):
        """开始录音（本地 Whisper 模式 - Ctrl+I）"""
        self.audio_recorder.start_recording()
    
    def stop_local_recording(self):
        """停止录音并处理（本地 Whisper 模式 - Ctrl+I）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
        elif audio:
            result = self.local_processor.process_audio(
                audio,
                mode="transcriptions",
                prompt=""
            )
            # 解构返回值
            text, error = result if isinstance(result, tuple) else (result, None)
            self.keyboard_manager.type_text(text, error)
        else:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
    
    def start_translation_recording(self):
        """开始录音（翻译模式）"""
        self.audio_recorder.start_recording()
    
    def stop_translation_recording(self):
        """停止录音并处理（翻译模式）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
        elif audio:
            result = self.openai_processor.process_audio(  # 使用 OpenAI 进行翻译
                    audio,
                    mode="translations",
                    prompt=""
                )
            text, error = result if isinstance(result, tuple) else (result, None)
            self.keyboard_manager.type_text(text,error)
        else:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
    

    def reset_state(self):
        """重置状态"""
        self.keyboard_manager.reset_state()
    
    def run(self):
        """运行语音助手"""
        logger.info("=== 语音助手已启动 ===")
        self.keyboard_manager.start_listening()

def main():
    # 判断是 OpenAI GPT-4 transcribe 还是 GROQ Whisper 还是 SiliconFlow 还是本地whisper.cpp
    service_platform = os.getenv("SERVICE_PLATFORM", "siliconflow")
    if service_platform == "openai":
        audio_processor = WhisperProcessor()  # 使用 OpenAI GPT-4 transcribe
    elif service_platform == "groq":
        audio_processor = WhisperProcessor()  # 使用 GROQ Whisper
    elif service_platform == "siliconflow":
        audio_processor = SenseVoiceSmallProcessor()
    elif service_platform == "local":
        audio_processor = LocalWhisperProcessor()
    else:
        raise ValueError(f"无效的服务平台: {service_platform}, 支持的平台: openai, groq, siliconflow, local")
    try:
        # 创建 OpenAI 和本地 Whisper 处理器
        original_platform = os.environ.get("SERVICE_PLATFORM")
        
        # 创建 OpenAI 处理器
        os.environ["SERVICE_PLATFORM"] = "openai"
        openai_processor = WhisperProcessor()
        
        # 创建本地 Whisper 处理器
        os.environ["SERVICE_PLATFORM"] = "local"
        local_processor = LocalWhisperProcessor()
        
        # 恢复原始环境变量
        if original_platform:
            os.environ["SERVICE_PLATFORM"] = original_platform
        else:
            os.environ.pop("SERVICE_PLATFORM", None)
        
        assistant = VoiceAssistant(openai_processor, local_processor)
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