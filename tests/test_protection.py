import re
import unittest

from mkdocs_translator.protection import (
    ProtectionError,
    protect_document,
    strip_single_outer_fence,
)


class ProtectionTests(unittest.TestCase):
    def test_masks_and_losslessly_restores_fragile_markdown(self):
        source = """# 安装

[安装文档](../install.md \"安装\")和 ![图片](img/a.png)

`https://inline.example/<token>`

```shell
echo <your-token>
```

<div class=\"note\">说明</div>
<style>.note { color: red; }</style>
<<< custom_key.brand_name >>>
裸链接：https://example.com/docs?q=1。
[reference]: ../reference.md
"""
        protected = protect_document(source)

        self.assertIn("# 安装", protected.masked_text)
        for fragile in (
            "../install.md",
            "img/a.png",
            "https://inline.example",
            '<div class="note">',
            "</div>",
            ".note { color: red; }",
            "<<< custom_key.brand_name >>>",
            "https://example.com/docs?q=1",
            "../reference.md",
        ):
            self.assertNotIn(fragile, protected.masked_text)
        self.assertEqual(source, protected.restore(protected.masked_text))
        self.assertEqual(len(protected.tokens), len(set(protected.tokens)))

    def test_fenced_code_content_is_visible_but_delimiters_and_fragile_values_are_masked(self):
        source = """```yaml
# 是否校验证书
verify: false
endpoint: https://example.com/api
token: <your-token>
```
"""
        protected = protect_document(source)
        self.assertIn("# 是否校验证书", protected.masked_text)
        self.assertIn("verify: false", protected.masked_text)
        self.assertNotIn("```yaml", protected.masked_text)
        self.assertNotIn("https://example.com/api", protected.masked_text)
        self.assertNotIn("<your-token>", protected.masked_text)

        translated = protected.masked_text.replace("是否校验证书", "Whether to verify the certificate")
        self.assertEqual(
            "```yaml\n# Whether to verify the certificate\nverify: false\n"
            "endpoint: https://example.com/api\ntoken: <your-token>\n```\n",
            protected.restore(translated),
        )

    def test_restore_rejects_missing_duplicate_and_reordered_tokens(self):
        protected = protect_document("[一](one.md) [二](two.md)")
        first, second = protected.tokens

        with self.assertRaisesRegex(ProtectionError, "missing"):
            protected.restore(protected.masked_text.replace(first, ""))
        with self.assertRaisesRegex(ProtectionError, "duplicated"):
            protected.restore(protected.masked_text.replace(first, first + first))
        with self.assertRaisesRegex(ProtectionError, "order changed"):
            protected.restore(protected.masked_text.replace(first, "TEMP").replace(second, first).replace("TEMP", second))

    def test_repeated_values_get_distinct_tokens(self):
        protected = protect_document("[一](same.md) [二](same.md)")
        self.assertEqual(2, len(protected.tokens))
        self.assertNotEqual(protected.tokens[0], protected.tokens[1])
        translated = protected.masked_text.replace("一", "One").replace("二", "Two")
        self.assertEqual("[One](same.md) [Two](same.md)", protected.restore(translated))

    def test_link_parser_preserves_balanced_parentheses(self):
        source = "[Java](https://en.wikipedia.org/wiki/Java_(programming_language))"
        protected = protect_document(source)
        self.assertNotIn("programming_language", protected.masked_text)
        self.assertEqual(source, protected.restore(protected.masked_text))

    def test_strips_only_a_single_full_response_fence(self):
        wrapped = "```markdown\n# Translated\n```\n"
        self.assertEqual("# Translated\n", strip_single_outer_fence(wrapped))
        self.assertEqual("before\n```markdown\ntext\n```\n", strip_single_outer_fence("before\n```markdown\ntext\n```\n"))
        self.assertEqual("```markdown\ntext\n```\nafter\n", strip_single_outer_fence("```markdown\ntext\n```\nafter\n"))

    def test_tokens_are_document_specific(self):
        first = protect_document("[一](one.md)")
        second = protect_document("[一](one.md)")
        self.assertNotEqual(first.tokens, second.tokens)
        self.assertRegex(first.tokens[0], re.compile(r"^GXP_[A-F0-9]{12}_00001_X$"))

    def test_pages_masks_control_fields_and_paths_but_keeps_chinese_labels(self):
        source = "nav:\n  - '快速开始': index.md\n  - '会话重放': session-replay\n"
        protected = protect_document(source, is_pages=True)
        self.assertIn("快速开始", protected.masked_text)
        self.assertIn("会话重放", protected.masked_text)
        self.assertNotIn("nav", protected.masked_text)
        self.assertNotIn("index.md", protected.masked_text)
        self.assertNotIn("session-replay", protected.masked_text)
        self.assertEqual(source, protected.restore(protected.masked_text))


if __name__ == "__main__":
    unittest.main()
