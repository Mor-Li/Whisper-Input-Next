#!/usr/bin/env python3
"""
测试本地whisper.cpp处理器
"""
import os
import sys
from io import BytesIO
from pathlib import Path

# 设置环境变量
os.environ['SERVICE_PLATFORM'] = 'local'
os.environ['WHISPER_CLI_PATH'] = '/Users/limo/Documents/GithubRepo/whisper.cpp/build/bin/whisper-cli'
os.environ['WHISPER_MODEL_PATH'] = 'models/ggml-large-v3.bin'

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.transcription.local_whisper import LocalWhisperProcessor

def test_with_existing_audio():
    """使用现有的测试音频文件进行测试"""
    # 使用whisper.cpp自带的测试音频文件
    audio_file = "/Users/limo/Documents/GithubRepo/whisper.cpp/tests/test_zh-CN.wav"
    
    if not os.path.exists(audio_file):
        print(f"❌ 测试音频文件不存在: {audio_file}")
        print("请确保whisper.cpp目录下有tests/test_zh-CN.wav文件")
        return False
    
    try:
        # 创建处理器
        processor = LocalWhisperProcessor()
        print("✅ LocalWhisperProcessor 创建成功")
        
        # 读取音频文件
        with open(audio_file, 'rb') as f:
            audio_data = f.read()
        
        # 创建BytesIO对象
        audio_buffer = BytesIO(audio_data)
        
        print(f"📁 使用测试音频文件: {audio_file}")
        print("🎙️ 开始转录测试...")
        
        # 测试转录
        result, error = processor.process_audio(audio_buffer, mode="transcriptions")
        
        if error:
            print(f"❌ 转录失败: {error}")
            return False
        else:
            print(f"✅ 转录成功: {result}")
        
        # 测试翻译（重新创建buffer，因为前面已经被关闭了）
        audio_buffer = BytesIO(audio_data)
        print("\n🌐 开始翻译测试...")
        result, error = processor.process_audio(audio_buffer, mode="translations")
        
        if error:
            print(f"❌ 翻译失败: {error}")
            return False
        else:
            print(f"✅ 翻译成功: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_prerequisites():
    """检查前置条件"""
    print("🔍 检查前置条件...")
    
    whisper_cli = os.environ.get('WHISPER_CLI_PATH')
    if not os.path.exists(whisper_cli):
        print(f"❌ Whisper CLI 不存在: {whisper_cli}")
        return False
    else:
        print(f"✅ Whisper CLI 存在: {whisper_cli}")
    
    # 检查模型文件
    model_rel_path = os.environ.get('WHISPER_MODEL_PATH')
    if os.path.isabs(model_rel_path):
        model_path = model_rel_path
    else:
        # whisper_cli: /path/to/whisper.cpp/build/bin/whisper-cli
        # 需要向上3级目录到whisper.cpp根目录
        whisper_root = os.path.dirname(os.path.dirname(os.path.dirname(whisper_cli)))
        model_path = os.path.join(whisper_root, model_rel_path)
        
    if not os.path.exists(model_path):
        print(f"❌ 模型文件不存在: {model_path}")
        return False
    else:
        print(f"✅ 模型文件存在: {model_path}")
    
    return True

def main():
    print("=" * 50)
    print("本地 Whisper.cpp 处理器测试")
    print("=" * 50)
    
    if not check_prerequisites():
        print("\n❌ 前置条件检查失败，无法继续测试")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("开始功能测试")
    print("=" * 50)
    
    success = test_with_existing_audio()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 所有测试通过！本地whisper.cpp处理器工作正常")
        print("\n📝 如何使用:")
        print("1. 设置环境变量 SERVICE_PLATFORM=local")
        print("2. 设置 WHISPER_CLI_PATH 指向你的whisper.cpp可执行文件")
        print("3. 设置 WHISPER_MODEL_PATH 指向模型文件路径")
        print("4. 运行 python main.py")
    else:
        print("❌ 测试失败，请检查配置和日志")
    print("=" * 50)

if __name__ == "__main__":
    main() 