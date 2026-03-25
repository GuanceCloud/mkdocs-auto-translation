#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
段落切分与合并逻辑单元测试
"""

import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from mkdocs_translator.parser import (
    parse_content,
    split_text_paragraphs,
    compute_hash,
    plan_merge_units,
    assemble_translation,
    Paragraph,
    PlannedMergeUnit
)
from mkdocs_translator.cache_manager import MergeUnit


class TestSplitTextParagraphs(unittest.TestCase):
    """测试段落切分"""
    
    def test_simple_paragraphs(self):
        """测试简单段落切分"""
        text = "第一段内容\n\n第二段内容\n\n第三段内容"
        result = split_text_paragraphs(text)
        self.assertEqual(len(result), 3)
        self.assertIn("第一段", result[0])
        self.assertIn("第二段", result[1])
        self.assertIn("第三段", result[2])
    
    def test_single_paragraph(self):
        """测试单个段落"""
        text = "只有一段内容"
        result = split_text_paragraphs(text)
        self.assertEqual(len(result), 1)
    
    def test_empty_text(self):
        """测试空文本"""
        text = ""
        result = split_text_paragraphs(text)
        self.assertEqual(len(result), 0)
    
    def test_multiple_newlines(self):
        """测试多个换行符"""
        text = "段落1\n\n\n\n段落2"
        result = split_text_paragraphs(text)
        self.assertEqual(len(result), 2)
    
    def test_windows_line_endings(self):
        """测试 Windows 换行符"""
        text = "段落1\r\n\r\n段落2"
        result = split_text_paragraphs(text)
        self.assertEqual(len(result), 2)


class TestParseContent(unittest.TestCase):
    """测试内容解析"""
    
    def test_plain_text(self):
        """测试纯文本"""
        content = "第一段\n\n第二段\n\n第三段"
        paragraphs = parse_content(content)
        self.assertEqual(len(paragraphs), 3)
        for p in paragraphs:
            self.assertEqual(p.paragraph_type, 'normal')
    
    def test_code_block(self):
        """测试代码块"""
        content = "```python\nprint('hello')\n```\n\n文本段落"
        paragraphs = parse_content(content)
        self.assertEqual(len(paragraphs), 2)
        self.assertEqual(paragraphs[0].paragraph_type, 'code')
        self.assertEqual(paragraphs[1].paragraph_type, 'normal')
    
    def test_admonition(self):
        """测试提示框"""
        content = "!!! note\n    这是提示\n\n文本段落"
        paragraphs = parse_content(content)
        self.assertGreaterEqual(len(paragraphs), 1)
    
    def test_mixed_content(self):
        """测试混合内容"""
        content = """# 标题

这是第一段。

```python
code here
```

