#!/bin/bash

# Whisper-Input 启动脚本 v2.0.0
# 用于启动语音转录工具

echo "🚀 启动 Whisper-Input 语音转录工具..."

# 创建日志目录(如果不存在)
if [ ! -d "logs" ]; then
  mkdir -p logs
fi

# 生成带时间戳的日志文件名
LOG_FILE="logs/whisper-input-$(date +%Y%m%d-%H%M%S).log"
echo "📝 日志将保存到: $LOG_FILE"

# 检查.env文件是否存在
if [ ! -f ".env" ]; then
  echo "❌ 未找到 .env 配置文件"
  echo "请复制 env.example 到 .env 并配置您的API密钥"
  exit 1
fi

# 检查是否已有名为whisper-input的会话
if tmux has-session -t whisper-input 2>/dev/null; then
  echo "🔄 已有whisper-input会话存在，将关闭旧会话并创建新会话..."
  tmux kill-session -t whisper-input
fi

# 创建虚拟环境(如果不存在)
if [ ! -d "venv" ]; then
  echo "🐍 创建虚拟环境..."
  python -m venv venv
  echo "✅ 虚拟环境创建完成"
fi

# 检查依赖是否已安装
if [ ! -f "venv/pyvenv.cfg" ] || [ ! -f "venv/lib/python*/site-packages/openai" ]; then
  echo "📦 安装项目依赖..."
  source venv/bin/activate
  pip install -r requirements.txt
  echo "✅ 依赖安装完成"
fi

# 创建一个新的tmux会话
tmux new-session -d -s whisper-input

# 确保在正确的目录
tmux send-keys -t whisper-input "cd $(pwd)" C-m

# 激活虚拟环境
tmux send-keys -t whisper-input "source venv/bin/activate" C-m

# 启动应用程序并同时将输出保存到日志文件
echo "🎙️  启动语音转录服务..."
tmux send-keys -t whisper-input "python main.py 2>&1 | tee $LOG_FILE" C-m

# 连接到会话
echo ""
echo "✅ Whisper-Input 已启动！"
echo "📋 快捷键说明："
echo "   Ctrl+F: OpenAI GPT-4 转录 (高质量)"
echo "   Ctrl+I: 本地 Whisper 转录 (省钱)"
echo ""
echo "🔧 会话管理："
echo "   按 Ctrl+B 然后 D 可以分离会话"
echo "   使用 'tmux attach -t whisper-input' 重新连接"
echo ""
echo "📝 日志文件: $LOG_FILE"
echo ""

tmux attach -t whisper-input