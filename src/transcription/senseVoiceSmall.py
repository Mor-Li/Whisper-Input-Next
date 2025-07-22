import os
import threading
import time
from functools import wraps

import dotenv
import httpx

from src.llm.translate import TranslateProcessor
from src.llm.kimi import KimiProcessor
from ..utils.logger import logger

dotenv.load_dotenv()

def timeout_decorator(seconds):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            error = [None]
            completed = threading.Event()

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    error[0] = e
                finally:
                    completed.set()

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()

            if completed.wait(seconds):
                if error[0] is not None:
                    raise error[0]
                return result[0]
            raise TimeoutError(f"操作超时 ({seconds}秒)")

        return wrapper
    return decorator

class SenseVoiceSmallProcessor:
    # 类级别的配置参数
    DEFAULT_TIMEOUT = 20  # API 超时时间（秒）
    DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"
    
    def __init__(self):
        api_key = os.getenv("SILICONFLOW_API_KEY")
        assert api_key, "未设置 SILICONFLOW_API_KEY 环境变量"
        
        self.convert_to_simplified = os.getenv("CONVERT_TO_SIMPLIFIED", "false").lower() == "true"
        # self.cc = OpenCC('t2s') if self.convert_to_simplified else None
        # self.symbol = SymbolProcessor()
        # self.add_symbol = os.getenv("ADD_SYMBOL", "false").lower() == "true"
        # self.optimize_result = os.getenv("OPTIMIZE_RESULT", "false").lower() == "true"
        self.timeout_seconds = self.DEFAULT_TIMEOUT
        self.translate_processor = TranslateProcessor()
        self.kimi_processor = KimiProcessor()
        # 是否启用Kimi润色功能（默认关闭，通过快捷键动态控制）
        self.enable_kimi_polish = os.getenv("ENABLE_KIMI_POLISH", "false").lower() == "true"

    def _convert_traditional_to_simplified(self, text):
        """将繁体中文转换为简体中文"""
        if not self.convert_to_simplified or not text:
            return text
        return self.cc.convert(text)

    @timeout_decorator(10)
    def _call_api(self, audio_data):
        """调用硅流 API"""
        transcription_url = "https://api.siliconflow.cn/v1/audio/transcriptions"
        
        files = {
            'file': ('audio.wav', audio_data),
            'model': (None, self.DEFAULT_MODEL)
        }

        headers = {
            'Authorization': f"Bearer {os.getenv('SILICONFLOW_API_KEY')}"
        }

        with httpx.Client() as client:
            response = client.post(transcription_url, files=files, headers=headers)
            response.raise_for_status()
            return response.json().get('text', '获取失败')


    def process_audio(self, audio_buffer, mode="transcriptions", prompt=""):
        """处理音频（转录或翻译）
        
        Args:
            audio_buffer: 音频数据缓冲
            mode: 'transcriptions' 或 'translations'，决定是转录还是翻译
        
        Returns:
            tuple: (结果文本, 错误信息)
            - 如果成功，错误信息为 None
            - 如果失败，结果文本为 None
        """
        try:
            start_time = time.time()
            
            logger.info(f"正在调用 硅基流动 API... (模式: {mode})")
            result = self._call_api(audio_buffer)

            logger.info(f"API 调用成功 ({mode}), 耗时: {time.time() - start_time:.1f}秒")
            # result = self._convert_traditional_to_simplified(result)
            if mode == "translations":
                result = self.translate_processor.translate(result)
            logger.info(f"识别结果: {result}")
            
            # 如果启用Kimi润色功能，对结果进行润色
            if self.enable_kimi_polish and result:
                result = self.kimi_processor.polish_text(result)

            return result, None

        except TimeoutError:
            error_msg = f"❌ API 请求超时 ({self.timeout_seconds}秒)"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"❌ {str(e)}"
            logger.error(f"音频处理错误: {str(e)}", exc_info=True)
            return None, error_msg
        finally:
            audio_buffer.close()  # 显式关闭字节流
