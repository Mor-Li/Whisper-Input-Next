from openai import OpenAI
client = OpenAI()


import os
import glob
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


# openai 官方api测试
with open(get_latest_audio_file(), "rb") as f:
    resp = client.audio.transcriptions.create(
        model="gpt-4o-transcribe",   # 或 "gpt-4o-mini-transcribe"
        file=f,                      # 关键点：传二进制文件对象
        # language="zh",             # 若已知语言可显式指定
        # temperature=0,             # 可选
    )
print(resp.text)

# proxy_on
# unset OPENAI_BASE_URL
# export OPENAI_API_KEY=$OFFICIAL_OPENAI_API_KEY