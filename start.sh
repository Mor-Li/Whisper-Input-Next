#!/bin/bash
# 启动 Whisper-Input-Next。
#
# 在 tmux 会话 Whisper-Input-Next 里运行守护循环 scripts/supervise.sh，
# 程序崩溃或麦克风卡死后会自动重启。已有同名会话时先关掉旧的再重开。
#
# 用法：
#   ./start.sh            启动并进入 tmux 界面（Ctrl+B 再按 D 退出界面，程序继续在后台跑）
#   ./start.sh --detach   只在后台启动，不进入界面（开机自启用的就是这个）
#
# 开机自启：./scripts/install_autostart.sh

set -euo pipefail
cd "$(dirname "$0")"
# 开机自启时 launchd 给的 PATH 里没有 Homebrew，找不到 tmux
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SESSION="Whisper-Input-Next"
ATTACH=1
if [ "${1:-}" = "--detach" ]; then
  ATTACH=0
fi

if [ ! -f ".env" ]; then
  echo "❌ 未找到 .env 配置文件，请复制 env.example 为 .env 并填好密钥"
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "❌ 未找到虚拟环境 .venv，请先按 README 安装依赖"
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "🔄 关闭旧的 $SESSION 会话..."
  tmux kill-session -t "$SESSION"
fi

# 先开一个空 shell 再发命令，让它加载 ~/.zshrc（部分 API 密钥是在那里 export 的）
tmux new-session -d -s "$SESSION" -c "$PWD"
sleep 0.5
tmux send-keys -t "$SESSION" "./scripts/supervise.sh" C-m

echo "✅ Whisper-Input-Next 已在 tmux 会话 $SESSION 里启动"
echo "   Ctrl+F：豆包流式转录    Ctrl+I：本地 Whisper"
echo "   查看界面：tmux attach -t $SESSION    最新日志：logs/latest.log"

if [ "$ATTACH" = 1 ] && [ -t 1 ]; then
  tmux attach -t "$SESSION"
fi
