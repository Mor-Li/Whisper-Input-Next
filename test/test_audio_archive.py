#!/usr/bin/env python3
"""
Audio Archive Transcription Tester
测试音频存档文件的转录功能

Usage: python test_audio_archive.py [audio_file_path]
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger

dotenv.load_dotenv()

def test_audio_transcription(audio_path):
    """测试指定音频文件的转录功能"""
    
    if not os.path.exists(audio_path):
        print(f"❌ 音频文件不存在: {audio_path}")
        return False
    
    print(f"🎵 测试音频文件: {audio_path}")
    print(f"📏 文件大小: {os.path.getsize(audio_path)} bytes")
    
    # 设置为OpenAI模式进行测试
    original_platform = os.environ.get("SERVICE_PLATFORM")
    os.environ["SERVICE_PLATFORM"] = "openai"
    
    try:
        # 创建OpenAI处理器
        processor = WhisperProcessor()
        print(f"🔧 使用处理器: OpenAI GPT-4o transcribe")
        print(f"⏱️  超时设置: {processor.timeout_seconds}秒")
        
        # 读取音频文件并转录
        print(f"\n🚀 开始转录...")
        with open(audio_path, 'rb') as f:
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
    else:
        # 默认使用你指定的音频文件
        audio_path = "audio_archive/recording_20250727_024821.wav"
    
    # 如果路径不是绝对路径，则相对于项目根目录
    if not os.path.isabs(audio_path):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        audio_path = os.path.join(project_root, audio_path)
    
    success = test_audio_transcription(audio_path)
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 测试完成！转录成功")
    else:
        print("😞 测试失败")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())