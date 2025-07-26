#!/bin/bash

# 设置环境变量
# 2025-04-20 日，排除了GROQ的配置，因为siliconflow的API更稳定，根据README.md的说明，而且还自带标点符号，不用再发给llama来加入标点符号。更加快速。
# export GROQ_API_KEY="your_groq_api_key_here"

# 2025-07-06 日，添加了本地whisper.cpp的配置 local 
# 本地whisper.cpp配置（SERVICE_PLATFORM=local）
export SERVICE_PLATFORM=local
export WHISPER_CLI_PATH="/Users/limo/Documents/GithubRepo/whisper.cpp/build/bin/whisper-cli"
export WHISPER_MODEL_PATH="models/ggml-large-v3.bin"

# 创建日志目录(如果不存在)
if [ ! -d "logs" ]; then
  mkdir -p logs
fi

# 生成带时间戳的日志文件名
LOG_FILE="logs/whisper-input-$(date +%Y%m%d-%H%M%S).log"
echo "日志将保存到: $LOG_FILE"

# 检查是否已有名为whisper-input的会话
if tmux has-session -t whisper-input 2>/dev/null; then
  echo "已有whisper-input会话存在，将关闭旧会话并创建新会话..."
  tmux kill-session -t whisper-input
fi

# 创建虚拟环境(如果不存在)
if [ ! -d "venv" ]; then
  echo "创建虚拟环境..."
  python -m venv venv
fi

# 激活虚拟环境并安装依赖
# echo "激活虚拟环境并安装依赖..."
# source venv/bin/activate

# 关闭代理并安装依赖
# echo "关闭代理并安装依赖..."
# proxy_off 
# 下面这三行不用每次都运行，只需要运行一次
# pip install pip-tools python-dotenv
# pip-compile requirements.in
# pip install -r requirements.txt

# 创建一个新的tmux会话
tmux new-session -d -s whisper-input

# 确保在正确的目录
tmux send-keys -t whisper-input "cd $(pwd)" C-m

# 激活虚拟环境
tmux send-keys -t whisper-input "source venv/bin/activate" C-m

# 设置本地whisper.cpp环境变量
tmux send-keys -t whisper-input "export SERVICE_PLATFORM=local" C-m
tmux send-keys -t whisper-input "export WHISPER_CLI_PATH=\"/Users/limo/Documents/GithubRepo/whisper.cpp/build/bin/whisper-cli\"" C-m
tmux send-keys -t whisper-input "export WHISPER_MODEL_PATH=\"models/ggml-large-v3.bin\"" C-m

# Kimi润色功能通过快捷键控制：
# - Ctrl + F：普通转录模式（不润色）
# - Ctrl + I：Kimi润色模式（自动润色）
# KIMI_API_KEY 已在 .env 文件中配置，load_dotenv() 会自动加载

# 启动应用程序并同时将输出保存到日志文件
tmux send-keys -t whisper-input "python main.py 2>&1 | tee $LOG_FILE" C-m

# 连接到会话
echo "启动whisper-input会话，按Ctrl+B然后D可以分离会话..."
echo "所有输出将同时记录到: $LOG_FILE"
tmux attach -t whisper-input
