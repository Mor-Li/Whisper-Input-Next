from pynput.keyboard import Controller, Key, Listener
import pyperclip
from ..utils.logger import logger
import subprocess
import time
from .inputState import InputState
import os
import sys
import threading


class _TapCapturingListener(Listener):
    """记住底层 event tap 引用的 pynput Listener（仅 macOS 使用）。

    pynput 只在启动时启用一次 tap；macOS 一旦判定回调超时就把 tap 禁用，
    pynput 不会重新启用，热键从此失灵、只能重启进程。把 tap 引用存下来，
    失效时（_darwin_intercept / watchdog）才有办法调 CGEventTapEnable 复活它。
    """

    tap_ref = None

    def _create_event_tap(self):
        tap = super()._create_event_tap()
        self.tap_ref = tap
        return tap


def _process_name(pid):
    """按 pid 查进程名，用于点名谁占用了 Secure Input"""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=2,
        )
        return os.path.basename(out.stdout.strip()) or "未知进程"
    except Exception:
        return "未知进程"


class KeyboardManager:
    """监听全局热键（默认 Ctrl+F / Ctrl+I），维护录音状态机，并把转录文本粘贴到光标处。"""

    KEY_DEBOUNCE_TIME = 0.3  # 按键防抖时间（秒）

    def __init__(self, on_record_start, on_record_stop, on_local_start, on_local_stop, on_state_change=None):
        self.keyboard = Controller()
        self.modifier_pressed = False  # 修饰键（默认 Ctrl）是否按着
        self.f_pressed = False  # 转录键（默认 F）是否按着
        self.i_pressed = False  # I 键是否按着
        self.error_message = None
        self.warning_message = None
        self.is_recording = False  # toggle 模式的录音状态
        self.last_key_time = 0  # 防止重复触发

        # macOS 事件拦截：需要吞掉的组合键虚拟键码集合 + 修饰键掩码
        # （在 start_listening 里根据实际配置计算）
        self._suppress_vks = set()
        self._suppress_modifier_mask = 0

        # tap 自愈：当前 listener 引用 + 禁用告警的限频时间戳
        self._listener = None
        self._tap_disabled_log_time = 0.0

        # 回调函数
        self.on_record_start = on_record_start  # Ctrl+F 开始
        self.on_record_stop = on_record_stop    # Ctrl+F 结束
        self.on_local_start = on_local_start    # Ctrl+I 开始（本地 Whisper）
        self.on_local_stop = on_local_stop      # Ctrl+I 结束
        self.on_state_change = on_state_change

        self._state = InputState.IDLE

        # 粘贴用的快捷键修饰键：Mac 是 Cmd，Windows 是 Ctrl
        if os.getenv("SYSTEM_PLATFORM") == "win":
            self.paste_modifier = Key.ctrl
            logger.info("配置到Windows平台")
        else:
            self.paste_modifier = Key.cmd
            logger.info("配置到Mac平台")

        self.transcriptions_button = self._parse_key(os.getenv("TRANSCRIPTIONS_BUTTON") or "f")
        # 热键的修饰键。旧版本叫 TRANSLATIONS_BUTTON（当年和翻译模式共用），仍然兼容
        modifier_name = os.getenv("HOTKEY_MODIFIER") or os.getenv("TRANSLATIONS_BUTTON") or "ctrl"
        self.modifier_key = self._parse_key(modifier_name)
        transcriptions_name = os.getenv("TRANSCRIPTIONS_BUTTON") or "f"
        logger.info(f"按 {modifier_name} + {transcriptions_name}：开始/结束录音（豆包流式，豆包不可用时用 OpenAI）")
        logger.info(f"按 {modifier_name} + i：开始/结束录音（本地 Whisper）")

    @staticmethod
    def _parse_key(name):
        """字符键（如 f）用字符串表示，特殊键（如 ctrl）用 pynput 的 Key 枚举。"""
        if len(name) == 1 and name.isalpha():
            return name
        try:
            return Key[name]
        except KeyError:
            raise ValueError(f"无效的按键配置：{name}")

    @property
    def state(self):
        """获取当前状态"""
        return self._state

    @state.setter
    def state(self, new_state):
        """切换状态，并触发对应的开始/结束录音回调"""
        if new_state == self._state:
            return
        self._state = new_state

        if new_state == InputState.RECORDING:
            self.on_record_start()
        elif new_state == InputState.RECORDING_LOCAL:
            self.on_local_start()
        elif new_state == InputState.PROCESSING:
            self.on_record_stop()
        elif new_state == InputState.PROCESSING_LOCAL:
            self.on_local_stop()
        elif new_state in (InputState.WARNING, InputState.ERROR):
            message = self.warning_message if new_state == InputState.WARNING else self.error_message
            logger.warning(f"状态栏提示（{new_state.name}）：{message}")
            self.warning_message = None
            self.error_message = None
            self._schedule_message_clear()

        # 上面的回调（如开流失败）可能已经在内部把状态 reset 回 IDLE，
        # 这时要上报真实的当前状态，而不是这次要切换的 new_state，
        # 否则状态栏会显示"录音中"而实际已经空闲。
        if self.on_state_change:
            try:
                self.on_state_change(self._state)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"状态回调异常: {exc}")

    def _schedule_message_clear(self):
        """警告/错误在状态栏显示 2 秒后回到空闲"""
        def clear_message():
            time.sleep(2)
            self.state = InputState.IDLE

        threading.Thread(target=clear_message, daemon=True).start()

    def show_warning(self, warning_message):
        """显示警告消息"""
        self.warning_message = warning_message
        self.state = InputState.WARNING

    def show_error(self, error_message):
        """显示错误消息"""
        self.error_message = error_message
        self.state = InputState.ERROR

    def keep_clipboard_text(self, text):
        """把文本放进剪贴板，方便用户手动粘贴（流式出错时的兜底）。"""
        if not text:
            return False

        try:
            pyperclip.copy(text)
            logger.info("已将兜底转录文本保留到剪贴板")
            return True
        except Exception as e:
            logger.warning(f"保留兜底转录文本到剪贴板失败: {e}")
            return False

    def type_text(self, text, error_message=None):
        """通过剪贴板把文字粘贴到当前光标位置

        Args:
            text: 要输入的文本
            error_message: 错误信息，非空时只显示错误、不输入
        """
        if error_message:
            self.show_error(error_message)
            return

        if not text:
            # 如果没有文本且不是错误，可能是录音时长不足
            if self.state == InputState.PROCESSING:
                self.show_warning("录音时长过短，请至少录制1秒")
            return

        try:
            logger.info("正在输入转录文本...")
            pyperclip.copy(text)
            with self.keyboard.pressed(self.paste_modifier):
                self.keyboard.press('v')
                self.keyboard.release('v')

            # 等待一小段时间确保文本已输入
            time.sleep(0.5)
            logger.info("文本输入完成")

            # 清理处理状态（流式识别中不重置，保持录音状态）
            if self.state != InputState.DOUBAO_STREAMING:
                self.state = InputState.IDLE
        except Exception as e:
            logger.error(f"文本输入失败: {e}")
            self.show_error(f"❌ 文本输入失败: {e}")

    def _set_state_async(self, new_state):
        """在后台线程里切换状态。

        状态切换会同步触发 on_record_start/on_record_stop 等回调（启动/停止录音），
        这些活如果在键盘事件回调线程里跑，会拖慢回调返回时间；而 macOS 一旦发现
        事件 tap 的回调超时，就会把 tap 禁用，表现为"快捷键突然没反应、录音不触发"。
        因此把状态切换挪到后台线程，保证键盘事件回调秒回。
        """
        threading.Thread(
            target=lambda: setattr(self, "state", new_state),
            name="state-change",
            daemon=True,
        ).start()

    def _toggle(self, recording_state, processing_state, label):
        """按一下开始录音，再按一下结束"""
        current_time = time.time()
        if current_time - self.last_key_time < self.KEY_DEBOUNCE_TIME:
            return
        self.last_key_time = current_time

        if not self.is_recording:
            if self.state.can_start_recording:
                self.is_recording = True
                self._set_state_async(recording_state)
                logger.info(f"🎤 开始录音（{label}）")
        else:
            self.is_recording = False
            self._set_state_async(processing_state)
            logger.info(f"⏹️ 停止录音（{label}）")

    def toggle_recording(self):
        """Ctrl+F：切换录音状态"""
        self._toggle(InputState.RECORDING, InputState.PROCESSING, "Ctrl+F")

    def toggle_local_recording(self):
        """Ctrl+I：切换本地 Whisper 录音状态"""
        self._toggle(InputState.RECORDING_LOCAL, InputState.PROCESSING_LOCAL, "本地 Whisper")

    def _matches(self, key, button):
        """判断按键是否是配置的某个键（字符键或特殊键）"""
        if isinstance(button, str):
            return getattr(key, 'char', None) == button
        return key == button

    def on_press(self, key):
        """按键按下时的回调"""
        if getattr(key, 'char', None) == 'i':
            self.i_pressed = True
            if self.modifier_pressed:
                self.toggle_local_recording()
        elif self._matches(key, self.transcriptions_button):
            self.f_pressed = True
            if self.modifier_pressed:
                self.toggle_recording()
        elif self._matches(key, self.modifier_key):
            self.modifier_pressed = True
            if self.f_pressed:
                self.toggle_recording()
            elif self.i_pressed:
                self.toggle_local_recording()

    def on_release(self, key):
        """按键释放时的回调"""
        if getattr(key, 'char', None) == 'i':
            self.i_pressed = False
        elif self._matches(key, self.transcriptions_button):
            self.f_pressed = False
        elif self._matches(key, self.modifier_key):
            self.modifier_pressed = False

    def _build_hotkey_suppression(self):
        """计算需要在系统层拦截的组合键。

        目的：`Ctrl+F` / `Ctrl+I` 这类组合键在 macOS 文本框里本身是 emacs 键位
        （Ctrl+F=光标右移一格、Ctrl+I=Tab），会在每次按下时弄乱光标。我们把这些
        组合键事件吞掉、不透传给前台 app，就能只用它们当录音开关而没有副作用。

        Returns:
            (set[int], int): (要拦截的虚拟键码集合, 修饰键 flag 掩码)
        """
        from Quartz import (
            kCGEventFlagMaskAlternate,
            kCGEventFlagMaskCommand,
            kCGEventFlagMaskControl,
            kCGEventFlagMaskShift,
        )

        # Controller._mapping: unicode 字符 -> 虚拟键码（跟随当前键盘布局）
        mapping = getattr(self.keyboard, "_mapping", {}) or {}

        def vk_of(button):
            if isinstance(button, str):
                return mapping.get(button)
            # 特殊键（Key 枚举）
            return getattr(getattr(button, "value", None), "vk", None)

        vks = set()
        # 转录键（默认 f）+ 本地 Whisper 键（i）
        for button in (self.transcriptions_button, "i"):
            vk = vk_of(button)
            if vk is not None:
                vks.add(vk)

        modifier_masks = {
            Key.ctrl: kCGEventFlagMaskControl,
            Key.ctrl_l: kCGEventFlagMaskControl,
            Key.ctrl_r: kCGEventFlagMaskControl,
            Key.cmd: kCGEventFlagMaskCommand,
            Key.cmd_l: kCGEventFlagMaskCommand,
            Key.cmd_r: kCGEventFlagMaskCommand,
            Key.alt: kCGEventFlagMaskAlternate,
            Key.alt_l: kCGEventFlagMaskAlternate,
            Key.alt_r: kCGEventFlagMaskAlternate,
            Key.shift: kCGEventFlagMaskShift,
            Key.shift_l: kCGEventFlagMaskShift,
            Key.shift_r: kCGEventFlagMaskShift,
        }
        mask = modifier_masks.get(self.modifier_key, kCGEventFlagMaskControl)
        return vks, mask

    def _darwin_intercept(self, event_type, event):
        """macOS 事件拦截回调。

        把录音组合键（默认 Ctrl+F / Ctrl+I）吞掉，不透传给前台 app，避免触发
        系统自带的 emacs 键位而移动光标。其它按键一律原样放行。

        pynput 会先触发 on_press/on_release，再调用本函数决定是否放行，
        所以拦截不会影响录音开关逻辑。本函数必须极快返回，否则事件 tap 会被
        macOS 判定超时并禁用。
        """
        try:
            from Quartz import (
                CGEventGetFlags,
                CGEventGetIntegerValueField,
                CGEventTapEnable,
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
                kCGKeyboardEventKeycode,
            )

            # macOS 禁用 tap 前会送来一个通知事件（典型诱因：录音收尾时进程
            # 正忙，恰好又快速连按导致回调排队超时）。在这里立刻重新启用，
            # 否则热键从此失灵、只能重启进程。
            if event_type in (kCGEventTapDisabledByTimeout,
                              kCGEventTapDisabledByUserInput):
                tap = getattr(self._listener, "tap_ref", None)
                if tap is not None:
                    CGEventTapEnable(tap, True)
                    now = time.time()
                    if now - self._tap_disabled_log_time > 5:
                        self._tap_disabled_log_time = now
                        logger.warning(
                            "⚠️ 键盘事件 tap 被系统禁用（回调超时），已自动重新启用"
                        )
                return event

            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            if vk in self._suppress_vks:
                flags = CGEventGetFlags(event)
                if flags & self._suppress_modifier_mask:
                    return None  # 吞掉事件，不传给前台 app
        except Exception:
            # 拦截逻辑绝不能因异常影响正常输入，出错就放行
            pass
        return event

    def start_listening(self):
        """开始监听键盘事件"""
        listener_kwargs = {
            "on_press": self.on_press,
            "on_release": self.on_release,
        }
        listener_cls = Listener

        # macOS: 拦截录音组合键，避免 Ctrl+F(光标右移)/Ctrl+I(Tab) 弄乱光标
        if sys.platform == "darwin":
            listener_cls = _TapCapturingListener
            try:
                self._suppress_vks, self._suppress_modifier_mask = (
                    self._build_hotkey_suppression()
                )
                if self._suppress_vks:
                    listener_kwargs["darwin_intercept"] = self._darwin_intercept
                    logger.info(
                        f"✅ 已启用组合键事件拦截 (vk={sorted(self._suppress_vks)})，"
                        "按录音快捷键不会再移动光标"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"初始化组合键拦截失败（不影响录音，仅光标可能仍会位移）: {exc}"
                )

        with listener_cls(**listener_kwargs) as listener:
            self._listener = listener
            if sys.platform == "darwin":
                self._start_tap_watchdog(listener)
            listener.join()

    def _start_tap_watchdog(self, listener):
        """后台体检线程：热键"突然失灵"的两种根因都在这里兜底。

        1. tap 被系统禁用：回调超时后 macOS 禁掉 tap，pynput 不会重新启用。
           _darwin_intercept 里会就地复活，这里是二道保险（比如禁用通知
           本身丢了、或没启用组合键拦截时）。
        2. Secure Input 被占用：终端的"安全键盘输入"、sudo 密码框、锁屏
           等会开启 Secure Input，期间所有 event tap 收不到键盘事件（按键
           直接透传给前台 app），对方释放后自动恢复。这里点名占用进程，
           以后失灵看日志就知道原因。
        """
        def _watch():
            from Quartz import (
                CGEventTapEnable,
                CGEventTapIsEnabled,
                CGSessionCopyCurrentDictionary,
            )

            last_secure_pid = None
            while listener.running:
                time.sleep(5)
                try:
                    tap = getattr(listener, "tap_ref", None)
                    if tap is not None and not CGEventTapIsEnabled(tap):
                        CGEventTapEnable(tap, True)
                        logger.warning(
                            "⚠️ 键盘事件 tap 处于禁用状态，watchdog 已重新启用"
                        )

                    session = CGSessionCopyCurrentDictionary() or {}
                    pid = session.get("kCGSSessionSecureInputPID")
                    if pid != last_secure_pid:
                        if pid is not None:
                            logger.warning(
                                f"⚠️ 进程 {_process_name(pid)} (pid={pid}) 开启了 "
                                "Secure Input，热键会失灵直到它释放"
                                "（常见来源：终端的\"安全键盘输入\"、sudo 密码、锁屏）"
                            )
                        else:
                            logger.info("✅ Secure Input 已释放，热键恢复正常")
                        last_secure_pid = pid
                except Exception:
                    # 体检线程绝不能崩；单轮失败下一轮重试
                    pass

        threading.Thread(target=_watch, name="tap-watchdog", daemon=True).start()

    def reset_state(self):
        """重置所有按键和录音状态，回到空闲"""
        self.modifier_pressed = False
        self.f_pressed = False
        self.i_pressed = False
        self.is_recording = False
        self.last_key_time = time.time()
        self.error_message = None
        self.warning_message = None
        self.state = InputState.IDLE

def check_accessibility_permissions():
    """检查是否有辅助功能权限并提供指导"""
    logger.warning("\n=== macOS 辅助功能权限检查 ===")
    logger.warning("此应用需要辅助功能权限才能监听键盘事件。")
    logger.warning("\n请按照以下步骤授予权限：")
    logger.warning("1. 打开 系统偏好设置")
    logger.warning("2. 点击 隐私与安全性")
    logger.warning("3. 点击左侧的 辅助功能")
    logger.warning("4. 点击右下角的锁图标并输入密码")
    logger.warning("5. 在右侧列表中找到 Terminal（或者您使用的终端应用）并勾选")
    logger.warning("\n授权后，请重新运行此程序。")
    logger.warning("===============================\n") 
