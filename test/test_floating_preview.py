#!/usr/bin/env python3
"""
测试 FloatingPreviewWindow 的光标位置检测功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    kAXFocusedUIElementAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    AXValueGetValue,
    kAXValueTypeCGPoint,
    kAXValueTypeCGSize,
)
from Cocoa import NSScreen


def test_get_caret_position():
    """测试获取当前光标位置"""
    print("=" * 50)
    print("测试: 获取当前输入框位置")
    print("=" * 50)
    print()

    # Step 1: 获取当前激活的应用
    print("[Step 1] 获取当前激活的应用...")
    workspace = NSWorkspace.sharedWorkspace()
    front_app = workspace.frontmostApplication()

    if front_app is None:
        print("❌ 无法获取当前激活的应用")
        return False

    pid = front_app.processIdentifier()
    app_name = front_app.localizedName()
    print(f"✅ 当前应用: {app_name} (pid={pid})")
    print()

    # Step 2: 创建 AXUIElement
    print("[Step 2] 创建 AXUIElement...")
    app_element = AXUIElementCreateApplication(pid)

    if app_element is None:
        print(f"❌ 无法为 {app_name} 创建 AXUIElement")
        return False

    print(f"✅ AXUIElement: {app_element}")
    print()

    # Step 3: 获取焦点元素
    print("[Step 3] 获取焦点元素...")
    err, focused_element = AXUIElementCopyAttributeValue(
        app_element, kAXFocusedUIElementAttribute, None
    )

    if err != 0:
        print(f"❌ 无法获取焦点元素, error code = {err}")
        print("   可能原因: 应用没有辅助功能权限，或当前没有焦点元素")
        return False

    if focused_element is None:
        print("❌ 焦点元素为 None")
        return False

    print(f"✅ 焦点元素: {focused_element}")
    print()

    # Step 4: 获取位置属性
    print("[Step 4] 获取位置属性 (kAXPositionAttribute)...")
    err, position_value = AXUIElementCopyAttributeValue(
        focused_element, kAXPositionAttribute, None
    )

    if err != 0:
        print(f"❌ 无法获取位置属性, error code = {err}")
        return False

    if position_value is None:
        print("❌ 位置属性为 None")
        return False

    print(f"✅ 位置属性值: {position_value}")
    print(f"   类型: {type(position_value)}")
    print()

    # Step 5: 获取尺寸属性
    print("[Step 5] 获取尺寸属性 (kAXSizeAttribute)...")
    err, size_value = AXUIElementCopyAttributeValue(
        focused_element, kAXSizeAttribute, None
    )

    if err != 0:
        print(f"❌ 无法获取尺寸属性, error code = {err}")
        return False

    if size_value is None:
        print("❌ 尺寸属性为 None")
        return False

    print(f"✅ 尺寸属性值: {size_value}")
    print(f"   类型: {type(size_value)}")
    print()

    # Step 6: 解析 AXValue
    print("[Step 6] 解析 AXValue...")
    print(f"   position_value 的方法: {dir(position_value)}")
    print()

    # 尝试不同的方式解析
    print("尝试方式 1: AXValueGetValue(value, type, None)...")
    try:
        result = AXValueGetValue(position_value, kAXValueTypeCGPoint, None)
        print(f"   结果: {result}")
        print(f"   类型: {type(result)}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    print()

    # 方式 2: 直接访问属性（某些 PyObjC 版本）
    print("尝试方式 2: 检查是否有 pointValue 方法...")
    if hasattr(position_value, 'pointValue'):
        try:
            point = position_value.pointValue()
            print(f"   ✅ pointValue(): {point}")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
    else:
        print("   没有 pointValue 方法")
    print()

    # 方式 3: 使用 Quartz
    print("尝试方式 3: 使用 Quartz.CGPoint...")
    try:
        import Quartz
        # AXValueRef 可以转换为 CGPoint
        if hasattr(Quartz, 'AXValueGetValue'):
            result = Quartz.AXValueGetValue(position_value, kAXValueTypeCGPoint, None)
            print(f"   结果: {result}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    print()

    # 方式 4: 检查 position_value 本身
    print("尝试方式 4: 直接打印 position_value 的内容...")
    print(f"   repr: {repr(position_value)}")
    print(f"   str: {str(position_value)}")

    # 有些情况下 AXValueRef 直接就是一个 tuple
    if isinstance(position_value, tuple):
        print(f"   ✅ 是 tuple: {position_value}")
    print()

    # 获取屏幕信息
    print("[额外] 屏幕信息:")
    screen = NSScreen.mainScreen()
    screen_frame = screen.frame()
    print(f"   屏幕尺寸: {screen_frame.size.width} x {screen_frame.size.height}")
    print()

    return True


if __name__ == "__main__":
    print("请先点击一个输入框（比如终端、编辑器、浏览器的搜索框等）")
    print("然后在 3 秒内切换回来...")
    print()

    import time
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    print()

    success = test_get_caret_position()

    print()
    print("=" * 50)
    print(f"测试结果: {'✅ 通过' if success else '❌ 失败'}")
    print("=" * 50)
