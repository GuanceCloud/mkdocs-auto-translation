#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修改后的中文字符检测功能 - 只检查中文字，不检查中文符号
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'mkdocs_translator'))

from translator import DocumentTranslator

def test_chinese_detection_updated():
    """测试修改后的中文字符检测功能"""
    translator = DocumentTranslator(
        target_lang="en",
        user="test_user",
        query="test_query",
        api_key="dummy_key"
    )
    
    # 测试用例
    test_cases = [
        # 纯英文和数字
        ("Hello world", False, "纯英文"),
        ("12345", False, "纯数字"),
        ("Hello 123", False, "英文数字"),
        ("", False, "空字符串"),
        
        # 纯中文
        ("你好世界", True, "纯中文"),
        ("一二三", True, "中文数字"),
        ("测试", True, "中文测试"),
        
        # 中英混合
        ("Hello 世界", True, "中英混合"),
        ("你好 123", True, "中文数字混合"),
        ("Hello\n世界", True, "中文换行混合"),
        
        # 中文标点符号（现在应该返回False）
        ("，。！？", False, "中文标点符号"),
        ("Hello，world！", False, "英文加中文标点"),
        ("你好，世界！", True, "中文加中文标点"),
        ("《》""", False, "中文书名号"),
        ("【】", False, "中文方括号"),
        ("（）", False, "中文圆括号"),
        
        # 全角字符（现在应该返回False）
        ("Ｈｅｌｌｏ", False, "全角英文"),
        ("１２３", False, "全角数字"),
        ("！＠＃", False, "全角符号"),
        
        # 边界情况
        ("a", False, "单个英文字母"),
        ("中", True, "单个中文字"),
        ("，", False, "单个中文标点"),
        ("！", False, "单个中文感叹号"),
    ]
    
    print("测试修改后的中文字符检测功能:")
    print("=" * 60)
    print("注意：现在只检查中文字符，不检查中文标点符号")
    print("=" * 60)
    
    correct_count = 0
    total_count = len(test_cases)
    
    for text, expected, description in test_cases:
        result = translator._contains_chinese(text)
        status = "✓" if result == expected else "✗"
        if result == expected:
            correct_count += 1
        
        print(f"{status} {description}: '{text}' -> {result} (期望: {expected})")
    
    print("=" * 60)
    print(f"测试结果: {correct_count}/{total_count} 通过")
    print(f"准确率: {correct_count/total_count*100:.1f}%")
    
    if correct_count == total_count:
        print("🎉 所有测试通过！")
    else:
        print("❌ 部分测试失败，请检查实现")
    
    print("=" * 60)
    print("测试完成!")

if __name__ == "__main__":
    test_chinese_detection_updated()
