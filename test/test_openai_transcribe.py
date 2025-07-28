#!/usr/bin/env python3
"""
测试 OpenAI GPT-4o Transcribe API
使用 audio_archive 中的音频文件进行转录测试
"""

import os
import glob
from openai import OpenAI
import dotenv

# 加载 .env 文件
dotenv.load_dotenv()

def test_openai_transcribe():
    """测试 OpenAI transcribe API"""
    
    # 检查 API key，优先使用 OFFICIAL_OPENAI_API_KEY
    api_key = os.getenv('OFFICIAL_OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("❌ 请先设置 OFFICIAL_OPENAI_API_KEY 或 OPENAI_API_KEY 环境变量")
        print("   在 .env 文件中添加: OFFICIAL_OPENAI_API_KEY='your-api-key-here'")
        return False
    
    print(f"🔑 使用 API Key: {api_key[:20]}...")
    
    # 获取 base_url（如果设置了 OPENAI_BASE_URL）
    base_url = os.getenv('OPENAI_BASE_URL')
    if base_url:
        print(f"🔗 使用自定义 API Base URL: {base_url}")
    else:
        print("🌐 使用官方 OpenAI API")
    
    # 创建 OpenAI 客户端
    client = OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None
    )
    
    # 获取 audio_archive 中的音频文件
    audio_archive_dir = "audio_archive"
    audio_files = glob.glob(os.path.join(audio_archive_dir, "*.wav"))
    
    if not audio_files:
        print(f"❌ 在 {audio_archive_dir} 目录中没有找到音频文件")
        return False
    
    # 选择最新的音频文件进行测试
    latest_audio = max(audio_files, key=os.path.getmtime)
    print(f"📁 使用音频文件: {latest_audio}")
    
    try:
        # 打开音频文件
        with open(latest_audio, "rb") as audio_file:
            print("🚀 正在调用 OpenAI GPT-4o transcribe API...")
            
            # 调用 gpt-4o-transcribe 模型
            transcription = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=audio_file,
                response_format="text"
            )
            
            print("✅ 转录成功!")
            print(f"📝 转录结果: {transcription}")
            return True
            
    except Exception as e:
        print(f"❌ API 调用失败: {str(e)}")
        return False

def test_different_models():
    """测试不同的 OpenAI transcribe 模型"""
    
    api_key = os.getenv('OFFICIAL_OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("❌ 请先设置 OFFICIAL_OPENAI_API_KEY 或 OPENAI_API_KEY 环境变量")
        return
    
    # 获取 base_url
    base_url = os.getenv('OPENAI_BASE_URL')
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None
    )
    
    # 获取音频文件
    audio_files = glob.glob(os.path.join("audio_archive", "*.wav"))
    if not audio_files:
        print("❌ 没有找到音频文件")
        return
    
    latest_audio = max(audio_files, key=os.path.getmtime)
    
    # 测试不同的模型
    models = [
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe", 
        "whisper-1"
    ]
    
    for model in models:
        print(f"\n🧪 测试模型: {model}")
        try:
            with open(latest_audio, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    response_format="text"
                )
                print(f"✅ {model} 转录结果: {transcription}")
                
        except Exception as e:
            print(f"❌ {model} 调用失败: {str(e)}")

if __name__ == "__main__":
    print("🔧 OpenAI GPT-4o Transcribe API 测试")
    print("=" * 50)
    
    # 基础测试
    success = test_openai_transcribe()
    
    if success:
        print("\n" + "=" * 50)
        print("🔍 测试不同模型的性能...")
        test_different_models()
    
    print("\n" + "=" * 50)
    print("测试完成！")