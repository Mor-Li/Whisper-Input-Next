#!/bin/zsh -i
# 用 OpenAI 官方接口转录 audio_archive/audio 里最新的一条录音。
# 对应 ~/.zshrc 里的别名 whisper_transcribe。需要 OFFICIAL_OPENAI_API_KEY（在 ~/.zshrc 里 export）。
if [ -z "$OFFICIAL_OPENAI_API_KEY" ]; then
    echo "OFFICIAL_OPENAI_API_KEY is not set"
    exit 1
fi
REPO="${0:A:h:h}"
export OPENAI_API_KEY=$OFFICIAL_OPENAI_API_KEY
unset OPENAI_BASE_URL
"$REPO/.venv/bin/python" "$REPO/tools/transcribe_latest_recording.py"
