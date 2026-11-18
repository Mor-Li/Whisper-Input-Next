#!/bin/bash
# 安装 / 卸载开机自启（macOS LaunchAgent）。
#
#   ./scripts/install_autostart.sh            安装：登录后自动执行 start.sh --detach
#   ./scripts/install_autostart.sh uninstall  卸载
#
# LaunchAgent 只负责登录时启动一次。start.sh 起好 tmux 会话就退出，所以不设 KeepAlive，
# 崩溃和卡死后的重启由 tmux 里的守护循环 scripts/supervise.sh 负责。
#
# 权限说明：这样启动时，麦克风和辅助功能权限算在 tmux 头上（不是 iTerm）。
# 如果开机后热键没反应，去「系统设置 → 隐私与安全性」的「辅助功能」和「麦克风」里
# 给 tmux 打勾。Homebrew 升级 tmux 后路径会变，可能要重新勾一次。

set -euo pipefail

LABEL="com.whisper-input-next.autostart"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ "${1:-}" = "uninstall" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✅ 已卸载开机自启（当前正在运行的 Whisper-Input 不受影响）"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/start.sh</string>
    <string>--detach</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$REPO/logs/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$REPO/logs/launchd.log</string>
</dict>
</plist>
EOF

# 这里不调 launchctl bootstrap：RunAtLoad 会让它立刻执行 start.sh，把正在用的实例重启掉。
# 放进 ~/Library/LaunchAgents 的 plist 在下次登录时会被 launchd 自动加载。
plutil -lint "$PLIST" >/dev/null
echo "✅ 已安装开机自启: $PLIST"
echo "   下次登录后会自动在 tmux 会话 Whisper-Input-Next 里启动"
