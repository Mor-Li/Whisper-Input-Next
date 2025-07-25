#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import wave
import sys
import subprocess
import requests
import traceback
from openai import OpenAI
import dotenv

# 加载环境变量
dotenv.load_dotenv()

def check_network():
    """检查网络连接状态"""
    try:
        # 测试连接到groq
        response = requests.get("https://api.groq.com/", timeout=5)
        if response.status_code == 200:
            print(f"✅ Groq API连接正常: {response.status_code}")
        else:
            print(f"⚠️ Groq API连接异常: {response.status_code}")
    except Exception as e:
        print(f"❌ Groq API连接失败: {e}")
    
    try:
        # 测试连接到谷歌（检查基本网络连通性）
        response = requests.get("https://www.google.com", timeout=5)
        print(f"✅ 外网连接正常: {response.status_code}")
    except Exception as e:
        print(f"❌ 外网连接失败: {e}")

def check_env_variables():
    """检查环境变量是否正确设置"""
    api_key = os.getenv("GROQ_API_KEY")
    base_url = os.getenv("GROQ_BASE_URL")
    
    if not api_key:
        print("❌ 未设置 GROQ_API_KEY 环境变量")
        return False
    else:
        print(f"✅ GROQ_API_KEY: {api_key[:5]}...{api_key[-5:]}")
    
    if not base_url:
        print("⚠️ 未设置 GROQ_BASE_URL 环境变量，将使用默认值")
    else:
        print(f"✅ GROQ_BASE_URL: {base_url}")
    
    return True

def create_test_audio():
    """创建测试音频文件"""
    try:
        # 使用系统命令录制3秒钟的音频
        print("🎤 录制3秒测试音频...")
        
        # 检查 'rec' 命令是否存在
        try:
            subprocess.run(["which", "rec"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # 使用rec命令录制音频
            subprocess.run(["rec", "-r", "16000", "-c", "1", "test_audio.wav", "trim", "0", "3"], 
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("✅ 已生成测试音频: test_audio.wav")
            return "test_audio.wav"
        except subprocess.CalledProcessError:
            # 如果系统中没有rec命令，就创建一个空的WAV文件
            print("⚠️ 未找到 'rec' 命令，创建空白音频文件...")
            with wave.open("test_audio.wav", "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(bytes([0] * 16000 * 2 * 3))  # 3秒的空白音频
            print("✅ 已生成空白测试音频: test_audio.wav")
            return "test_audio.wav"
    except Exception as e:
        print(f"❌ 创建测试音频失败: {e}")
        return None

def test_whisper_api(audio_path):
    """测试Whisper API"""
    api_key = os.getenv("GROQ_API_KEY")
    base_url = os.getenv("GROQ_BASE_URL")
    
    # 检查代理状态
    print("\n📡 检查代理状态:")
    http_proxy = os.getenv("http_proxy")
    https_proxy = os.getenv("https_proxy")
    print(f"  - HTTP代理: {http_proxy if http_proxy else '未设置'}")
    print(f"  - HTTPS代理: {https_proxy if https_proxy else '未设置'}")
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None
    )
    
    print("\n🔄 开始测试Whisper API...")
    
    # 打开音频文件
    with open(audio_path, "rb") as audio_file:
        try:
            # 记录开始时间
            start_time = time.time()
            
            print("⏳ 发送API请求...")
            response = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                response_format="text",
                file=("audio.wav", audio_file)
            )
            
            # 计算耗时
            elapsed_time = time.time() - start_time
            
            print(f"✅ API请求成功! 耗时: {elapsed_time:.2f}秒")
            print(f"📝 转录结果: {response}")
            return True
            
        except Exception as e:
            print(f"❌ API请求失败: {str(e)}")
            print("\n🔍 详细错误信息:")
            traceback.print_exc()
            return False

def main():
    """主函数"""
    print("🔍 Whisper API 测试工具")
    print("=" * 50)
    
    # 检查网络连接
    print("\n📡 检查网络连接状态...")
    check_network()
    
    # 检查环境变量
    print("\n🔐 检查环境变量...")
    if not check_env_variables():
        return
    
    # 检查是否提供了音频文件
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        audio_path = sys.argv[1]
        print(f"\n🎵 使用指定音频文件: {audio_path}")
    else:
        # 创建测试音频
        print("\n🎵 没有提供音频文件，创建测试音频...")
        audio_path = create_test_audio()
        if not audio_path:
            return
    
    # 尝试先关闭代理测试
    print("\n🔄 先尝试关闭代理测试...")
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    
    if not test_whisper_api(audio_path):
        # 如果失败，尝试开启代理测试
        print("\n🔄 尝试开启代理测试...")
        volc_proxy = 'http://127.0.0.1:7890'
        os.environ["http_proxy"] = volc_proxy
        os.environ["https_proxy"] = volc_proxy
        os.environ["HTTP_PROXY"] = volc_proxy
        os.environ["HTTPS_PROXY"] = volc_proxy
        
        test_whisper_api(audio_path)

if __name__ == "__main__":
    main() 
    
# 正常的输出如下：
# (base) limo@limos-MacBook-Pro ~/Documents/GithubRepo/Whisper-Input ➜ git:(main) [04-20 17:42:46] python test_whisper_api.py
# 🔍 Whisper API 测试工具
# ==================================================

# 📡 检查网络连接状态...
# ✅ Groq API连接正常: 200
# ✅ 外网连接正常: 200

# 🔐 检查环境变量...
# ✅ GROQ_API_KEY: gsk_X...dSPQk
# ✅ GROQ_BASE_URL: https://api.groq.com/openai/v1

# 🎵 没有提供音频文件，创建测试音频...
# 🎤 录制3秒测试音频...
# ✅ 已生成测试音频: test_audio.wav

# 🔄 先尝试关闭代理测试...

# 📡 检查代理状态:
#   - HTTP代理: 未设置
#   - HTTPS代理: 未设置

# 🔄 开始测试Whisper API...
# ⏳ 发送API请求...
# ✅ API请求成功! 耗时: 3.01秒
# 📝 转录结果:  .

