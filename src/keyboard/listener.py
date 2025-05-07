from pynput.keyboard import Controller, Key, Listener
import pyperclip
from ..utils.logger import logger
import time
from .inputState import InputState
import os


class KeyboardManager:
    def __init__(self, on_record_start, on_record_stop, on_translate_start, on_translate_stop, on_reset_state):
        self.keyboard = Controller()
        self.option_pressed = False
        self.shift_pressed = False
        self.temp_text_length = 0  # 用于跟踪临时文本的长度
        self.processing_text = None  # 用于跟踪正在处理的文本
        self.error_message = None  # 用于跟踪错误信息
        self.warning_message = None  # 用于跟踪警告信息
        self.option_press_time = None  # 记录 Option 按下的时间戳
        self.PRESS_DURATION_THRESHOLD = 0.5  # 按键持续时间阈值（秒）
        self.is_checking_duration = False  # 用于控制定时器线程
        self.has_triggered = False  # 用于防止重复触发
        self._original_clipboard = None  # 保存原始剪贴板内容
        
        
        # 回调函数
        self.on_record_start = on_record_start
        self.on_record_stop = on_record_stop
        self.on_translate_start = on_translate_start
        self.on_translate_stop = on_translate_stop
        self.on_reset_state = on_reset_state

        
        # 状态管理
        self._state = InputState.IDLE
        self._state_messages = {
            InputState.IDLE: "",
            InputState.RECORDING: "🎤 正在录音...",
            InputState.RECORDING_TRANSLATE: "🎤 正在录音 (翻译模式)",
            InputState.PROCESSING: "🔄 正在转录...",
            InputState.TRANSLATING: "🔄 正在翻译...",
            InputState.ERROR: lambda msg: f"{msg}",  # 错误消息使用函数动态生成
            InputState.WARNING: lambda msg: f"⚠️ {msg}"  # 警告消息使用函数动态生成
        }

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
            self.transcriptions_button = Key[transcriptions_button]
            logger.info(f"配置到转录按钮：{transcriptions_button}")
        except KeyError:
            logger.error(f"无效的转录按钮配置：{transcriptions_button}")

        translations_button = os.getenv("TRANSLATIONS_BUTTON")
        try:
            self.translations_button = Key[translations_button]
            logger.info(f"配置到翻译按钮(与转录按钮组合)：{translations_button}")
        except KeyError:
            logger.error(f"无效的翻译按钮配置：{translations_button}")

        logger.info(f"按住 {transcriptions_button} + {translations_button} 键：实时语音转录")
        logger.info(f"单独按住 {transcriptions_button} 键：不执行任何操作")
    
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
                self.type_temp_text(message)
                self.on_record_start()
                
            elif new_state == InputState.RECORDING_TRANSLATE:
                # 翻译,录音状态
                self.temp_text_length = 0
                self.type_temp_text(message)
                self.on_translate_start()

            elif new_state == InputState.PROCESSING:
                self._delete_previous_text()
                self.type_temp_text(message)
                self.processing_text = message
                self.on_record_stop()

            elif new_state == InputState.TRANSLATING:
                # 翻译状态
                self._delete_previous_text()                 
                self.type_temp_text(message)
                self.processing_text = message
                self.on_translate_stop()
            
            elif new_state == InputState.WARNING:
                # 警告状态
                message = message(self.warning_message)
                self._delete_previous_text()
                self.type_temp_text(message)
                self.warning_message = None
                self._schedule_message_clear()     
            
            elif new_state == InputState.ERROR:
                # 错误状态
                message = message(self.error_message)
                self._delete_previous_text()
                self.type_temp_text(message)
                self.error_message = None
                self._schedule_message_clear()  
        
            elif new_state == InputState.IDLE:
                # 空闲状态，清除所有临时文本
                self.processing_text = None
            
            else:
                # 其他状态
                self.type_temp_text(message)
    
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
            
            # 先输入文本和完成标记
            self.type_temp_text(text+" ✅")
            
            # 等待一小段时间确保文本已输入
            time.sleep(0.5)
            
            # 删除完成标记（2个字符：空格和✅）
            self.temp_text_length = 2
            self._delete_previous_text()
            
            # 将转录结果复制到剪贴板
            if os.getenv("KEEP_ORIGINAL_CLIPBOARD", "true").lower() != "true":
                pyperclip.copy(text)
            else:
                # 恢复原始剪贴板内容
                self._restore_clipboard()
            
            logger.info("文本输入完成")
            
            # 清理处理状态
            self.state = InputState.IDLE
        except Exception as e:
            logger.error(f"文本输入失败: {e}")
            self.show_error(f"❌ 文本输入失败: {e}")
    
    def _delete_previous_text(self):
        """删除之前输入的临时文本"""
        if self.temp_text_length > 0:
            for _ in range(self.temp_text_length):
                self.keyboard.press(Key.backspace)
                self.keyboard.release(Key.backspace)

        self.temp_text_length = 0
    
    def type_temp_text(self, text):
        """输入临时状态文本"""
        if not text:
            return
            
        # 将文本复制到剪贴板
        pyperclip.copy(text)

        # 模拟 Ctrl + V 粘贴文本
        with self.keyboard.pressed(self.sysetem_platform):
            self.keyboard.press('v')
            self.keyboard.release('v')

        # 更新临时文本长度
        self.temp_text_length = len(text)
    
    def start_duration_check(self):
        """开始检查按键持续时间"""
        if self.is_checking_duration:
            return

        def check_duration():
            while self.is_checking_duration and self.option_pressed:
                current_time = time.time()
                if (not self.has_triggered and 
                    self.option_press_time and 
                    (current_time - self.option_press_time) >= self.PRESS_DURATION_THRESHOLD):
                    
                    # 达到阈值时触发相应功能
                    if self.option_pressed and self.shift_pressed and self.state.can_start_recording:
                        self.state = InputState.RECORDING
                        self.has_triggered = True
                    # 移除单独按 Option 键触发录音的逻辑
                
                time.sleep(0.01)  # 短暂休眠以降低 CPU 使用率

        self.is_checking_duration = True
        import threading
        threading.Thread(target=check_duration, daemon=True).start()

    def on_press(self, key):
        """按键按下时的回调"""
        try:
            if key == self.transcriptions_button: #Key.f8:  # Option 键按下
                # 在开始任何操作前保存剪贴板内容
                if self._original_clipboard is None:
                    self._original_clipboard = pyperclip.paste()
                    
                self.option_pressed = True
                self.option_press_time = time.time()
                self.start_duration_check()
            elif key == self.translations_button:
                self.shift_pressed = True
        except AttributeError:
            pass

    def on_release(self, key):
        """按键释放时的回调"""
        try:
            if key == self.transcriptions_button:# Key.f8:  # Option 键释放
                self.option_pressed = False
                self.option_press_time = None
                self.is_checking_duration = False
                
                if self.has_triggered:
                    self.state = InputState.PROCESSING
                    self.has_triggered = False
            elif key == self.translations_button:#Key.f7:
                self.shift_pressed = False
                # 移除独立处理翻译键释放的逻辑
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
        
        # 恢复剪贴板
        self._restore_clipboard()
        
        # 重置状态标志
        self.option_pressed = False
        self.shift_pressed = False
        self.option_press_time = None
        self.is_checking_duration = False
        self.has_triggered = False
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