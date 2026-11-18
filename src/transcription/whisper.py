import os
import time

from openai import OpenAI
from opencc import OpenCC

from ..utils.logger import logger
from ..utils.timeout import timeout_decorator


class WhisperProcessor:
    """OpenAI gpt-4o-transcribe 批量转录（豆包不可用时 Ctrl+F 走这里）。"""

    TIMEOUT_SECONDS = 180
    DEFAULT_MODEL = "gpt-4o-transcribe"
    service_platform = "openai"

    def __init__(self):
        api_key = os.getenv("OFFICIAL_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("未设置 OFFICIAL_OPENAI_API_KEY 或 OPENAI_API_KEY 环境变量")
        self.client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")

        self.convert_to_simplified = os.getenv("CONVERT_TO_SIMPLIFIED", "false").lower() == "true"
        self.cc = OpenCC('t2s') if self.convert_to_simplified else None

    def _convert_traditional_to_simplified(self, text):
        if not self.convert_to_simplified or not text:
            return text
        return self.cc.convert(text)

    @timeout_decorator(TIMEOUT_SECONDS)
    def _call_api(self, audio_data):
        response = self.client.audio.transcriptions.create(
            model=self.DEFAULT_MODEL,
            response_format="text",
            file=("audio.wav", audio_data),
        )
        return str(response).strip()

    def process_audio(self, audio_buffer):
        """转录一段 WAV 音频。

        Returns:
            tuple: (结果文本, 错误信息)。成功时错误信息为 None，失败时结果文本为 None。
        """
        try:
            start_time = time.time()
            logger.info("正在调用 OpenAI 转录接口...")
            result = self._call_api(audio_buffer)
            logger.info(f"API 调用成功, 耗时: {time.time() - start_time:.1f}秒")
            result = self._convert_traditional_to_simplified(result)
            logger.info(f"识别结果: {result}")
            return result, None
        except TimeoutError:
            error_msg = f"❌ API 请求超时 ({self.TIMEOUT_SECONDS}秒)"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"❌ {str(e)}"
            logger.error(f"音频处理错误: {str(e)}", exc_info=True)
            return None, error_msg
        finally:
            audio_buffer.close()
