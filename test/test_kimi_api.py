#!/usr/bin/env python3
"""
测试Kimi API的功能
"""

import sys
import os

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.llm.kimi import KimiProcessor

def test_kimi_api():
    """测试Kimi API"""
    print("=== 测试Kimi API ===")
    
    # 检查环境变量
    if not os.getenv("KIMI_API_KEY"):
        print("❌ 错误: 未设置 KIMI_API_KEY 环境变量")
        print("请先设置: export KIMI_API_KEY=\"your_kimi_api_key_here\"")
        return False
    
    try:
        # 创建Kimi处理器
        kimi = KimiProcessor()
    except ValueError as e:
        print(f"❌ 初始化错误: {e}")
        return False
    
    # 测试文本（模拟语音识别结果）
    test_texts = [
        "你好这是一个测试文本没有标点符号需要润色一下",
        "今天天气很好我想出去走走不知道去哪里比较好",
        "我正在测试这个语音输入软件看看效果怎么样"
    ]
    
    for i, test_text in enumerate(test_texts, 1):
        print(f"\n--- 测试 {i} ---")
        print(f"原始文本: {test_text}")
        
        try:
            # 调用Kimi API进行润色
            polished_text = kimi.polish_text(test_text)
            print(f"润色结果: {polished_text}")
            
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    print("\n✅ Kimi API测试完成")
    return True

if __name__ == "__main__":
    success = test_kimi_api()
    sys.exit(0 if success else 1) 