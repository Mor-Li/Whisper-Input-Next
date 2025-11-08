"""
测试 macOS 系统通知功能
"""

import subprocess
import sys


def send_notification(title, message, subtitle=""):
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
            text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 发送通知失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ 发送通知时出现异常: {e}")
        return False


def test_notifications():
    """测试不同类型的通知"""
    print("=== macOS 系统通知测试 ===\n")

    # 测试 1: 基本通知
    print("测试 1: 发送基本通知...")
    success = send_notification(
        title="Whisper Input Next",
        message="这是一条测试通知"
    )
    print(f"结果: {'✅ 成功' if success else '❌ 失败'}\n")

    # 测试 2: 带副标题的通知
    print("测试 2: 发送带副标题的通知...")
    success = send_notification(
        title="Whisper Input Next",
        message="音频设备可能已断开",
        subtitle="设备错误"
    )
    print(f"结果: {'✅ 成功' if success else '❌ 失败'}\n")

    # 测试 3: 模拟设备断开通知
    print("测试 3: 模拟设备断开通知...")
    success = send_notification(
        title="⚠️ 音频设备断开",
        message="外部麦克风可能已断开，请检查设备连接",
        subtitle="录音失败"
    )
    print(f"结果: {'✅ 成功' if success else '❌ 失败'}\n")

    print("=== 测试完成 ===")
    print("\n💡 提示: 如果你没有看到通知，请检查:")
    print("1. 系统设置 -> 通知 -> 终端（或你使用的终端应用）")
    print("2. 确保通知权限已开启")
    print("3. 确保通知样式设置为 '横幅' 或 '提醒'")


if __name__ == "__main__":
    test_notifications()
