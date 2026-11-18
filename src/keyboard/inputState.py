from enum import Enum, auto


class InputState(Enum):
    """输入状态枚举"""
    IDLE = auto()               # 空闲
    RECORDING = auto()          # Ctrl+F 录音中（OpenAI 批量模式）
    RECORDING_LOCAL = auto()    # Ctrl+I 录音中（本地 Whisper）
    DOUBAO_STREAMING = auto()   # 豆包流式识别中（边说边转）
    PROCESSING = auto()         # Ctrl+F 处理中
    PROCESSING_LOCAL = auto()   # Ctrl+I 处理中
    ERROR = auto()              # 错误
    WARNING = auto()            # 警告（如录音时长不足）

    @property
    def can_start_recording(self):
        """只有 IDLE 状态才能开始新的录音"""
        return self == InputState.IDLE
