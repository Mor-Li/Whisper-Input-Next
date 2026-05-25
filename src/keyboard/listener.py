from pynput.keyboard import Controller, Key, Listener
import pyperclip
from ..utils.logger import logger
import time
from .inputState import InputState
import os


class KeyboardManager:
    KEY_ALIASES = {
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "cmd": Key.cmd,
        "command": Key.cmd,
        "win": Key.cmd,
        "windows": Key.cmd,
        "super": Key.cmd,
    }
    KEY_DISPLAY_NAMES = {
        "ctrl": "Ctrl",
        "control": "Ctrl",
        "cmd": "Cmd",
        "command": "Cmd",
        "win": "Win",
        "windows": "Win",
        "super": "Win",
    }

    def __init__(self, on_record_start, on_record_stop, on_translate_start, on_translate_stop, on_kimi_start, on_kimi_stop, on_reset_state, on_state_change=None):
        self.keyboard = Controller()
        self.ctrl_pressed = False  # 快捷键修饰键状态
        self.f_pressed = False  # F键状态
        self.i_pressed = False  # I键状态
        self.temp_text_length = 0  # 用于跟踪临时文本的长度
        self.processing_text = None  # 用于跟踪正在处理的文本
        self.error_message = None  # 用于跟踪错误信息
        self.warning_message = None  # 用于跟踪警告信息
        self.is_recording = False  # toggle模式的录音状态
        self.last_key_time = 0  # 防止重复触发
        self.KEY_DEBOUNCE_TIME = 0.3  # 按键防抖时间（秒）
        
        
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
        self.system_platform = os.getenv("SYSTEM_PLATFORM", "").lower()
        if self.system_platform in ("win", "windows", "linux"):
            self.system_modifier = Key.ctrl
            logger.info("配置到Windows/Linux平台")
        else:
            self.system_modifier = Key.cmd
            logger.info("配置到Mac平台")
        

        # 获取转录按钮和快捷键修饰键
        self.transcriptions_button, transcriptions_display = self._resolve_button(
            "TRANSCRIPTIONS_BUTTON",
            "f",
        )
        self.translations_button, modifier_display = self._resolve_button(
            "TRANSLATIONS_BUTTON",
            "win",
        )

        logger.info(f"按 {modifier_display}+{transcriptions_display} 键：切换录音状态（转录模式）")
        logger.info(f"按 {modifier_display}+I 键：切换录音状态（本地 Whisper 模式）")
        logger.info(f"两种模式都是按一下开始，再按一下结束")

    def _resolve_button(self, env_name, default_value):
        """Resolve a keyboard setting into a pynput Key or single character."""
        button_name = (os.getenv(env_name, default_value) or default_value).strip().lower()
        resolved = self._parse_button(button_name)

        if resolved is None:
            logger.error(f"无效的快捷键配置 {env_name}={button_name}，回退到 {default_value}")
            button_name = default_value
            resolved = self._parse_button(button_name)

        logger.info(f"配置到快捷键 {env_name}：{button_name}")
        return resolved, self._display_button_name(button_name)

    @classmethod
    def _parse_button(cls, button_name):
        if len(button_name) == 1 and button_name.isalpha():
            return button_name

        if button_name in cls.KEY_ALIASES:
            return cls.KEY_ALIASES[button_name]

        try:
            return Key[button_name]
        except KeyError:
            return None

    @classmethod
    def _display_button_name(cls, button_name):
        if button_name in cls.KEY_DISPLAY_NAMES:
            return cls.KEY_DISPLAY_NAMES[button_name]
        if len(button_name) == 1:
            return button_name.upper()
        return button_name

    @staticmethod
    def _key_matches(key, configured_key):
        if isinstance(configured_key, str):
            return hasattr(key, "char") and key.char and key.char.lower() == configured_key

        if key == configured_key:
            return True

        aliases = []
        if configured_key == Key.ctrl:
            aliases = [getattr(Key, "ctrl_l", None), getattr(Key, "ctrl_r", None)]
        elif configured_key == Key.cmd:
            aliases = [getattr(Key, "cmd_l", None), getattr(Key, "cmd_r", None)]
        elif configured_key == Key.shift:
            aliases = [getattr(Key, "shift_l", None), getattr(Key, "shift_r", None)]
        elif configured_key == Key.alt:
            aliases = [getattr(Key, "alt_l", None), getattr(Key, "alt_r", None)]

        return any(alias is not None and key == alias for alias in aliases)
    
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
    
    def _paste_text_from_clipboard(self, text: str) -> None:
        pyperclip.copy(text)
        hotkey = os.getenv("PASTE_HOTKEY")
        if not hotkey:
            if self.system_platform == "linux":
                hotkey = "ctrl+shift+v"
            elif self.system_platform in ("win", "windows"):
                hotkey = "ctrl+v"
            else:
                hotkey = "cmd+v"

        normalized = hotkey.replace("+", "+").lower()
        key_map = {
            "ctrl": Key.ctrl,
            "control": Key.ctrl,
            "cmd": Key.cmd,
            "command": Key.cmd,
            "shift": Key.shift,
            "alt": Key.alt,
            "option": Key.alt,
        }
        parts = [part for part in normalized.split("+") if part]
        modifiers = [key_map[part] for part in parts[:-1] if part in key_map]
        final_key = parts[-1] if parts else "v"

        try:
            for modifier in modifiers:
                self.keyboard.press(modifier)
            self.keyboard.press(final_key)
            self.keyboard.release(final_key)
            for modifier in reversed(modifiers):
                self.keyboard.release(modifier)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"无法发送粘贴快捷键 {hotkey}: {exc}") from exc

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
            self._paste_text_from_clipboard(text)
            
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
            self._paste_text_from_clipboard(text)
        
        # 更新临时文本长度
        self.temp_text_length = len(text)
    
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
                self.state = InputState.RECORDING
                logger.info("🎤 开始录音（转录模式）")
        else:
            # 停止录音
            self.is_recording = False
            self.state = InputState.PROCESSING
            logger.info("⏹️ 停止录音（转录模式）")
    
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
                self.state = InputState.RECORDING_KIMI
                logger.info("🎤 开始录音（本地 Whisper 模式）")
        else:
            # 停止录音
            self.is_recording = False
            self.state = InputState.PROCESSING_KIMI
            logger.info("⏹️ 停止录音（本地 Whisper 模式）")

    def on_press(self, key):
        """按键按下时的回调"""
        try:
            # 检查转录按钮（字符键或特殊键）
            is_transcription_key = self._key_matches(key, self.transcriptions_button)
                
            # 检查快捷键修饰键（如 Win/Ctrl/Cmd）
            is_translation_key = self._key_matches(key, self.translations_button)
            
            # 检查I键（用于本地 Whisper 模式）
            if hasattr(key, 'char') and key.char == 'i':
                self.i_pressed = True
                # 检查是否同时按下了修饰键+i（本地 Whisper 模式）
                if self.ctrl_pressed and self.i_pressed:
                    self.toggle_kimi_recording()
            elif is_transcription_key:  # F键
                self.f_pressed = True
                # 检查是否同时按下了修饰键+f
                if self.ctrl_pressed and self.f_pressed:
                    self.toggle_recording()
            elif is_translation_key:  # 快捷键修饰键
                self.ctrl_pressed = True
                # 检查是否同时按下了修饰键+f（默认转录模式）
                if self.ctrl_pressed and self.f_pressed:
                    self.toggle_recording()
                # 检查是否同时按下了修饰键+i（本地 Whisper 模式）
                elif self.ctrl_pressed and self.i_pressed:
                    self.toggle_kimi_recording()
        except AttributeError:
            pass

    def on_release(self, key):
        """按键释放时的回调"""
        try:
            # 检查转录按钮（字符键或特殊键）
            is_transcription_key = self._key_matches(key, self.transcriptions_button)
                
            # 检查快捷键修饰键（如 Win/Ctrl/Cmd）
            is_translation_key = self._key_matches(key, self.translations_button)
                
            # 检查I键释放
            if hasattr(key, 'char') and key.char == 'i':
                self.i_pressed = False
            elif is_transcription_key:  # F键释放
                self.f_pressed = False
            elif is_translation_key:  # 快捷键修饰键释放
                self.ctrl_pressed = False

        except AttributeError:
            pass
    
    def start_listening(self):
        """开始监听键盘事件"""
        with Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def reset_state(self):
        """重置所有状态和临时文本"""
        # 清除临时文本
        self._delete_previous_text()
        
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
