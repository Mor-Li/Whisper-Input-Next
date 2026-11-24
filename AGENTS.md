# Whisper-Input-Next 维护说明

这份说明写给接手维护的 agent。面向用户的介绍见 README.md 和 docs/README_zh-CN.md。

## 一、目录结构

- `main.py`：入口。`VoiceAssistant` 串起录音、转录、热键和状态栏。
- `src/audio/`：录音（`recorder.py`）和录音存档、转录缓存（`archive.py`）。
- `src/transcription/`：三种转录服务。豆包流式 `doubao_streaming.py` 是 Ctrl+F 的默认，OpenAI `whisper.py` 是豆包没配置时的备用，本地 whisper.cpp `local_whisper.py` 是 Ctrl+I。
- `src/keyboard/`：热键监听和状态机。`src/ui/`：菜单栏图标、点开后的使用统计菜单（`status_bar.py` 和 `usage_chart.py`）、说话时的浮动预览窗。统计数字由 `src/audio/usage_stats.py` 在菜单打开时从 `audio_archive/cache.json` 现算，缓存文件没变就不重读。
- 菜单里的「退出」会让 `main.py` 以退出码 0 结束，守护循环随之结束，不会自动拉起。重新启动用 `whisper_input`。
- `scripts/`：跑服务用的脚本，守护循环和开机自启。
- `tools/`：独立的音频文件转录脚本，和服务本身无关。墨哥的 transcribe-audio、video-transcribe、douyin-scrape 三个 skill 和 zsh 别名 `whisper_transcribe` 直接调用这里的文件，改名或挪位置要一起改。
- `test/`：只用替身、能自动跑的测试。`test/manual/`：要真麦克风或真密钥的手动脚本。
- 依赖用 uv 管，`pyproject.toml` 里的版本按 2026-11 实际在用的固定。`uv sync` 重建 `.venv`。

## 二、怎么跑起来

- 入口是 `main.py`，平时不直接运行它，而是用 `./start.sh`。
- `start.sh` 在 tmux 会话 `Whisper-Input-Next` 里先开一个空 shell，再发命令运行 `scripts/supervise.sh`。先开空 shell 是为了让它加载 `~/.zshrc`，因为 `OPENAI_API_KEY` 这类密钥有一部分是在那里 export 的，不在 `.env` 里。
- `scripts/supervise.sh` 是守护循环。`main.py` 退出码为 0（状态栏菜单点 Quit）或 130（Ctrl+C）时结束，其他退出码 2 秒后重启。连续 5 次 30 秒内就退出，改为每 60 秒重试一次。
- 开机自启由 `scripts/install_autostart.sh` 安装，生成 `~/Library/LaunchAgents/com.whisper-input-next.autostart.plist`。它只在登录时执行一次 `start.sh --detach`，所以不设 KeepAlive，重启全靠守护循环。
- 墨哥的 zsh 别名：`whisper_input` 是重启服务，`whisper_input_off` 是关掉会话。
- 用新代码重启服务：`./start.sh --detach`，会先关掉旧会话。

## 三、日志

- 每次运行一份 `logs/Whisper-Input-Next-<时间>.log`，`logs/latest.log` 指向当前这份。
- `logs/app.log` 是程序自己写的滚动日志，内容和上面重复，最多保留 6 个 1MB 文件。
- 开机自启时 `start.sh` 自己的输出在 `logs/launchd.log`。
- 查某次为什么挂了：看上一份运行日志的最后几十行。

## 四、权限

- 从 iTerm 里启动时，麦克风和辅助功能权限算在 iTerm 头上。
- 从 launchd 启动时，权限算在 tmux 头上。墨哥电脑上的 metabot 也是开机由 launchd 拉起的 tmux，和 Whisper 共用同一个 tmux server，所以 tmux 早已有麦克风和辅助功能权限。
- TCC 按可执行文件路径记权限，tmux 的路径是 `/opt/homebrew/Cellar/tmux/<版本>/bin/tmux`。brew 升级 tmux 后路径变了，权限可能要重新勾。

## 五、踩过的坑

### CoreAudio 关流卡死（2026-11 修）

现象是按 Ctrl+F 两次后状态栏图标一直是蓝色转圈，热键再按没反应，只能手动重启。

日志里的规律每次都一样：某次录音结束后出现「stream.stop() 5s 未返回」，之后设备刷新被跳过，下一次开流（`sd.InputStream` 或 `stream.start()`）永远不返回。2026-11-04 到 11-18 的 20 份运行日志里，卡住的 stop() 一次都没有自己恢复过。所以结论是：stop() 一旦卡住，这个进程里的 CoreAudio 就废了，只能重启进程。

现在的做法在 `src/audio/recorder.py` 和 `main.py`：

1. 关流和开流都放在辅助线程里限时 5 秒（`AudioRecorder.STREAM_OP_TIMEOUT`），超时就调 `_mark_wedged()` 上报。
2. 上报后录音器拒绝再开流，免得按键线程又卡进去。
3. `VoiceAssistant._on_audio_wedged()` 发一条系统通知，等流式线程和转录队列做完（最多 60 秒），刷完日志后 `os._exit(75)`，守护循环几秒后拉起新进程。
4. `stop_doubao_streaming()` 里如果流式线程根本没起来，直接把状态复位成空闲，不再停在「处理中」。
5. `KeyboardManager.state` 的 setter 在回调之后上报真实的当前状态。以前开流失败时回调内部已经复位成空闲，setter 却仍然上报「录音中」，状态栏会显示错。