这是第二段。
"""
        paragraphs = parse_content(content)
        self.assertGreater(len(paragraphs), 0)
        
        types = [p.paragraph_type for p in paragraphs]
        self.assertIn('normal', types)
        self.assertIn('code', types)


class TestComputeHash(unittest.TestCase):
    """测试哈希计算"""
    
    def test_same_content_same_hash(self):
        """相同内容产生相同哈希"""
        content = "测试内容"
        hash1, full1 = compute_hash(content)
        hash2, full2 = compute_hash(content)
        self.assertEqual(hash1, hash2)
        self.assertEqual(full1, full2)
    
    def test_different_content_different_hash(self):
        """不同内容产生不同哈希"""
        hash1, _ = compute_hash("内容1")
        hash2, _ = compute_hash("内容2")
        self.assertNotEqual(hash1, hash2)
    
    def test_hash_length(self):
        """测试哈希长度"""
        short_hash, full_hash = compute_hash("测试")
        self.assertEqual(len(short_hash), 6)
        self.assertEqual(len(full_hash), 64)


class TestPlanMergeUnits(unittest.TestCase):
    """测试合并策略"""
    
    def _create_paragraphs(self, contents):
        """创建测试段落列表"""
        paragraphs = []
        for content in contents:
            short_hash, full_hash = compute_hash(content)
            paragraphs.append(Paragraph(
                content_hash=short_hash,
                full_hash=full_hash,
                content=content,
                paragraph_type='normal'
            ))
        return paragraphs
    
    def test_empty_paragraphs(self):
        """测试空段落列表"""
        result = plan_merge_units([], [])
        self.assertEqual(len(result), 0)
    
    def test_no_old_merge_units(self):
        """测试无旧缓存时的合并"""
        paragraphs = self._create_paragraphs([
            "短段落1",
            "短段落2",
            "短段落3"
        ])
        
        result = plan_merge_units(paragraphs, [])
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].need_translate, True)
        self.assertEqual(len(result[0].hashes), 3)
    
    def test_full_cache_reuse(self):
        """测试完全复用缓存"""
        paragraphs = self._create_paragraphs([
            "段落1内容",
            "段落2内容"
        ])
        
        old_merge_units = [
            MergeUnit(
                hashes=[paragraphs[0].content_hash, paragraphs[1].content_hash],
                translation="Cached translation"
            )
        ]
        
        result = plan_merge_units(paragraphs, old_merge_units)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].need_translate, False)
        self.assertEqual(result[0].translation, "Cached translation")
    
    def test_partial_cache_reuse(self):
        """测试部分复用缓存"""
        paragraphs = self._create_paragraphs([
            "段落1",
            "段落2",
            "段落3",
            "段落4"
        ])
        
        old_merge_units = [
            MergeUnit(
                hashes=[paragraphs[0].content_hash, paragraphs[1].content_hash],
                translation="Translation 1-2"
            ),
            MergeUnit(
                hashes=[paragraphs[2].content_hash, paragraphs[3].content_hash],
                translation="Translation 3-4"
            )
        ]
        
        # 修改第二个段落
        paragraphs[1] = Paragraph(
            content_hash="changed",
            full_hash="changed_full",
            content="修改后的段落2",
            paragraph_type='normal'
        )
        
        result = plan_merge_units(paragraphs, old_merge_units)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].need_translate, True)
        self.assertEqual(result[1].need_translate, False)
    
    def test_deleted_paragraph(self):
        """测试删除段落场景"""
        paragraphs = self._create_paragraphs([
            "段落0",
            "段落2",
            "段落3",
            "段落4"
        ])
        
        old_merge_units = [
            MergeUnit(
                hashes=["p0_hash", "p1_hash"],
                translation="Translation 0-1"
            ),
            MergeUnit(
                hashes=[paragraphs[1].content_hash, paragraphs[2].content_hash, paragraphs[3].content_hash],
                translation="Translation 2-4"
            )
        ]
        
        paragraphs[0] = Paragraph(
            content_hash="p0_hash",
            full_hash="p0_full",
            content="段落0",
            paragraph_type='normal'
        )
        
        result = plan_merge_units(paragraphs, old_merge_units)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].need_translate, True)
        self.assertEqual(result[1].need_translate, False)
    
    def test_new_paragraph_inserted(self):
        """测试插入新段落场景"""
        paragraphs = self._create_paragraphs([
            "段落0",
            "新段落",
            "段落2",
            "段落3"
        ])
        
        old_merge_units = [
            MergeUnit(
                hashes=[paragraphs[0].content_hash, "old_p1"],
                translation="Translation 0-1"
            ),
            MergeUnit(
                hashes=[paragraphs[2].content_hash, paragraphs[3].content_hash],
                translation="Translation 2-3"
            )
        ]
        
        result = plan_merge_units(paragraphs, old_merge_units)
        
        self.assertGreater(len(result), 0)
    
    def test_large_paragraph_no_merge(self):
        """测试大段落不与小段落合并"""
        large_content = "A" * 300
        paragraphs = self._create_paragraphs([large_content, "小段落"])
        
        result = plan_merge_units(paragraphs, [], min_length=200)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0].hashes), 1)
        self.assertEqual(len(result[1].hashes), 1)


class TestAssembleTranslation(unittest.TestCase):
    """测试译文组装"""
    
    def test_assemble_single_unit(self):
        """测试单个合并单元"""
        units = [
            PlannedMergeUnit(
                hashes=["hash1"],
                merged_content="内容",
                translation="Translation",
                need_translate=False
            )
        ]
        
        result = assemble_translation(units)
        self.assertEqual(result, "Translation")
    
    def test_assemble_multiple_units(self):
        """测试多个合并单元"""
        units = [
            PlannedMergeUnit(
                hashes=["hash1"],
                merged_content="内容1",
                translation="Translation 1",
                need_translate=False
            ),
            PlannedMergeUnit(
                hashes=["hash2"],
                merged_content="内容2",
                translation="Translation 2",
                need_translate=False
            )
        ]
        
        result = assemble_translation(units)
        self.assertEqual(result, "Translation 1\n\nTranslation 2")
    
    def test_assemble_empty_units(self):
        """测试空单元列表"""
        result = assemble_translation([])
        self.assertEqual(result, "")


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def test_full_workflow(self):
        """测试完整工作流"""
        content = """# 标题

