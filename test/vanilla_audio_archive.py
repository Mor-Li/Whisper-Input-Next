from openai import OpenAI
client = OpenAI()

# openai 官方api测试
with open("audio_archive/recording_20250916_010510.wav", "rb") as f:
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