stop() 为什么会卡住还没查清，可能和蓝牙耳机、睡眠唤醒或每次录音前都 `sd._terminate()` / `sd._initialize()` 刷新设备列表有关。真要根治可以把录音放进子进程。

### 录满最大时长后录音丢档（2026-11-24 修）

现象：录音达到最大时长（当时是 10 分钟）被自动停止后，日志里有「⏰ 录音已达到最大时长」和豆包的最终文本，字也打进了光标处，但没有「音频文件已保存到存档」，`audio_archive/audio/` 里没有 wav，`cache.json` 里没有条目。2026-11-24 晚 23:03 和 23:13 两段选题报告排练就这样丢了档。

原因：`main.py` 的 `_handle_auto_stop` 调的是 `stop_recording(abort=True)`，音频直接丢弃，状态也直接复位。豆包流式线程不受影响，照常收到最终文本并打字，但写缓存时要先拿音频存档路径，这时录音器里已经没有音频，于是跳过了缓存。这是 v3.1.0 时的设计：当时上限是为了防误触耗 API 额度，超时就丢弃。可豆包是边录边传，额度早就花了，丢弃只是白丢。

现在的做法：

1. 录满时长和设备断开都走 `VoiceAssistant._finish_recording()`，它调 `KeyboardManager.finish_recording()`，效果和手动再按一次热键完全一样（状态切到处理中，触发 `on_record_stop` / `on_local_stop`，存档、转录、写缓存都照手动的来）。以前设备断开是直接调停止函数，热键状态机里还以为在录音，下一次按键只会白白复位一次。
2. 如果这一刻刚好手动按了停止，热键状态已经是处理中，自动停止就什么都不做，不去抢录音器。
3. 上限默认 30 分钟，`.env` 里 `MAX_RECORD_MINUTES` 可改，填错（非正数）用默认值。录满会发一条系统通知。
4. 回归测试在 `test/test_auto_stop_archive.py`。

放宽上限的代价：录音时音频以 float32 留在内存里，48kHz 单声道每分钟约 11MB，30 分钟约 350MB，停止时拼接再转 WAV，峰值约翻倍。存档的 wav 是 16 位，每分钟约 5.8MB，30 分钟约 170MB。豆包用的是小时版资源（`volc.seedasr.sauc.duration`），按时长计费，代码里没有单次时长限制，但超过 10 分钟的连续流式会话还没实测过。OpenAI 批量转录有 25MB 的文件上限，大约 4 分钟以上的录音走这条备用路线本来就会失败，和这次改动无关。

### 其他

- 热键失灵的另外两种原因（事件 tap 被系统禁用、Secure Input 被占用）见 `docs/HOTKEY_DEAD_TAP_SELFHEAL.md`。
- 转录缓存 `audio_archive/cache.json` 的写入安全见 `docs/TRANSCRIPTION_CACHE_SAFETY.md`。

### 日志第一条丢失

sounddevice 每次初始化 PortAudio 时会把 stderr 临时指到 /dev/null。录音前会重新初始化来发现新插的麦克风，这一瞬间写到 stderr 的日志会丢。所以控制台日志写 stdout。

### OpenAI 账户没余额

2026-11-19 试跑时 OpenAI 返回 429「no credits remaining」。豆包配置齐全时用不到它，但豆包出问题时的备用路线和 `whisper_transcribe` 别名都会失败，要用得先去 OpenAI 后台充值。

## 六、测试

- 自动测试：`.venv/bin/python -m unittest discover -s test -p "test_*.py"`。其中 `test_archive_cache_safety.py` 会建临时目录、杀子进程，跑之前先看一眼它的说明。
- `test/manual/` 里的脚本要真麦克风或真密钥，不要随手跑。

## 七、移除过的功能

2026-11-19 清理时删掉了下面这些走不到或已废弃的功能。删之前的代码都在 git 标签 `pre-cleanup-2026-11` 上，用 `git show pre-cleanup-2026-11:路径` 取回。

- 翻译模式：录中文出英文。没有任何热键能触发它，而且调用 OpenAI 翻译接口时用了不支持的模型名。代码在 `main.py` 的 `start_translation_recording`，以及 `src/llm/translate.py`。以后要做，建议在豆包转写之后再调大模型翻译。
- Kimi 润色：`src/llm/kimi.py`，本地 Whisper 结果交给 Kimi 改写。
- 加标点和结果优化：`src/llm/symbol.py`，只在 GROQ 平台时生效。
- GROQ、SiliconFlow 两个转录平台：`src/transcription/whisper.py` 的分支和 `src/transcription/senseVoiceSmall.py`。
- 光标处打 `0`、`1`、`!` 显示状态：`src/keyboard/listener.py` 的 `type_temp_text`，早已被菜单栏图标取代。
- PyQt5 控制面板：`control_ui.py`，改配置、看日志的小窗口，主程序从没调用过。
- 一批早期的手动测试脚本，以及 `requirements.txt`。
