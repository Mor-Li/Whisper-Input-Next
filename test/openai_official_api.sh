# alias zsh -i test/openai_official_api.sh
# make sure OFFICIAL_OPENAI_API_KEY is set
if [ -z "$OFFICIAL_OPENAI_API_KEY" ]; then
    echo "OFFICIAL_OPENAI_API_KEY is not set"
    exit 1
fi
source ~/Documents/GithubRepo/Whisper-Input-Next/.venv/bin/activate
export OPENAI_API_KEY=$OFFICIAL_OPENAI_API_KEY
unset OPENAI_BASE_URL
python /Users/limo/Documents/GithubRepo/Whisper-Input-Next/test/vanilla_audio_archive.py