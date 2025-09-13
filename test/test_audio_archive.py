#!/usr/bin/env python3
"""
Audio Archive Transcription Tester
测试音频存档文件的转录功能

Usage: python test_audio_archive.py [audio_file_path]
"""

import sys
import os
import glob
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
import tempfile
import subprocess
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger

dotenv.load_dotenv()

def get_latest_audio_file(audio_dir="audio_archive"):
    """从指定目录获取最新的音频文件"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    audio_archive_path = os.path.join(project_root, audio_dir)
    
    if not os.path.exists(audio_archive_path):
        print(f"❌ 音频存档目录不存在: {audio_archive_path}")
        return None
    
    # 查找所有音频文件
    audio_patterns = ['*.wav', '*.mp3', '*.m4a', '*.flac', '*.ogg']
    audio_files = []
    
    for pattern in audio_patterns:
        audio_files.extend(glob.glob(os.path.join(audio_archive_path, pattern)))
    
    if not audio_files:
        print(f"❌ 在 {audio_archive_path} 中未找到音频文件")
        return None
    
    # 按修改时间排序，获取最新的文件
    latest_file = max(audio_files, key=os.path.getmtime)
    print(f"🎵 找到最新音频文件: {os.path.basename(latest_file)}")
    return latest_file

def convert_to_wav(input_path):
    """将音频文件转换为WAV格式"""
    file_ext = os.path.splitext(input_path)[1].lower()
    
    if file_ext == '.wav':
        return input_path
    
    print(f"🔄 检测到 {file_ext} 格式，正在转换为 WAV...")
    
    # 创建临时WAV文件
    temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_wav.close()
    
    try:
        # 使用ffmpeg转换
        cmd = [
            'ffmpeg', '-i', input_path, 
            '-acodec', 'pcm_s16le',  # 16-bit PCM
            '-ar', '16000',          # 16kHz采样率
            '-ac', '1',              # 单声道
            '-y',                    # 覆盖输出文件
            temp_wav.name
        ]
        
        print(f"🔧 转换命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ FFmpeg转换失败:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return None
        
        print(f"✅ 转换成功: {temp_wav.name}")
        return temp_wav.name
        
    except FileNotFoundError:
        print("❌ 未找到 ffmpeg，请先安装 ffmpeg")
        print("macOS: brew install ffmpeg")
        print("Ubuntu: sudo apt install ffmpeg")
        return None
    except Exception as e:
        print(f"❌ 转换过程中发生错误: {e}")
        return None

def test_audio_transcription(audio_path):
    """测试指定音频文件的转录功能"""
    
    if not os.path.exists(audio_path):
        print(f"❌ 音频文件不存在: {audio_path}")
        return False
    
    print(f"🎵 测试音频文件: {audio_path}")
    print(f"📏 文件大小: {os.path.getsize(audio_path)} bytes")
    
    # 转换音频格式
    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        return False
    
    # 设置为OpenAI模式进行测试
    original_platform = os.environ.get("SERVICE_PLATFORM")
    os.environ["SERVICE_PLATFORM"] = "openai"
    
    temp_created = wav_path != audio_path  # 是否创建了临时文件
    
    try:
        # 创建OpenAI处理器
        processor = WhisperProcessor()
        print(f"🔧 使用处理器: OpenAI GPT-4o transcribe")
        print(f"⏱️  超时设置: {processor.timeout_seconds}秒")
        
        # 读取音频文件并转录
        print(f"\n🚀 开始转录...")
        with open(wav_path, 'rb') as f:
            import io
            audio_buffer = io.BytesIO(f.read())
            
            result = processor.process_audio(
                audio_buffer,
                mode="transcriptions", 
                prompt=""
            )
            
            # 解析结果
            text, error = result if isinstance(result, tuple) else (result, None)
            
            if error:
                print(f"❌ 转录失败: {error}")
                return False
            else:
                print(f"✅ 转录成功!")
                print(f"📝 转录结果:")
                print(f"「{text}」")
                return True
                
    except Exception as e:
        print(f"💥 测试过程中发生错误: {e}")
        return False
    finally:
        # 清理临时文件
        if temp_created and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
                print(f"🧹 清理临时文件: {wav_path}")
            except Exception as e:
                print(f"⚠️  清理临时文件失败: {e}")
        
        # 恢复原始环境变量
        if original_platform:
            os.environ["SERVICE_PLATFORM"] = original_platform
        else:
            os.environ.pop("SERVICE_PLATFORM", None)

def main():
    """主函数"""
    print("🎙️  Audio Archive Transcription Tester")
    print("=" * 50)
    
    # 获取音频文件路径
    if len(sys.argv) > 1:
        audio_path = sys.argv[1]
        # 如果路径不是绝对路径，则相对于项目根目录
        if not os.path.isabs(audio_path):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            audio_path = os.path.join(project_root, audio_path)
    else:
        # 默认使用audio_archive目录下最新的音频文件
        audio_path = get_latest_audio_file()
        if not audio_path:
            print("❌ 未找到可用的音频文件")
            return 1
    
    success = test_audio_transcription(audio_path)
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 测试完成！转录成功")
    else:
        print("😞 测试失败")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())