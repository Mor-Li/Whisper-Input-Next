#!/usr/bin/env python3
"""
测试在 Listener 上下文中 pynput 是否会导致光标移动
模拟实际的快捷键监听和输入场景
"""

from pynput.keyboard import Controller, Key, Listener
import time
import threading

class TestKeyboardListener:
    def __init__(self):
        self.keyboard = Controller()
        self.ctrl_pressed = False
        self.f_pressed = False
        
    def type_status(self, text):
        """模拟输入状态符号"""
        print(f"\n正在输入: '{text}'")
        
        # 方法1: 使用 type()
        # self.keyboard.type(text)
        
        # 方法2: 使用 press/release
        self.keyboard.press(text)
        self.keyboard.release(text)
        
    def on_press(self, key):
        """按键按下时的回调"""
        try:
            # 检查 F 键
            if hasattr(key, 'char') and key.char == 'f':
                self.f_pressed = True
                if self.ctrl_pressed and self.f_pressed:
                    print("\n检测到 Ctrl+F！")
                    # 模拟实际场景：在监听器回调中输入
                    self.type_status('0')
                    
            # 检查 Ctrl 键
            elif key == Key.ctrl_l or key == Key.ctrl_r:
                self.ctrl_pressed = True
                if self.ctrl_pressed and self.f_pressed:
                    print("\n检测到 Ctrl+F！")
                    # 模拟实际场景：在监听器回调中输入
                    self.type_status('0')
                    
            # ESC 退出
            elif key == Key.esc:
                print("\n按下 ESC，退出测试")
                return False
                
        except AttributeError:
            pass
    
    def on_release(self, key):
        """按键释放时的回调"""
        try:
            if hasattr(key, 'char') and key.char == 'f':
                self.f_pressed = False
            elif key == Key.ctrl_l or key == Key.ctrl_r:
                self.ctrl_pressed = False
        except AttributeError:
            pass
    
    def start_test(self):
        """开始测试"""
        print("=" * 60)
        print("Listener 上下文中的 pynput 光标测试")
        print("=" * 60)
        print("\n测试说明：")
        print("1. 将光标放在任何文本编辑器中")
        print("2. 按 Ctrl+F 触发输入")
        print("3. 观察 '0' 是否在光标当前位置输入，还是向右移动了一个位置")
        print("4. 按 ESC 退出测试")
        print("\n重要：这模拟了实际代码中的场景 - 在监听器回调中输入")
        print("=" * 60)
        print("\n开始监听键盘...")
        
        # 开始监听
        with Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

if __name__ == "__main__":
    test = TestKeyboardListener()
    test.start_test()