#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from mkdocs_translator.cache_manager import CacheData, CacheManager, TranslationUnit
from mkdocs_translator.parser import (
    Paragraph,
    assemble_translation,
    build_cached_blocks,
    compute_hash,
    parse_content,
    plan_translation_units,
    split_markdown_blocks,
)


class TestMarkdownParsing(unittest.TestCase):
    def test_markdown_structures_are_split(self):
        content = """# 标题

这是第一段。

- 列表项1
- 列表项2

| 列1 | 列2 |
| --- | --- |
| A | B |

```python
print("hello")
```
"""
        paragraphs = parse_content(content)
        self.assertEqual(
            [p.paragraph_type for p in paragraphs],
            ['heading', 'normal', 'list', 'table', 'code']
        )

    def test_setext_heading(self):
        paragraphs = parse_content("""标题
====

正文
""")
        self.assertEqual(paragraphs[0].paragraph_type, 'heading')
        self.assertEqual(paragraphs[1].paragraph_type, 'normal')

    def test_frontmatter_is_standalone(self):
        blocks = split_markdown_blocks("""---
title: test
---

# 标题

正文
""")
        self.assertEqual([block_type for block_type, _ in blocks], ['frontmatter', 'heading', 'normal'])


class TestSectionPlanning(unittest.TestCase):
    def _paragraph(self, content: str, paragraph_type: str = 'normal') -> Paragraph:
        short_hash, full_hash = compute_hash(content)
        return Paragraph(
            content_hash=short_hash,
            full_hash=full_hash,
            content=content,
            paragraph_type=paragraph_type
        )

    def test_heading_and_body_are_grouped(self):
        paragraphs = parse_content("""## Billing

Guance offers a flexible billing model.

For more details, refer to the billing guide.
""")
        units = plan_translation_units(paragraphs, [], preferred_chars=500, max_chars=1000)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].unit_type, 'section_opening')
        self.assertIn("## Billing", units[0].source_text)
        self.assertIn("Guance offers", units[0].source_text)

    def test_intro_and_list_are_grouped(self):
        paragraphs = parse_content("""## Limits

This feature supports:

- Option A
- Option B
""")
        units = plan_translation_units(paragraphs, [], preferred_chars=500, max_chars=1000)
        self.assertEqual(len(units), 1)
        self.assertIn("This feature supports:", units[0].source_text)
        self.assertIn("- Option A", units[0].source_text)

    def test_code_block_stays_standalone(self):
        paragraphs = parse_content("""## Example

Intro text.

```python
print("hello")
```

Closing text.
""")
        units = plan_translation_units(paragraphs, [], preferred_chars=200, max_chars=500)
        self.assertEqual(len(units), 3)
        self.assertEqual(units[1].unit_type, 'code_block')
        self.assertEqual(units[1].source_text, '```python\nprint("hello")\n```')

    def test_cache_reuse_uses_source_hash_and_context(self):
        paragraphs = parse_content("""## Billing

Guance offers a flexible billing model.
""")
        first_plan = plan_translation_units(paragraphs, [], preferred_chars=500, max_chars=1000)
        cached_units = [
            TranslationUnit(
                unit_id=first_plan[0].unit_id,
                unit_type=first_plan[0].unit_type,
                block_hashes=first_plan[0].block_hashes,
                source_hash=first_plan[0].source_hash,
                context_signature=first_plan[0].context_signature,
                section_path=first_plan[0].section_path,
                translation="Cached translation"
            )
        ]

        second_plan = plan_translation_units(paragraphs, cached_units, preferred_chars=500, max_chars=1000)
        self.assertFalse(second_plan[0].need_translate)
        self.assertEqual(second_plan[0].translation, "Cached translation")

    def test_context_is_attached(self):
        paragraphs = parse_content("""# Billing

Intro.

## USD Settlement

Please contact your account manager.
""")
        units = plan_translation_units(paragraphs, [], preferred_chars=200, max_chars=500)
        self.assertEqual(len(units), 2)
        self.assertTrue(units[0].context_after)
        self.assertTrue(units[1].context_before)

    def test_build_cached_blocks_contains_section_path(self):
        paragraphs = parse_content("""# Billing

## Site-Related

Please contact your account manager.
""")
        blocks = build_cached_blocks(paragraphs)
        self.assertEqual(blocks[0].section_path, ['Billing'])
        self.assertEqual(blocks[-1].section_path, ['Billing', 'Site-Related'])


class TestAssembleTranslation(unittest.TestCase):
    def test_assemble_translation(self):
        paragraphs = parse_content("""# Billing

Text
""")
        units = plan_translation_units(paragraphs, [], preferred_chars=500, max_chars=1000)
        for unit in units:
            unit.translation = f"T::{unit.unit_type}"
        result = assemble_translation(units)
        self.assertIn("T::section_opening", result)


class TestCacheRoundTrip(unittest.TestCase):
    def test_blocks_round_trip_without_embedded_full_hash(self):
        paragraphs = parse_content("""# Billing

Text
""")
        blocks = build_cached_blocks(paragraphs)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheManager(Path(temp_dir))
            cache = CacheData()
            manager.replace_blocks(cache, blocks)
            manager.save_cache(Path("sample.md"), cache)

            loaded = manager.load_cache(Path("sample.md"))
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded.blocks), len(blocks))
            for block in loaded.blocks.values():
                self.assertFalse(hasattr(block, "full_hash"))


if __name__ == "__main__":
    unittest.main()
