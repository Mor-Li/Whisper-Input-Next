#!/usr/bin/env python3
"""
测试 pynput 是否会导致光标移动的问题
"""

from pynput.keyboard import Controller
import time
import sys

def test_keyboard_input():
    """测试键盘输入是否会导致光标移动"""
    keyboard = Controller()
    
    print("=" * 50)
    print("pynput 光标移动测试")
    print("=" * 50)
    print("\n请将光标放在任何文本编辑器中的某个位置")
    print("程序将在5秒后自动输入字符")
    print("\n观察输入的字符是否在光标当前位置，还是向右移动了一个位置")
    print("=" * 50)
    
    # 倒计时
    for i in range(5, 0, -1):
        print(f"\r倒计时: {i} 秒...", end="", flush=True)
        time.sleep(1)
    
    print("\n\n开始测试...")
    
    # 测试1: 使用 type() 方法
    print("\n测试1: 使用 keyboard.type() 方法输入 '0'")
    time.sleep(1)
    keyboard.type('0')
    
    time.sleep(2)
    
    # 测试2: 使用 press/release 方法
    print("\n测试2: 使用 keyboard.press/release 方法输入 '1'")
    time.sleep(1)
    keyboard.press('1')
    keyboard.release('1')
    
    time.sleep(2)
    
    # 测试3: 连续输入多个字符
    print("\n测试3: 连续输入 'ABC'")
    time.sleep(1)
    keyboard.type('ABC')
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("\n请检查：")
    print("1. 字符 '0' 是否在光标原位置输入？")
    print("2. 字符 '1' 是否在光标原位置输入？")
    print("3. 字符 'ABC' 是否在光标原位置输入？")
    print("\n如果任何字符出现在光标右侧一个位置，说明是 pynput 的问题")
    print("=" * 50)

if __name__ == "__main__":
    try:
        test_keyboard_input()
    except KeyboardInterrupt:
        print("\n\n测试被中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n错误: {e}")
        sys.exit(1)