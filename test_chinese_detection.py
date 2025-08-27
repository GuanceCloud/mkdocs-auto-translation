#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试中文字符检测功能
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'mkdocs_translator'))

from translator import DocumentTranslator

def test_chinese_detection():
    """测试中文字符检测功能"""
    translator = DocumentTranslator(
        target_lang="en",
        user="test_user",
        query="test_query",
        api_key="dummy_key"
    )
    
    # 测试用例
    test_cases = [
        ("Hello world", False, "纯英文"),
        ("你好世界", True, "纯中文"),
        ("Hello 世界", True, "中英混合"),
        ("Hello, world!", False, "英文加标点"),
        ("你好，世界！", True, "中文加标点"),
        ("", False, "空字符串"),
        ("12345", False, "纯数字"),
        ("一二三", True, "中文数字"),
        ("Hello 123", False, "英文数字"),
        ("你好 123", True, "中文数字"),
        ("Hello\nWorld", False, "英文换行"),
        ("你好\n世界", True, "中文换行"),
    ]
    
    print("测试中文字符检测功能:")
    print("=" * 50)
    
    for text, expected, description in test_cases:
        result = translator._contains_chinese(text)
        status = "✓" if result == expected else "✗"
        print(f"{status} {description}: '{text}' -> {result} (期望: {expected})")
    
    print("=" * 50)
    print("测试完成!")

if __name__ == "__main__":
    test_chinese_detection()
