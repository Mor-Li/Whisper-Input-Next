import io
import sounddevice as sd
import numpy as np
import queue
import soundfile as sf
import subprocess
from ..utils.logger import logger
import time
import threading

# 允许的设备关键字（按优先级从高到低）
# 只允许这些设备，其他设备不使用
ALLOWED_DEVICE_KEYWORDS = [
    "external microphone",    # 外接麦克风/耳机（最高优先级）
    "macbook pro microphone", # 内置麦克风
    "airpods",                # AirPods 蓝牙耳机
]


class AudioRecorder:
    def __init__(self):
        self.recording = False
        self.audio_queue = queue.Queue()
        self.sample_rate = 16000
        # self.temp_dir = tempfile.mkdtemp()
        self.current_device = None
        self.record_start_time = None
        self.min_record_duration = 1.0  # 最小录音时长（秒）
        self.max_record_duration = 600.0  # 最大录音时长（10分钟）
        self.auto_stop_timer = None  # 自动停止定时器
        self.auto_stop_callback = None  # 自动停止时的回调函数
        self.device_disconnect_callback = None  # 设备断开时的回调函数
        self._device_error_detected = False  # 标记是否检测到设备错误
        self._last_used_device = None  # 上次录音使用的设备（用于判断是否切换）
        self._check_audio_devices()
        # logger.info(f"初始化完成，临时文件目录: {self.temp_dir}")
        logger.info(f"初始化完成，最大录音时长: {self.max_record_duration/60:.1f}分钟")
    
    def _list_audio_devices(self):
        """列出所有可用的音频输入设备"""
        devices = sd.query_devices()
        logger.info("\n=== 可用的音频输入设备 ===")
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:  # 只显示输入设备
                status = "默认设备 ✓" if device['name'] == self.current_device else ""
                logger.info(f"{i}: {device['name']} "
                          f"(采样率: {int(device['default_samplerate'])}Hz, "
                          f"通道数: {device['max_input_channels']}) {status}")
        logger.info("========================\n")
    
    def _check_audio_devices(self):
        """检查音频设备状态，使用白名单选择最佳设备"""
        try:
            # 使用白名单选择最佳设备
            device_idx, best_device = self._get_best_input_device()

            if best_device is not None:
                self.current_device = best_device['name']
                self.sample_rate = int(best_device['default_samplerate'])
            else:
                # 没有白名单设备，使用系统默认
                default_input = sd.query_devices(kind='input')
                self.current_device = default_input['name']
                self.sample_rate = int(default_input['default_samplerate'])

            logger.info("\n=== 当前音频设备信息 ===")
            logger.info(f"选择的输入设备: {self.current_device}")
            logger.info(f"支持的采样率: {self.sample_rate}Hz")
            logger.info("========================\n")

            # 列出所有可用设备
            self._list_audio_devices()

        except Exception as e:
            logger.error(f"检查音频设备时出错: {e}")
            raise RuntimeError("无法访问音频设备，请检查系统权限设置")
    
    def _check_device_changed(self):
        """检查默认音频设备是否发生变化"""
        try:
            default_input = sd.query_devices(kind='input')
            if default_input['name'] != self.current_device:
                logger.warning(f"\n音频设备已切换:")
                logger.warning(f"从: {self.current_device}")
                logger.warning(f"到: {default_input['name']}\n")
                self.current_device = default_input['name']
                self._check_audio_devices()
                return True
            return False
        except Exception as e:
            logger.error(f"检查设备变化时出错: {e}")
            return False

    def _get_best_input_device(self):
        """根据优先级选择最佳输入设备（只从白名单中选择）

        Returns:
            tuple: (device_index, device_info) 或 (None, None) 如果没有可用设备
        """
        try:
            # 刷新设备列表（检测新插入的设备）
            sd._terminate()
            sd._initialize()

            devices = sd.query_devices()
            input_devices = [(i, d) for i, d in enumerate(devices) if d['max_input_channels'] > 0]

            # 按优先级从高到低匹配白名单设备
            for keyword in ALLOWED_DEVICE_KEYWORDS:
                for idx, device in input_devices:
                    if keyword.lower() in device['name'].lower():
                        logger.debug(f"找到匹配设备: {device['name']} (优先级关键字: {keyword})")
                        return idx, device

            # 没有找到白名单设备
            logger.warning("没有找到白名单中的可用设备")
            return None, None
        except Exception as e:
            logger.error(f"选择最佳设备时出错: {e}")
            return None, None
    
    def _auto_stop_recording(self):
        """自动停止录音（达到最大时长）"""
        logger.warning(f"⏰ 录音已达到最大时长（{self.max_record_duration/60:.1f}分钟），自动中止录音")
        
        # 如果有自动停止回调，则调用它
        if self.auto_stop_callback:
            self.auto_stop_callback()
        else:
            # 否则直接中止录音（abort=True）
            self.stop_recording(abort=True)
    
    def set_auto_stop_callback(self, callback):
        """设置自动停止时的回调函数"""
        self.auto_stop_callback = callback

    def set_device_disconnect_callback(self, callback):
        """设置设备断开时的回调函数"""
        self.device_disconnect_callback = callback

    def _handle_device_disconnect(self):
        """处理录音过程中设备断开"""
        if not self.recording:
            return

        logger.warning("录音过程中检测到设备断开，保存已录内容")

        # 发送系统通知
        self._send_notification(
            title="音频设备已断开",
            message="录音已停止，正在转录已录制内容",
            subtitle="设备断开"
        )

        # 触发回调（会调用 VoiceAssistant 的停止录音方法）
        if self.device_disconnect_callback:
            # 在新线程中调用回调，避免阻塞音频回调
            threading.Thread(target=self.device_disconnect_callback, daemon=True).start()

    def _send_notification(self, title, message, subtitle=""):
        """
        发送 macOS 系统通知

        Args:
            title: 通知标题
            message: 通知内容
            subtitle: 通知副标题（可选）
        """
        try:
            # 构建 osascript 命令
            script = f'display notification "{message}" with title "{title}"'
            if subtitle:
                script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'

            # 执行 AppleScript
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
                timeout=2  # 设置超时避免阻塞
            )
        except Exception as e:
            # 通知失败不影响主流程，只记录日志
            logger.debug(f"发送系统通知失败: {e}")

    def start_recording(self):
        """开始录音"""
        if not self.recording:
            try:
                # 选择最佳设备
                device_idx, best_device = self._get_best_input_device()

                if best_device is None:
                    # 没有可用的白名单设备
                    self._send_notification(
                        title="无可用音频设备",
                        message="请连接麦克风",
                        subtitle="录音失败"
                    )
                    raise RuntimeError("没有可用的音频输入设备")

                # 检查设备是否切换
                new_device_name = best_device['name']
                logger.info(f"设备选择: 最佳设备={new_device_name}, 上次使用={self._last_used_device}")
                device_switched = (self._last_used_device is not None and
                                   self._last_used_device != new_device_name)
                first_recording = (self._last_used_device is None)

                # 更新当前设备和采样率
                self.current_device = new_device_name
                self.sample_rate = int(best_device['default_samplerate'])
                self._last_used_device = new_device_name

                logger.info("开始录音...")
                self.recording = True
                self.record_start_time = time.time()
                self.audio_data = []
                self._device_error_detected = False  # 重置设备错误标志

                # 只有在设备切换或第一次录音时才发送通知
                if device_switched or first_recording:
                    if device_switched:
                        self._send_notification(
                            title="音频设备已切换",
                            message=f"使用: {self.current_device}",
                            subtitle=""
                        )
                    else:
                        self._send_notification(
                            title="开始录音",
                            message=f"使用: {self.current_device}",
                            subtitle=""
                        )

                def audio_callback(indata, frames, time, status):
                    if status:
                        status_str = str(status).lower()
                        logger.warning(f"音频录制状态: {status}")
                        # 检测设备断开错误（排除普通的 overflow）
                        if ("input" in status_str or "device" in status_str) and "overflow" not in status_str:
                            if not self._device_error_detected:
                                self._device_error_detected = True
                                self._handle_device_disconnect()
                            return
                    if self.recording:
                        self.audio_queue.put(indata.copy())

                self.stream = sd.InputStream(
                    channels=1,
                    samplerate=self.sample_rate,
                    callback=audio_callback,
                    device=device_idx,  # 使用选定的设备
                    latency='low'  # 使用低延迟模式
                )
                self.stream.start()
                logger.info(f"音频流已启动 (设备: {self.current_device})")
                
                # 设置自动停止定时器
                self.auto_stop_timer = threading.Timer(self.max_record_duration, self._auto_stop_recording)
                self.auto_stop_timer.start()
                logger.info(f"⏱️  已设置自动停止定时器: {self.max_record_duration/60:.1f}分钟后自动停止")
            except Exception as e:
                self.recording = False
                error_msg = str(e)
                logger.error(f"启动录音失败: {error_msg}")

                # 发送系统通知
                self._send_notification(
                    title="⚠️ 音频设备错误",
                    message="麦克风可能已断开，请检查设备连接",
                    subtitle="录音启动失败"
                )

                raise
    
    def stop_recording(self, abort=False):
        """停止录音并返回音频数据
        
        Args:
            abort: 是否放弃录音（不返回音频数据）
        """
        if not self.recording:
            return None
            
        logger.info("停止录音...")
        self.recording = False
        self.stream.stop()
        self.stream.close()
        
        # 取消自动停止定时器（如果存在）
        if self.auto_stop_timer and self.auto_stop_timer.is_alive():
            self.auto_stop_timer.cancel()
            logger.info("✅ 已取消自动停止定时器")
        
        # 如果是abort，直接返回None
        if abort:
            logger.warning("⚠️ 录音已被中止，音频数据已丢弃")
            # 清空音频队列
            while not self.audio_queue.empty():
                self.audio_queue.get()
            return None
        
        # 检查录音时长
        if self.record_start_time:
            record_duration = time.time() - self.record_start_time
            logger.info(f"📏 录音时长: {record_duration:.1f}秒 ({record_duration/60:.1f}分钟)")
            if record_duration < self.min_record_duration:
                logger.warning(f"录音时长太短 ({record_duration:.1f}秒 < {self.min_record_duration}秒)")
                return "TOO_SHORT"
        
        # 收集所有音频数据
        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
        
        if not audio_data:
            logger.warning("没有收集到音频数据")
            return None
            
        # 合并音频数据
        audio = np.concatenate(audio_data)
        logger.info(f"音频数据长度: {len(audio)} 采样点")

        # 将 numpy 数组转换为字节流
        audio_buffer = io.BytesIO()
        sf.write(audio_buffer, audio, self.sample_rate, format='WAV')
        audio_buffer.seek(0)  # 将缓冲区指针移动到开始位置
        
        return audio_buffer