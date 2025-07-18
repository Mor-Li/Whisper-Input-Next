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
    def __init__(self, audio_processor):
        self.audio_recorder = AudioRecorder()
        self.audio_processor = audio_processor
        self.keyboard_manager = KeyboardManager(
            on_record_start=self.start_transcription_recording,
            on_record_stop=self.stop_transcription_recording,
            on_translate_start=self.start_translation_recording,
            on_translate_stop=self.stop_translation_recording,
            on_kimi_start=self.start_kimi_recording,
            on_kimi_stop=self.stop_kimi_recording,
            on_reset_state=self.reset_state
        )
    
    def start_transcription_recording(self):
        """开始录音（转录模式）"""
        self.audio_recorder.start_recording()
    
    def stop_transcription_recording(self):
        """停止录音并处理（转录模式）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
        elif audio:
            result = self.audio_processor.process_audio(
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
            result = self.audio_processor.process_audio(
                    audio,
                    mode="translations",
                    prompt=""
                )
            text, error = result if isinstance(result, tuple) else (result, None)
            self.keyboard_manager.type_text(text,error)
        else:
            logger.error("没有录音数据，状态将重置")
            self.keyboard_manager.reset_state()
    
    def start_kimi_recording(self):
        """开始录音（Kimi润色模式）"""
        self.audio_recorder.start_recording()
    
    def stop_kimi_recording(self):
        """停止录音并处理（Kimi润色模式）"""
        audio = self.audio_recorder.stop_recording()
        if audio == "TOO_SHORT":
            logger.warning("录音时长太短，状态将重置")
            self.keyboard_manager.reset_state()
        elif audio:
            # 临时启用Kimi润色功能
            original_kimi_setting = getattr(self.audio_processor, 'enable_kimi_polish', False)
            if hasattr(self.audio_processor, 'enable_kimi_polish'):
                self.audio_processor.enable_kimi_polish = True
            
            result = self.audio_processor.process_audio(
                audio,
                mode="transcriptions",
                prompt=""
            )
            
            # 恢复原始设置
            if hasattr(self.audio_processor, 'enable_kimi_polish'):
                self.audio_processor.enable_kimi_polish = original_kimi_setting
                
            # 解构返回值
            text, error = result if isinstance(result, tuple) else (result, None)
            self.keyboard_manager.type_text(text, error)
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
    # 判断是 Whisper 还是 SiliconFlow 还是本地whisper.cpp
    service_platform = os.getenv("SERVICE_PLATFORM", "siliconflow")
    if service_platform == "groq":
        audio_processor = WhisperProcessor()
    elif service_platform == "siliconflow":
        audio_processor = SenseVoiceSmallProcessor()
    elif service_platform == "local":
        audio_processor = LocalWhisperProcessor()
    else:
        raise ValueError(f"无效的服务平台: {service_platform}, 支持的平台: groq, siliconflow, local")
    try:
        assistant = VoiceAssistant(audio_processor)
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