
from enum import Enum, auto

class InputState(Enum):
    """输入状态枚举"""
    IDLE = auto()           # 空闲状态
    RECORDING = auto()      # 正在录音
    RECORDING_TRANSLATE = auto()  # 正在录音(翻译模式)
    RECORDING_KIMI = auto()     # 正在录音(Kimi润色模式)
    PROCESSING = auto()     # 正在处理
    PROCESSING_KIMI = auto()    # 正在处理(Kimi润色模式)
    TRANSLATING = auto()    # 正在翻译
    ERROR = auto()          # 错误状态
    WARNING = auto()        # 警告状态（用于录音时长不足等提示）

    @property
    def is_recording(self):
        """检查是否处于录音状态"""
        return self in (InputState.RECORDING, InputState.RECORDING_TRANSLATE, InputState.RECORDING_KIMI)
    
    @property
    def can_start_recording(self):
        """检查是否可以开始新的录音"""
        return not self.is_recording
