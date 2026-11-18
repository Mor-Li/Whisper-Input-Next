#!/bin/bash
# 守护循环：运行 main.py，进程退出后自动重新拉起。
#
# 由 start.sh 放进 tmux 会话里运行，一般不需要手动调用。
# - 每次运行写一个新日志 logs/Whisper-Input-Next-<时间>.log，logs/latest.log 指向最新一份
# - 退出码 0（状态栏菜单里点 Quit）或 Ctrl+C 打断：不再重启
# - 其他退出码（崩溃，或 CoreAudio 卡死后主动退出的 75）：2 秒后重启
# - 连续 5 次在 30 秒内就退出，说明启动本身有问题，改成每 60 秒重试一次，避免刷屏

cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

fast_failures=0
while true; do
  log_file="logs/Whisper-Input-Next-$(date +%Y%m%d-%H%M%S).log"
  ln -sfn "$(basename "$log_file")" logs/latest.log
  echo "📝 日志: $log_file"

  started=$(date +%s)
  .venv/bin/python main.py 2>&1 | tee "$log_file"
  code=${PIPESTATUS[0]}

  case "$code" in
    0)
      echo "Whisper-Input 正常退出，守护循环结束"
      break
      ;;
    130)
      echo "收到 Ctrl+C，守护循环结束"
      break
      ;;
  esac

  if (( $(date +%s) - started < 30 )); then
    fast_failures=$((fast_failures + 1))
  else
    fast_failures=0
  fi
  delay=2
  if (( fast_failures >= 5 )); then
    delay=60
  fi
  echo "$(date +%H:%M:%S) - 🔁 main.py 退出（退出码 $code），${delay}s 后自动重启" | tee -a "$log_file"
  sleep "$delay"
done
