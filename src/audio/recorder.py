import io
import sounddevice as sd
import numpy as np
import queue
import soundfile as sf
import os
import tempfile
from ..utils.logger import logger
import time
import threading

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
        """检查音频设备状态"""
        try:
            devices = sd.query_devices()
            default_input = sd.query_devices(kind='input')
            self.current_device = default_input['name']
            
            logger.info("\n=== 当前音频设备信息 ===")
            logger.info(f"默认输入设备: {self.current_device}")
            logger.info(f"支持的采样率: {int(default_input['default_samplerate'])}Hz")
            logger.info(f"最大输入通道数: {default_input['max_input_channels']}")
            logger.info("========================\n")
            
            # 如果默认采样率与我们的不同，使用设备的默认采样率
            if abs(default_input['default_samplerate'] - self.sample_rate) > 100:
                self.sample_rate = int(default_input['default_samplerate'])
                logger.info(f"调整采样率为: {self.sample_rate}Hz")
            
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
    
    def start_recording(self):
        """开始录音"""
        if not self.recording:
            try:
                # 检查设备是否发生变化
                self._check_device_changed()
                
                logger.info("开始录音...")
                self.recording = True
                self.record_start_time = time.time()
                self.audio_data = []
                
                def audio_callback(indata, frames, time, status):
                    if status:
                        logger.warning(f"音频录制状态: {status}")
                    if self.recording:
                        self.audio_queue.put(indata.copy())
                
                self.stream = sd.InputStream(
                    channels=1,
                    samplerate=self.sample_rate,
                    callback=audio_callback,
                    device=None,  # 使用默认设备
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
                logger.error(f"启动录音失败: {e}")
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