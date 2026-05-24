# 🦜 parrot

> 用 OpenAI gpt-realtime-2 给 Claude Code 装一张嘴 + 一对耳朵——闭着眼睛操作 Claude Code 的双向传话鹦鹉。
> 听 Claude 说什么念给你；听你说什么念给 Claude。

## 它是什么

一个独立的语音 agent，跟 Whisper-Input-Next 主程序**互相独立**：

| | Whisper-Input-Next（主） | parrot（这个） |
|---|---|---|
| 交互模式 | 按热键录音 → 转写 → 粘贴 | 持续对话（server VAD 自动断句、自动打断） |
| 用途 | 替代键盘输入 | 替代眼睛 + 手（念 Claude 输出 + 转发指令） |
| 进程 | `python main.py` | `python -m parrot.poc` |
| 麦克风 | DJI（默认） | DJI（CoreAudio shared 共拾，不冲突） |
| 后端 | 豆包 / OpenAI GPT-4o transcribe / 本地 whisper.cpp | OpenAI gpt-realtime-2（直连，不走 LiteLLM） |

两个进程可以同时跑（macOS CoreAudio shared mode 验证过）。

## 快速开始

**前置（一次性）**：把 DJI 设为 macOS 系统默认输入设备
```
系统设置 → 声音 → 输入 → DJI MIC MINI
```
理由：parrot 用 AVAudioEngine 启用 macOS VPIO 做系统级 AEC（消除 GPT 自己说话被 mic 拾回的自激回声）。AVAudioEngine 默认抓系统 default input，不接 sounddevice 那种 device index。

**启动**：
```bash
source ~/.bashrc                 # 让 OFFICIAL_OPENAI_API_KEY_XIANYU 可见
source .venv/bin/activate
python -m parrot.poc
```

依赖：`openai[realtime]`（自带 websockets）、`python-socks`（如果你的 shell 有 SOCKS proxy）、`pyobjc-framework-AVFoundation`、`sounddevice`、`numpy`。

**回归测试**：跑 `python -m parrot.verify_aec` 验证本机 AEC 性能。会外放 16 秒 TTS、录两份 wav 到 `/tmp/aec_{RAW,VPIO}.wav` 对比，AEC 衰减 ≥ 20 dB = OK。

## 工具

parrot 配了 4 个 tmux 工具（function calling）：

- `tmux_list_sessions` — 列所有 session
- `tmux_capture_pane(session, lines)` — 读屏（默认 80 行，自动 ANSI 清理）
- `tmux_send_keys(session, text)` — 把你的口头指令转发给 Claude Code
- `tmux_send_ctrl_c(session)` — 打断 Claude 当前任务

默认监管的 tmux session 是 `tiktok-drama`（可用 `COPILOT_TMUX_SESSION` env 覆盖 —— 是的 env 变量还叫 COPILOT，懒得改了）。

## 已知边界 case（todo）

### 1. 跟主项目语音输入冲突（共拾音）

**场景**：parrot 在跑的时候，你按主项目的 Ctrl+F 想录一段转写到光标。DJI mic 被两个进程同时拾音：
- 主项目正确转写 → 粘贴 ✅
- 但 parrot 也"听见"了你说的话 → server VAD 触发 → GPT 以为你在跟它说话 → 开口回答 ❌

**预期行为**：按下主项目语音输入热键期间，parrot 应该自动 mute（不送 audio buffer 给 OpenAI），松开后恢复。

**暂时解决**：
- 戴耳机 + 主项目 / parrot 二选一跑
- 或用 `COPILOT_INPUT_DEVICE=macbook` 让 parrot 用别的 mic

**长期方案**：未定。候选 —— 主项目按下热键时在 `~/.cache/whisper-input/recording.lock` 放一个标记文件，parrot 检测到就 mute。或者 parrot 监听主项目的快捷键事件，按下立刻 pause 输入 stream。

### 2. 喇叭回音

~~GPT 念稿通过电脑喇叭播放 → DJI（别在身上）拾到 → GPT 听见自己 → 自循环。~~

**已解决（2026-05-25）**：用 macOS VPIO（AVAudioEngine + voiceProcessingEnabled）做系统级 AEC，跟 FaceTime / Zoom / 微信视频同款机制。实测 AEC 衰减 20-32 dB（取决于环境）。前提是把 DJI 设为系统默认输入（见上）。

### 3. Claude Code 何时"答完了"

当前需要你主动问"Claude 干啥了"，parrot 才会 capture-pane。理想做法是 Claude Code 的 Stop / Notification hook 触发后主动 ping parrot —— 待 POC 链路打通后再加（feishu-hook skill 同款机制）。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `OFFICIAL_OPENAI_API_KEY_XIANYU` | （必填） | OpenAI 官方 API key，从 `~/.bashrc` 读 |
| `COPILOT_TMUX_SESSION` | `tiktok-drama` | parrot 默认监管的 tmux session |
| `COPILOT_INPUT_DEVICE` | （空） | 强制指定 mic（substring 匹配，如 `macbook` / `airpods`） |
