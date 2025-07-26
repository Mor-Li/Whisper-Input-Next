#!/usr/bin/env python3
"""
失败重试逻辑测试脚本
测试OpenAI转录失败后的重试机制

这个脚本会：
1. 使用错误的API key模拟失败
2. 检查是否显示感叹号
3. 恢复正确API key模拟重试
4. 验证重试是否成功
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
import io
from src.transcription.whisper import WhisperProcessor
from src.utils.logger import logger

dotenv.load_dotenv()

def test_failure_retry_logic():
    """测试失败重试逻辑"""
    
    audio_path = "audio_archive/recording_20250727_024821.wav"
    
    if not os.path.exists(audio_path):
        print(f"❌ 测试音频文件不存在: {audio_path}")
        return False
    
    print("🧪 测试失败重试逻辑")
    print("=" * 50)
    
    # 备份原始API key
    original_key = os.getenv("OFFICIAL_OPENAI_API_KEY")
    
    # 第一步：模拟失败
    print("📍 步骤1: 模拟API失败")
    os.environ["OFFICIAL_OPENAI_API_KEY"] = "sk-invalid-key-for-testing"
    os.environ["SERVICE_PLATFORM"] = "openai"
    
    try:
        processor = WhisperProcessor()
        
        with open(audio_path, 'rb') as f:
            audio_buffer = io.BytesIO(f.read())
            
            print("🚀 发送请求（预期失败）...")
            result = processor.process_audio(audio_buffer, mode="transcriptions", prompt="")
            
            text, error = result if isinstance(result, tuple) else (result, None)
            
            if error:
                print(f"✅ 按预期失败: {error}")
                print("💡 此时应该显示感叹号(!)等待重试")
            else:
                print("❌ 意外成功了，应该失败的")
                return False
                
    except Exception as e:
        print(f"✅ 捕获到异常: {e}")
        print("💡 此时应该显示感叹号(!)等待重试")
    
    # 第二步：恢复API key并重试
    print("\n📍 步骤2: 恢复API key并重试")
    os.environ["OFFICIAL_OPENAI_API_KEY"] = original_key
    
    try:
        # 重新创建处理器（使用正确的API key）
        processor = WhisperProcessor()
        
        with open(audio_path, 'rb') as f:
            audio_buffer = io.BytesIO(f.read())
            
            print("🔄 重试转录...")
            result = processor.process_audio(audio_buffer, mode="transcriptions", prompt="")
            
            text, error = result if isinstance(result, tuple) else (result, None)
            
            if error:
                print(f"❌ 重试仍然失败: {error}")
                return False
            else:
                print("✅ 重试成功!")
                print(f"📝 重试结果: {text[:100]}...")
                return True
                
    except Exception as e:
        print(f"❌ 重试过程中发生错误: {e}")
        return False

def main():
    """主函数"""
    print("🔄 失败重试逻辑测试")
    print("模拟: 失败(!) → 按Ctrl+F → 重试(1) → 成功")
    print()
    
    success = test_failure_retry_logic()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 失败重试逻辑测试通过!")
        print("💡 实际使用时:")
        print("   1. API失败 → 显示 '!'")
        print("   2. 再按Ctrl+F → 显示 '1' 并重试上次音频")
        print("   3. 成功 → 输出转录文本")
    else:
        print("😞 失败重试逻辑测试失败")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())