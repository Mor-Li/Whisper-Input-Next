import os
import subprocess
import json
import tempfile
import threading
import time
from functools import wraps
import glob
from datetime import datetime

import dotenv

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

class LocalWhisperProcessor:
    # 类级别的配置参数
    DEFAULT_TIMEOUT = 180  # 修改为180秒（3分钟）
    
    def __init__(self):
        # 从环境变量获取whisper.cpp路径和模型路径
        self.whisper_cli_path = os.getenv("WHISPER_CLI_PATH", "/Users/limo/Documents/GithubRepo/whisper.cpp/build/bin/whisper-cli")
        self.model_path = os.getenv("WHISPER_MODEL_PATH", "models/ggml-large-v3.bin")
        
        # 检查whisper.cpp可执行文件是否存在
        if not os.path.exists(self.whisper_cli_path):
            raise FileNotFoundError(f"Whisper CLI 未找到: {self.whisper_cli_path}")
        
        # 检查模型文件是否存在
        # 如果是绝对路径直接使用，否则相对于whisper.cpp根目录
        if os.path.isabs(self.model_path):
            full_model_path = self.model_path
        else:
            # whisper_cli_path: /path/to/whisper.cpp/build/bin/whisper-cli
            # 需要向上3级目录到whisper.cpp根目录
            whisper_root = os.path.dirname(os.path.dirname(os.path.dirname(self.whisper_cli_path)))
            full_model_path = os.path.join(whisper_root, self.model_path)
        
        if not os.path.exists(full_model_path):
            raise FileNotFoundError(f"Whisper 模型未找到: {full_model_path}")
        
        self.timeout_seconds = self.DEFAULT_TIMEOUT
        self.translate_processor = TranslateProcessor()
        self.kimi_processor = KimiProcessor()
        # 是否启用Kimi润色功能（默认关闭，通过快捷键动态控制）
        self.enable_kimi_polish = os.getenv("ENABLE_KIMI_POLISH", "false").lower() == "true"
        
        # 创建音频存档目录
        self.audio_archive_dir = "audio_archive"
        self._ensure_archive_directory()

    def _ensure_archive_directory(self):
        """确保音频存档目录存在"""
        if not os.path.exists(self.audio_archive_dir):
            os.makedirs(self.audio_archive_dir)
            logger.info(f"创建音频存档目录: {self.audio_archive_dir}")

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


    def _save_audio_to_temp_file(self, audio_buffer):
        """将音频数据保存到临时WAV文件"""
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        try:
            # 重置缓冲区位置到开始
            audio_buffer.seek(0)
            temp_file.write(audio_buffer.read())
            temp_file.flush()
            return temp_file.name
        finally:
            temp_file.close()

    @timeout_decorator(180)  # 修改为180秒（3分钟）
    def _call_whisper_cpp(self, wav_file):
        """调用本地whisper.cpp进行转录"""
        # 创建临时文件作为输出前缀
        prefix = tempfile.NamedTemporaryFile(delete=False).name
        
        try:
            # 处理模型路径
            if os.path.isabs(self.model_path):
                model_path = self.model_path
            else:
                # 相对于whisper.cpp根目录
                whisper_root = os.path.dirname(os.path.dirname(os.path.dirname(self.whisper_cli_path)))
                model_path = os.path.join(whisper_root, self.model_path)
            
            # 构建命令
            cmd = [
                self.whisper_cli_path,
                "-m", model_path,
                "-f", wav_file,
                "-l", "auto",          # 自动检测中/英/粤
                "-fa",                 # Flash-Attention
                "--beam-size", "5", 
                "--best-of", "5",
                "-ojf",                # verbose JSON
                "-of", prefix, 
                "--no-prints",
            ]
            
            logger.info(f"执行whisper.cpp命令: {' '.join(cmd)}")
            
            # 执行命令
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            # 读取JSON结果文件
            json_file = prefix + ".json"
            if not os.path.exists(json_file):
                raise FileNotFoundError(f"输出JSON文件未找到: {json_file}")
            
            # 使用latin1编码读取JSON文件
            data = None
            try:
                with open(json_file, encoding="latin1") as f:
                    data = json.load(f)
                logger.info("成功使用 latin1 编码读取文件")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.warning(f"使用 latin1 编码失败: {e}")
                logger.info("尝试以二进制方式读取...")
                with open(json_file, "rb") as f:
                    content = f.read()
                    try:
                        content_str = content.decode("latin1", errors="replace")
                        data = json.loads(content_str)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON解析失败: {e}")
                        logger.error(f"文件内容预览: {content[:500]}")
                        raise
            
            # 从转录结果中提取纯文字
            full_txt = ""
            if "transcription" in data:
                segments = data["transcription"]
                if isinstance(segments, list):
                    text_parts = []
                    for seg in segments:
                        if "text" in seg:
                            text = seg["text"]
                            # 修复编码问题：将latin1编码的字符串重新解码为UTF-8
                            try:
                                if isinstance(text, str):
                                    text = text.encode('latin1').decode('utf-8')
                            except (UnicodeEncodeError, UnicodeDecodeError):
                                pass
                            text_parts.append(text)
                    full_txt = "".join(text_parts)
            
            return full_txt.strip()
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(prefix + ".json"):
                    os.unlink(prefix + ".json")
                if os.path.exists(prefix + ".txt"):
                    os.unlink(prefix + ".txt")
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")

    def process_audio(self, audio_buffer, mode="transcriptions", prompt=""):
        """处理音频（转录或翻译）
        
        Args:
            audio_buffer: 音频数据缓冲
            mode: 'transcriptions' 或 'translations'，决定是转录还是翻译
            prompt: 提示词（暂不支持）
        
        Returns:
            tuple: (结果文本, 错误信息)
            - 如果成功，错误信息为 None
            - 如果失败，结果文本为 None
        """
        wav_file = None
        try:
            start_time = time.time()
            
            logger.info(f"正在使用本地 whisper.cpp 处理音频... (模式: {mode})")
            
            # 首先保存音频到存档（保留原始录音）
            archive_path = self._save_audio_to_archive(audio_buffer)
            
            # 保存音频到临时文件用于处理
            wav_file = self._save_audio_to_temp_file(audio_buffer)
            
            # 调用whisper.cpp进行转录
            result = self._call_whisper_cpp(wav_file)
            
            logger.info(f"本地处理成功 ({mode}), 耗时: {time.time() - start_time:.1f}秒")
            logger.info(f"转录结果: {result}")
            
            # 如果启用Kimi润色功能，对转录结果进行润色
            if self.enable_kimi_polish and result:
                result = self.kimi_processor.polish_text(result)
            
            # 如果是翻译模式，调用翻译服务
            if mode == "translations" and result:
                logger.info("正在翻译结果...")
                result = self.translate_processor.translate(result)
                logger.info(f"翻译结果: {result}")
            
            return result, None

        except TimeoutError:
            error_msg = f"❌ 本地处理超时 ({self.timeout_seconds}秒)"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"❌ {str(e)}"
            logger.error(f"本地音频处理错误: {str(e)}", exc_info=True)
            return None, error_msg
        finally:
            # 清理临时WAV文件（注意：这里只删除用于处理的临时文件，不删除存档文件）
            if wav_file and os.path.exists(wav_file):
                try:
                    os.unlink(wav_file)
                    logger.debug(f"清理临时处理文件: {wav_file}")
                except Exception as e:
                    logger.warning(f"清理临时WAV文件失败: {e}")
            
            # 显式关闭字节流
            try:
                audio_buffer.close()
            except Exception:
                pass 