#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试翻译逻辑，包括对failed状态文件的处理
"""

import sys
import os
import json
import tempfile
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(__file__), 'mkdocs_translator'))

from metadata import MetadataManager

def create_test_file(content: str, file_path: Path):
    """创建测试文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def test_translation_logic():
    """测试翻译逻辑"""
    print("测试翻译逻辑:")
    print("=" * 60)
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / "source"
        source_path.mkdir()
        
        # 创建测试文件
        test_file = source_path / "test.md"
        test_content = "Hello World"
        create_test_file(test_content, test_file)
        
        # 创建metadata文件路径
        metadata_path = source_path / "metadata.json"
        last_metadata_path = source_path / "last-metadata.json"
        
        # 初始化MetadataManager
        metadata_manager = MetadataManager(metadata_path, source_path)
        last_metadata_manager = MetadataManager(last_metadata_path, source_path)
        
        print(f"1. 测试新文件（应该需要翻译）:")
        needs_translation = metadata_manager.needs_translation(test_file.relative_to(source_path))
        print(f"   文件: {test_file.name}")
        print(f"   需要翻译: {needs_translation}")
        print(f"   期望结果: True")
        print(f"   测试结果: {'✓' if needs_translation == True else '✗'}")
        print()
        
        # 模拟成功翻译
        print(f"2. 模拟成功翻译:")
        success_metadata = {'translation_time': 1.5}
        metadata_manager.update_file_status(test_file.relative_to(source_path), True, success_metadata)
        last_metadata_manager.update_file_status(test_file.relative_to(source_path), True, success_metadata)
        
        # 检查是否需要重新翻译（hash相同，status为success）
        needs_translation = metadata_manager.needs_translation(test_file.relative_to(source_path))
        print(f"   文件: {test_file.name}")
        print(f"   需要翻译: {needs_translation}")
        print(f"   期望结果: False")
        print(f"   测试结果: {'✓' if needs_translation == False else '✗'}")
        print()
        
        # 模拟翻译失败
        print(f"3. 模拟翻译失败:")
        error_metadata = {'error_message': '翻译结果包含中文字符'}
        metadata_manager.update_file_status(test_file.relative_to(source_path), False, error_metadata)
        last_metadata_manager.update_file_status(test_file.relative_to(source_path), False, error_metadata)
        
        # 检查是否需要重新翻译（hash相同，status为failed）
        needs_translation = metadata_manager.needs_translation(test_file.relative_to(source_path))
        print(f"   文件: {test_file.name}")
        print(f"   需要翻译: {needs_translation}")
        print(f"   期望结果: True")
        print(f"   测试结果: {'✓' if needs_translation == True else '✗'}")
        print()
        
        # 修改文件内容（hash变化）
        print(f"4. 修改文件内容（hash变化）:")
        new_content = "Hello World Updated"
        create_test_file(new_content, test_file)
        
        # 检查是否需要重新翻译（hash不同）
        needs_translation = metadata_manager.needs_translation(test_file.relative_to(source_path))
        print(f"   文件: {test_file.name}")
        print(f"   需要翻译: {needs_translation}")
        print(f"   期望结果: True")
        print(f"   测试结果: {'✓' if needs_translation == True else '✗'}")
        print()
        
        # 显示metadata内容
        print(f"5. 查看metadata内容:")
        print(f"   metadata.json:")
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata_content = json.load(f)
                print(f"   {json.dumps(metadata_content, indent=2, ensure_ascii=False)}")
        else:
            print("   文件不存在")
        
        print(f"   last-metadata.json:")
        if last_metadata_path.exists():
            with open(last_metadata_path, 'r', encoding='utf-8') as f:
                last_metadata_content = json.load(f)
                print(f"   {json.dumps(last_metadata_content, indent=2, ensure_ascii=False)}")
        else:
            print("   文件不存在")
    
    print("=" * 60)
    print("测试完成!")

if __name__ == "__main__":
    test_translation_logic()
