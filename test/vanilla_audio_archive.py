from openai import OpenAI
client = OpenAI()

with open("audio_archive/recording_20250913_073924.wav", "rb") as f:
    resp = client.audio.transcriptions.create(
        model="gpt-4o-transcribe",   # 或 "gpt-4o-mini-transcribe"
        file=f,                      # 关键点：传二进制文件对象
        # language="zh",             # 若已知语言可显式指定
        # temperature=0,             # 可选
    )
print(resp.text)