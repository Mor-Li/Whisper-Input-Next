import os
import threading
import time
from functools import wraps
import glob
import json
from datetime import datetime

import dotenv
import httpx
from openai import OpenAI
from opencc import OpenCC

from ..llm.symbol import SymbolProcessor
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
    DEFAULT_TIMEOUT = 20  # API 超时时间（秒）- GROQ等其他服务
    OPENAI_TIMEOUT = 180  # OpenAI GPT-4o transcribe 超时时间（秒）
    DEFAULT_MODEL = None
    
    def __init__(self):
        self.convert_to_simplified = os.getenv("CONVERT_TO_SIMPLIFIED", "false").lower() == "true"
        self.cc = OpenCC('t2s') if self.convert_to_simplified else None
        self.symbol = SymbolProcessor()
        self.add_symbol = os.getenv("ADD_SYMBOL", "false").lower() == "true"
        self.optimize_result = os.getenv("OPTIMIZE_RESULT", "false").lower() == "true"
        self.service_platform = os.getenv("SERVICE_PLATFORM", "groq").lower()
        self.timeout_seconds = self.OPENAI_TIMEOUT if self.service_platform == "openai" else self.DEFAULT_TIMEOUT

        if self.service_platform == "openai":
            # OpenAI GPT-4o transcribe 配置
            api_key = os.getenv("OFFICIAL_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
            assert api_key, "未设置 OFFICIAL_OPENAI_API_KEY 或 OPENAI_API_KEY 环境变量"
            # 使用官方 OpenAI API
            self.client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
            self.DEFAULT_MODEL = "gpt-4o-transcribe"
        elif self.service_platform == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            base_url = os.getenv("GROQ_BASE_URL")
            assert api_key, "未设置 GROQ_API_KEY 环境变量"
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None
            )
            self.DEFAULT_MODEL = "whisper-large-v3-turbo"
        elif self.service_platform == "siliconflow":
            api_key = os.getenv("GROQ_API_KEY")
            assert api_key, "未设置 SILICONFLOW_API_KEY 环境变量"
            self.DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"
        else:
            raise ValueError(f"未知的平台: {self.service_platform}")
        
        # 创建音频存档目录
        self.audio_archive_dir = "audio_archive"
        self._ensure_archive_directory()

    def _ensure_archive_directory(self):
        """确保音频存档目录存在"""
        if not os.path.exists(self.audio_archive_dir):
            os.makedirs(self.audio_archive_dir)
            logger.info(f"创建音频存档目录: {self.audio_archive_dir}")
    
    def _load_transcription_cache(self):
        """加载转录缓存"""
        cache_path = os.path.join(self.audio_archive_dir, "cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载转录缓存失败: {e}")
        return {}
    
    def _save_transcription_cache(self, cache_data):
        """保存转录缓存"""
        cache_path = os.path.join(self.audio_archive_dir, "cache.json")
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"转录缓存已保存: {cache_path}")
        except Exception as e:
            logger.error(f"保存转录缓存失败: {e}")
    
    def _add_to_cache(self, audio_filename, transcription_result, service_platform):
        """添加转录结果到缓存"""
        cache = self._load_transcription_cache()
        cache[audio_filename] = {
            "transcription": transcription_result,
            "service": service_platform,
            "timestamp": datetime.now().isoformat(),
            "model": self.DEFAULT_MODEL if hasattr(self, 'DEFAULT_MODEL') else "unknown"
        }
        self._save_transcription_cache(cache)

    def _save_audio_to_archive(self, audio_buffer):
        """将音频数据保存到存档目录，并管理文件数量"""
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_filename = f"recording_{timestamp}.wav"
        archive_path = os.path.join(self.audio_archive_dir, archive_filename)
        
        try:
            # 重置缓冲区位置到开始
            audio_buffer.seek(0)
            with open(archive_path, 'wb') as f:
                f.write(audio_buffer.read())
            
            logger.info(f"音频文件已保存到存档: {archive_path}")
            
            # 音频文件已存档，默认保留所有文件
            
            return archive_path
        except Exception as e:
            logger.error(f"保存音频文件到存档失败: {e}")
            return None



    def _convert_traditional_to_simplified(self, text):
        """将繁体中文转换为简体中文"""
        if not self.convert_to_simplified or not text:
            return text
        return self.cc.convert(text)
    
    @timeout_decorator(180)  # OpenAI 专用超时时间
    def _call_openai_api(self, mode, audio_data, prompt):
        """调用 OpenAI GPT-4o transcribe API"""
        if mode == "translations":
            response = self.client.audio.translations.create(
                model="gpt-4o-transcribe",
                response_format="text",
                prompt=prompt,
                file=("audio.wav", audio_data)
            )
        else:  # transcriptions
            response = self.client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                response_format="text",
                prompt=prompt,
                file=("audio.wav", audio_data)
            )
        return str(response).strip()
    
    def _call_whisper_api(self, mode, audio_data, prompt):
        """调用 Whisper API"""
        if self.service_platform == "openai":
            # 使用专用的 OpenAI API 调用（已有180秒超时）
            return self._call_openai_api(mode, audio_data, prompt)
        else:
            # GROQ API 使用10秒超时
            return self._call_groq_api(mode, audio_data, prompt)
    
    @timeout_decorator(10)
    def _call_groq_api(self, mode, audio_data, prompt):
        """调用 GROQ API"""
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

            # 首先保存音频到存档（保留原始录音）
            archive_path = self._save_audio_to_archive(audio_buffer)

            logger.info(f"正在调用 Whisper API... (模式: {mode})")
            result = self._call_whisper_api(mode, audio_buffer, prompt)

            logger.info(f"API 调用成功 ({mode}), 耗时: {time.time() - start_time:.1f}秒")
            result = self._convert_traditional_to_simplified(result)
            logger.info(f"识别结果: {result}")
            
            # OpenAI GPT-4o transcribe 自带标点符号，无需额外处理
            if self.service_platform != "openai":
                # 仅在 groq API 时添加标点符号
                if self.service_platform == "groq" and self.add_symbol:
                    result = self.symbol.add_symbol(result)
                    logger.info(f"添加标点符号: {result}")
                if self.optimize_result:
                    result = self.symbol.optimize_result(result)
                    logger.info(f"优化结果: {result}")

            # 添加转录结果到缓存
            if archive_path:
                audio_filename = os.path.basename(archive_path)
                self._add_to_cache(audio_filename, result, self.service_platform)

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