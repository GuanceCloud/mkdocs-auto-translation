#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修改后的日志功能 - 只输出到文件，不在终端显示
"""

import sys
import os
import tempfile
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(__file__), 'mkdocs_translator'))

from translator import DocumentTranslator

def test_logging_no_console():
    """测试日志功能 - 只输出到文件"""
    print("测试修改后的日志功能（只输出到文件）:")
    print("=" * 60)
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # 测试DocumentTranslator初始化
        print("1. 测试DocumentTranslator初始化:")
        try:
            translator = DocumentTranslator(
                target_lang="en",
                user="test_user",
                query="test_query",
                api_key="dummy_key"
            )
            print("   ✓ DocumentTranslator初始化成功")
            print(f"   ✓ 翻译日志器已设置: {translator.translation_logger is not None}")
            
            # 检查handler数量
            handler_count = len(translator.translation_logger.handlers)
            print(f"   ✓ 日志handler数量: {handler_count}")
            
            # 检查handler类型
            for i, handler in enumerate(translator.translation_logger.handlers):
                handler_type = type(handler).__name__
                print(f"   ✓ Handler {i+1} 类型: {handler_type}")
                
        except Exception as e:
            print(f"   ✗ DocumentTranslator初始化失败: {e}")
            return
        
        # 测试中文字符检测
        print("\n2. 测试中文字符检测:")
        test_texts = [
            ("Hello World", False, "纯英文"),
            ("你好世界", True, "纯中文"),
            ("Hello 世界", True, "中英混合"),
        ]
        
        for text, expected, description in test_texts:
            result = translator._contains_chinese(text)
            status = "✓" if result == expected else "✗"
            print(f"   {status} {description}: '{text}' -> {result} (期望: {expected})")
        
        # 测试日志记录（应该只在文件中，不在终端显示）
        print("\n3. 测试日志记录（应该只在文件中）:")
        try:
            print("   正在记录测试日志...")
            translator.translation_logger.info("这是一条测试信息 - 应该只在日志文件中看到")
            translator.translation_logger.warning("这是一条测试警告 - 应该只在日志文件中看到")
            translator.translation_logger.error("这是一条测试错误 - 应该只在日志文件中看到")
            print("   ✓ 测试日志记录完成")
        except Exception as e:
            print(f"   ✗ 测试日志记录失败: {e}")
        
        # 检查日志文件是否创建
        print("\n4. 检查日志文件:")
        log_file = Path.cwd() / 'translation.log'
        if log_file.exists():
            print(f"   ✓ 日志文件已创建: {log_file}")
            print(f"   ✓ 日志文件大小: {log_file.stat().st_size} 字节")
            
            # 显示日志文件内容
            print("\n5. 日志文件内容预览:")
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        print(f"   最新日志条目:")
                        for line in lines[-5:]:  # 显示最后5行
                            print(f"   {line.strip()}")
                    else:
                        print("   日志文件为空")
            except Exception as e:
                print(f"   读取日志文件失败: {e}")
        else:
            print(f"   ✗ 日志文件未创建: {log_file}")
        
        # 验证终端输出没有被日志干扰
        print("\n6. 验证终端输出:")
        print("   这条消息应该正常显示在终端")
        print("   如果日志配置正确，上面应该没有额外的日志输出")
        print("   只有这些print语句应该显示在终端")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print(f"请查看当前目录下的 translation.log 文件")
    print("注意：日志应该只在文件中，终端应该保持干净")

if __name__ == "__main__":
    test_logging_no_console()
