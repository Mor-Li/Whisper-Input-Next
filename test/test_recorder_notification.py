"""
测试 AudioRecorder 的系统通知功能
模拟设备错误时是否能正确发送通知
"""

import sys
sys.path.insert(0, '.')

from src.audio.recorder import AudioRecorder
from src.utils.logger import logger


def test_notification_on_device_error():
    """测试当设备错误时是否发送通知"""
    logger.info("=== 测试 AudioRecorder 通知功能 ===\n")

    # 初始化录音器
    recorder = AudioRecorder()

    logger.info("测试 1: 测试通知方法是否可用...")
    recorder._send_notification(
        title="测试通知",
        message="这是一条测试通知，验证通知功能正常工作",
        subtitle="功能测试"
    )
    logger.info("✅ 通知方法调用成功\n")

    logger.info("测试 2: 模拟设备断开场景...")
    logger.info("提示: 现在你可以拔掉外部麦克风（如果有的话）")
    logger.info("或者在系统设置中禁用麦克风权限来模拟设备错误")
    logger.info("\n准备好后按 Enter 开始测试...")
    input()

    try:
        recorder.start_recording()
        logger.info("✅ 录音启动成功（设备正常）")
        import time
        time.sleep(2)
        recorder.stop_recording()
    except Exception as e:
        logger.warning(f"⚠️ 录音启动失败（预期行为）: {e}")
        logger.info("💡 如果你看到了系统通知 '⚠️ 音频设备错误'，说明功能正常！")

    logger.info("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_notification_on_device_error()