这是第一段内容，包含一些文字。

这是第二段内容，也有一定的长度。

```python
print('code')
```

这是代码后的段落。
"""
        paragraphs = parse_content(content)
        self.assertGreater(len(paragraphs), 0)
        
        result = plan_merge_units(paragraphs, [])
        self.assertGreater(len(result), 0)
        
        for unit in result:
            unit.translation = "Mock translation for: " + unit.merged_content[:20]
        
        final = assemble_translation(result)
        self.assertIn("Mock translation", final)


class TestEdgeCases(unittest.TestCase):
    """边界情况测试"""
    
    def test_single_character_paragraph(self):
        """测试单字符段落"""
        paragraphs = [Paragraph(
            content_hash=compute_hash("A")[0],
            full_hash=compute_hash("A")[1],
            content="A",
            paragraph_type='normal'
        )]
        
        result = plan_merge_units(paragraphs, [])
        self.assertEqual(len(result), 1)
    
    def test_very_long_paragraph(self):
        """测试超长段落"""
        long_content = "内容" * 1000
        paragraphs = [Paragraph(
            content_hash=compute_hash(long_content)[0],
            full_hash=compute_hash(long_content)[1],
            content=long_content,
            paragraph_type='normal'
        )]
        
        result = plan_merge_units(paragraphs, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0].hashes), 1)
    
    def test_merge_units_with_overlapping_hashes(self):
        """测试有重叠哈希的合并单元
        
        当旧 merge_units 有重叠时（如 [h1,h2] 和 [h2,h3]），
        第一个 merge_unit 会被复用，然后 h3 会尝试复用第二个。
        由于 h2 已经被第一个 merge_unit 处理，第二个无法完整复用。
        """
        paragraphs = [
            Paragraph(content_hash="h1", full_hash="f1", content="P1", paragraph_type='normal'),
            Paragraph(content_hash="h2", full_hash="f2", content="P2", paragraph_type='normal'),
            Paragraph(content_hash="h3", full_hash="f3", content="P3", paragraph_type='normal'),
        ]
        
        old_merge_units = [
            MergeUnit(hashes=["h1", "h2"], translation="T1-2"),
            MergeUnit(hashes=["h2", "h3"], translation="T2-3"),
        ]
        
        result = plan_merge_units(paragraphs, old_merge_units)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].need_translate, False)
        self.assertEqual(result[0].translation, "T1-2")
        self.assertEqual(result[1].need_translate, False)
        self.assertEqual(result[1].translation, "T2-3")


if __name__ == '__main__':
    unittest.main(verbosity=2)