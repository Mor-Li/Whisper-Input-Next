import os
import threading
import time
from functools import wraps

import dotenv
import httpx
from openai import OpenAI
from opencc import OpenCC

from ..llm.symbol import SymbolProcessor
from ..llm.kimi import KimiProcessor
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

class WhisperProcessor:
    # 类级别的配置参数
    DEFAULT_TIMEOUT = 20  # API 超时时间（秒）
    DEFAULT_MODEL = None
    
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        base_url = os.getenv("GROQ_BASE_URL")
        self.convert_to_simplified = os.getenv("CONVERT_TO_SIMPLIFIED", "false").lower() == "true"
        self.cc = OpenCC('t2s') if self.convert_to_simplified else None
        self.symbol = SymbolProcessor()
        self.add_symbol = os.getenv("ADD_SYMBOL", "false").lower() == "true"
        self.optimize_result = os.getenv("OPTIMIZE_RESULT", "false").lower() == "true"
        self.timeout_seconds = self.DEFAULT_TIMEOUT
        self.service_platform = os.getenv("SERVICE_PLATFORM", "groq").lower()

        if self.service_platform == "groq":
            assert api_key, "未设置 GROQ_API_KEY 环境变量"
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None
            )
            self.DEFAULT_MODEL = "whisper-large-v3-turbo"
        elif self.service_platform == "siliconflow":
            assert api_key, "未设置 SILICONFLOW_API_KEY 环境变量"
            self.DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"
        else:
            raise ValueError(f"未知的平台: {self.service_platform}")
        
        # 添加Kimi处理器
        self.kimi_processor = KimiProcessor()
        # 是否启用Kimi润色功能（默认关闭，通过快捷键动态控制）
        self.enable_kimi_polish = os.getenv("ENABLE_KIMI_POLISH", "false").lower() == "true"

    def _convert_traditional_to_simplified(self, text):
        """将繁体中文转换为简体中文"""
        if not self.convert_to_simplified or not text:
            return text
        return self.cc.convert(text)
    
    @timeout_decorator(10)
    def _call_whisper_api(self, mode, audio_data, prompt):
        """调用 Whisper API"""
        if mode == "translations":
            response = self.client.audio.translations.create(
                model="whisper-large-v3",
                response_format="text",
                prompt=prompt,
                file=("audio.wav", audio_data)
            )
        else:  # transcriptions
            response = self.client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                response_format="text",
                prompt=prompt,
                file=("audio.wav", audio_data)
            )
        return str(response).strip()

    def process_audio(self, audio_buffer, mode="transcriptions", prompt=""):
        """调用 Whisper API 处理音频（转录或翻译）
        
        Args:
            audio_path: 音频文件路径
            mode: 'transcriptions' 或 'translations'，决定是转录还是翻译
            prompt: 提示词
        
        Returns:
            tuple: (结果文本, 错误信息)
            - 如果成功，错误信息为 None
            - 如果失败，结果文本为 None
        """
        try:
            start_time = time.time()

            logger.info(f"正在调用 Whisper API... (模式: {mode})")
            result = self._call_whisper_api(mode, audio_buffer, prompt)

            logger.info(f"API 调用成功 ({mode}), 耗时: {time.time() - start_time:.1f}秒")
            result = self._convert_traditional_to_simplified(result)
            logger.info(f"识别结果: {result}")
            
            # 使用Kimi润色功能替代原有的标点符号和优化功能
            if self.enable_kimi_polish and result:
                result = self.kimi_processor.polish_text(result)
            else:
                # 如果未启用Kimi润色，则使用原有的处理方式
                # 仅在 groq API 时添加标点符号
                if self.service_platform == "groq" and self.add_symbol:
                    result = self.symbol.add_symbol(result)
                    logger.info(f"添加标点符号: {result}")
                if self.optimize_result:
                    result = self.symbol.optimize_result(result)
                    logger.info(f"优化结果: {result}")

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