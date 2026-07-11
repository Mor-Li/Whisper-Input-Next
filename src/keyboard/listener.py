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
    def __init__(self, on_record_start, on_record_stop, on_translate_start, on_translate_stop, on_kimi_start, on_kimi_stop, on_reset_state, on_state_change=None):
        self.keyboard = Controller()
        self.ctrl_pressed = False  # 改为ctrl键状态
        self.f_pressed = False  # F键状态
        self.i_pressed = False  # I键状态
        self.temp_text_length = 0  # 用于跟踪临时文本的长度
        self.processing_text = None  # 用于跟踪正在处理的文本
        self.error_message = None  # 用于跟踪错误信息
        self.warning_message = None  # 用于跟踪警告信息
        self.is_recording = False  # toggle模式的录音状态
        self.last_key_time = 0  # 防止重复触发
        self.KEY_DEBOUNCE_TIME = 0.3  # 按键防抖时间（秒）
        self._original_clipboard = None  # 保存原始剪贴板内容

        # macOS 事件拦截：需要吞掉的组合键虚拟键码集合 + 修饰键掩码
        # （在 start_listening 里根据实际配置计算）
        self._suppress_vks = set()
        self._suppress_modifier_mask = 0

        # tap 自愈：当前 listener 引用 + 禁用告警的限频时间戳
        self._listener = None
        self._tap_disabled_log_time = 0.0
        
        
        # 回调函数
        self.on_record_start = on_record_start
        self.on_record_stop = on_record_stop
        self.on_translate_start = on_translate_start
        self.on_translate_stop = on_translate_stop
        self.on_kimi_start = on_kimi_start
        self.on_kimi_stop = on_kimi_stop
        self.on_reset_state = on_reset_state
        self.on_state_change = on_state_change

        
        # 状态管理
        self._state = InputState.IDLE
        self._state_messages = {
            InputState.IDLE: "",
            InputState.RECORDING: "0",
            InputState.RECORDING_TRANSLATE: "0",
            InputState.RECORDING_KIMI: "0",
            InputState.PROCESSING: "1",
            InputState.PROCESSING_KIMI: "1",
            InputState.TRANSLATING: "1",
            InputState.ERROR: lambda msg: f"{msg}",  # 错误消息使用函数动态生成
            InputState.WARNING: lambda msg: f"! {msg}"  # 警告消息使用感叹号
        }

        self.state_symbol_enabled = True

        # 获取系统平台
        sysetem_platform = os.getenv("SYSTEM_PLATFORM")
        if sysetem_platform == "win" :
            self.sysetem_platform = Key.ctrl
            logger.info("配置到Windows平台")
        else:
            self.sysetem_platform = Key.cmd
            logger.info("配置到Mac平台")
        

        # 获取转录和翻译按钮
        transcriptions_button = os.getenv("TRANSCRIPTIONS_BUTTON")
        try:
            # 字符键（如f）直接使用字符串，特殊键使用Key枚举
            if len(transcriptions_button) == 1 and transcriptions_button.isalpha():
                self.transcriptions_button = transcriptions_button
            else:
                self.transcriptions_button = Key[transcriptions_button]
            logger.info(f"配置到转录按钮：{transcriptions_button}")
        except KeyError:
            logger.error(f"无效的转录按钮配置：{transcriptions_button}")

        translations_button = os.getenv("TRANSLATIONS_BUTTON")
        try:
            # 字符键（如f）直接使用字符串，特殊键使用Key枚举
            if len(translations_button) == 1 and translations_button.isalpha():
                self.translations_button = translations_button
            else:
                self.translations_button = Key[translations_button]
            logger.info(f"配置到翻译按钮(与转录按钮组合)：{translations_button}")
        except KeyError:
            logger.error(f"无效的翻译按钮配置：{translations_button}")

        logger.info(f"按 {translations_button} + {transcriptions_button} 键：切换录音状态（OpenAI GPT-4o transcribe 模式）")
        logger.info(f"按 {translations_button} + I 键：切换录音状态（本地 Whisper 模式）")
        logger.info(f"两种模式都是按一下开始，再按一下结束")
    
    @property
    def state(self):
        """获取当前状态"""
        return self._state
    
    @state.setter
    def state(self, new_state):
        """设置新状态并更新UI"""
        if new_state != self._state:
            self._state = new_state
            
            # 获取状态消息
            message = self._state_messages[new_state]
            
            # 根据状态转换类型显示不同消息
            if new_state == InputState.RECORDING:
                # 录音状态
                self.temp_text_length = 0
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.on_record_start()
                
            elif new_state == InputState.RECORDING_TRANSLATE:
                # 翻译,录音状态
                self.temp_text_length = 0
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.on_translate_start()
                
            elif new_state == InputState.RECORDING_KIMI:
                # 本地 Whisper 录音状态
                self.temp_text_length = 0
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.on_kimi_start()

            elif new_state == InputState.PROCESSING:
                self._delete_previous_text()
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.processing_text = message
                self.on_record_stop()
                
            elif new_state == InputState.PROCESSING_KIMI:
                # 本地 Whisper 处理状态
                self._delete_previous_text()
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.processing_text = message
                self.on_kimi_stop()

            elif new_state == InputState.TRANSLATING:
                # 翻译状态
                self._delete_previous_text()                 
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.processing_text = message
                self.on_translate_stop()
            
            elif new_state == InputState.WARNING:
                # 警告状态
                message = message(self.warning_message)
                self._delete_previous_text()
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.warning_message = None
                self._schedule_message_clear()     
            
            elif new_state == InputState.ERROR:
                # 错误状态
                message = message(self.error_message)
                self._delete_previous_text()
                if self.state_symbol_enabled:
                    self.type_temp_text(message)
                self.error_message = None
                self._schedule_message_clear()  
        
            elif new_state == InputState.IDLE:
                # 空闲状态，清除所有临时文本
                self.processing_text = None
            
            else:
                # 其他状态
                if self.state_symbol_enabled:
                    self.type_temp_text(message)

            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"状态回调异常: {exc}")

    def set_state_symbol_enabled(self, enabled: bool):
        """开启或关闭在输入框内展示状态符号"""
        self.state_symbol_enabled = enabled
    
    def _schedule_message_clear(self):
        """计划清除消息"""
        def clear_message():
            time.sleep(2)  # 警告消息显示2秒
            self.state = InputState.IDLE
        
        import threading
        threading.Thread(target=clear_message, daemon=True).start()
    
    def show_warning(self, warning_message):
        """显示警告消息"""
        self.warning_message = warning_message
        self.state = InputState.WARNING
    
    def show_error(self, error_message):
        """显示错误消息"""
        self.error_message = error_message
        self.state = InputState.ERROR
    
    def _save_clipboard(self):
        """保存当前剪贴板内容"""
        if self._original_clipboard is None:
            self._original_clipboard = pyperclip.paste()

    def _restore_clipboard(self):
        """恢复原始剪贴板内容"""
        if self._original_clipboard is not None:
            pyperclip.copy(self._original_clipboard)
            self._original_clipboard = None

    def keep_clipboard_text(self, text):
        """将指定文本保留到剪贴板，避免后续状态重置恢复旧内容。"""
        if not text:
            return False

        try:
            pyperclip.copy(text)
            self._original_clipboard = None
            logger.info("已将兜底转录文本保留到剪贴板")
            return True
        except Exception as e:
            logger.warning(f"保留兜底转录文本到剪贴板失败: {e}")
            return False

    def type_text(self, text, error_message=None):
        """将文字输入到当前光标位置
        
        Args:
            text: 要输入的文本或包含文本和错误信息的元组
            error_message: 错误信息
        """
        # 如果text是元组，说明是从process_audio返回的结果
        if isinstance(text, tuple):
            text, error_message = text
            
        if error_message:
            self.show_error(error_message)
            return
            
        if not text:
            # 如果没有文本且不是错误，可能是录音时长不足
            if self.state in (InputState.PROCESSING, InputState.TRANSLATING):
                self.show_warning("录音时长过短，请至少录制1秒")
            return
            
        try:
            logger.info("正在输入转录文本...")
            self._delete_previous_text()
            
            # 最终转录文本通过剪贴板输入
            pyperclip.copy(text)
            
            # 模拟 Ctrl + V 粘贴文本
            with self.keyboard.pressed(self.sysetem_platform):
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
    
    def _delete_previous_text(self):
        """删除之前输入的临时文本"""
        if self.temp_text_length > 0:
            # 添加0.2秒延迟，让删除操作更自然
            import time
            time.sleep(0.2)
            
            for _ in range(self.temp_text_length):
                self.keyboard.press(Key.backspace)
                self.keyboard.release(Key.backspace)

        self.temp_text_length = 0
    
    def type_temp_text(self, text):
        """输入临时状态文本"""
        if not text or not self.state_symbol_enabled:
            return
            
        # 判断是否为状态符号（现在使用数字）
        is_status_symbol = text in ['0', '1']
        
        if is_status_symbol:
            # 状态符号直接输入，不使用剪贴板
            try:
                self.keyboard.type(text)
            except Exception as e:
                # 如果直接输入失败，记录错误但不中断程序
                logger.warning(f"直接输入状态符号失败: {e}, 文本: {text}")
        else:
            # 其他文本（如错误消息、警告等）通过剪贴板输入
            pyperclip.copy(text)
            with self.keyboard.pressed(self.sysetem_platform):
                self.keyboard.press('v')
                self.keyboard.release('v')
        
        # 更新临时文本长度
        self.temp_text_length = len(text)
    
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

    def toggle_recording(self):
        """切换录音状态"""
        current_time = time.time()

        # 防抖处理
        if current_time - self.last_key_time < self.KEY_DEBOUNCE_TIME:
            return

        self.last_key_time = current_time
        
        if not self.is_recording:
            # 开始录音
            if self.state.can_start_recording:
                self.is_recording = True
                self._set_state_async(InputState.RECORDING)
                logger.info("🎤 开始录音（OpenAI GPT-4o transcribe 模式）")
        else:
            # 停止录音
            self.is_recording = False
            self._set_state_async(InputState.PROCESSING)
            logger.info("⏹️ 停止录音（OpenAI GPT-4o transcribe 模式）")
    
    def toggle_kimi_recording(self):
        """切换本地 Whisper 录音状态"""
        current_time = time.time()

        # 防抖处理
        if current_time - self.last_key_time < self.KEY_DEBOUNCE_TIME:
            return

        self.last_key_time = current_time
        
        if not self.is_recording:
            # 开始录音
            if self.state.can_start_recording:
                self.is_recording = True
                self._set_state_async(InputState.RECORDING_KIMI)
                logger.info("🎤 开始录音（本地 Whisper 模式）")
        else:
            # 停止录音
            self.is_recording = False
            self._set_state_async(InputState.PROCESSING_KIMI)
            logger.info("⏹️ 停止录音（本地 Whisper 模式）")

    def on_press(self, key):
        """按键按下时的回调"""
        try:
            # 检查转录按钮（字符键或特殊键）
            is_transcription_key = False
            if isinstance(self.transcriptions_button, str):
                # 字符键
                is_transcription_key = hasattr(key, 'char') and key.char == self.transcriptions_button
            else:
                # 特殊键
                is_transcription_key = key == self.transcriptions_button
                
            # 检查翻译按钮（字符键或特殊键）
            is_translation_key = False
            if isinstance(self.translations_button, str):
                # 字符键
                is_translation_key = hasattr(key, 'char') and key.char == self.translations_button
            else:
                # 特殊键
                is_translation_key = key == self.translations_button
            
            # 检查I键（用于本地 Whisper 模式）
            if hasattr(key, 'char') and key.char == 'i':
                self.i_pressed = True
                # 检查是否同时按下了ctrl+i（本地 Whisper 模式）
                if self.ctrl_pressed and self.i_pressed:
                    self.toggle_kimi_recording()
            elif is_transcription_key:  # F键
                self.f_pressed = True
                # 检查是否同时按下了ctrl+f
                if self.ctrl_pressed and self.f_pressed:
                    self.toggle_recording()
            elif is_translation_key:  # Ctrl键
                self.ctrl_pressed = True
                # 检查是否同时按下了ctrl+f（OpenAI GPT-4o transcribe 模式）
                if self.ctrl_pressed and self.f_pressed:
                    self.toggle_recording()
                # 检查是否同时按下了ctrl+i（本地 Whisper 模式）
                elif self.ctrl_pressed and self.i_pressed:
                    self.toggle_kimi_recording()
        except AttributeError:
            pass

    def on_release(self, key):
        """按键释放时的回调"""
        try:
            # 检查转录按钮（字符键或特殊键）
            is_transcription_key = False
            if isinstance(self.transcriptions_button, str):
                # 字符键
                is_transcription_key = hasattr(key, 'char') and key.char == self.transcriptions_button
            else:
                # 特殊键
                is_transcription_key = key == self.transcriptions_button
                
            # 检查翻译按钮（字符键或特殊键）
            is_translation_key = False
            if isinstance(self.translations_button, str):
                # 字符键
                is_translation_key = hasattr(key, 'char') and key.char == self.translations_button
            else:
                # 特殊键
                is_translation_key = key == self.translations_button
                
            # 检查I键释放
            if hasattr(key, 'char') and key.char == 'i':
                self.i_pressed = False
            elif is_transcription_key:  # F键释放
                self.f_pressed = False
            elif is_translation_key:  # Ctrl键释放
                self.ctrl_pressed = False

        except AttributeError:
            pass
    
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
        mask = modifier_masks.get(self.translations_button, kCGEventFlagMaskControl)
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

    def reset_state(self, *, restore_clipboard=True):
        """重置所有状态和临时文本"""
        # 清除临时文本
        self._delete_previous_text()
        
        # 恢复剪贴板。异常兜底输出时会跳过恢复，保留救援文本给用户手动粘贴。
        if restore_clipboard:
            self._restore_clipboard()
        else:
            self._original_clipboard = None
        
        # 重置状态标志
        self.ctrl_pressed = False
        self.f_pressed = False
        self.i_pressed = False
        self.is_recording = False
        self.last_key_time = time.time()
        self.processing_text = None
        self.error_message = None
        self.warning_message = None
        
        # 设置为空闲状态
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
