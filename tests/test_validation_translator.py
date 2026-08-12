import tempfile
import unittest
from pathlib import Path

from mkdocs_translator.translator import DocumentTranslator
from mkdocs_translator.validation import ValidationError, contains_han_in_translatable_text, validate_translation


class StubTranslator(DocumentTranslator):
    def __init__(self, transform):
        super().__init__("en", api_key="dummy", client=object(), system_prompt="prompt")
        self.transform = transform
        self.last_input = None

    def translate_text(self, text, **kwargs):
        self.last_input = text
        return self.transform(text), {"usage": None, "translation_time": 0.1}


class ValidationAndTranslatorTests(unittest.TestCase):
    def test_residual_han_check_ignores_protected_regions(self):
        protected = "`中文`\n````text\n中文\n````\n[link](https://example.com/中文)\n<<<中文>>>"
        self.assertFalse(contains_han_in_translatable_text(protected))
        self.assertTrue(contains_han_in_translatable_text("English 中文"))

    def test_pages_allows_human_nav_key_translation_but_preserves_path(self):
        source = "nav:\n  - 快速开始: index.md\n"
        translated = "nav:\n  - Quick Start: index.md\n"
        validate_translation(source, translated, Path(".pages"), False, False)
        with self.assertRaises(ValidationError):
            validate_translation(source, "menu:\n  - Quick Start: changed.md\n", Path(".pages"), False, False)

    def test_validation_failure_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("[中文](original.md)", encoding="utf-8")
            target.write_text("Previous valid translation", encoding="utf-8")
            translator = StubTranslator(lambda text: text.replace("GXP_", "CHANGED_"))
            success, details = translator.translate_file(source, target)
            self.assertFalse(success)
            self.assertIn("Protected content integrity check failed", details["error_message"])
            self.assertEqual("Previous valid translation", target.read_text(encoding="utf-8"))

    def test_success_atomically_replaces_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("[中文](same.md)", encoding="utf-8")
            target.write_text("old", encoding="utf-8")
            translator = StubTranslator(lambda text: text.replace("中文", "English"))
            success, _ = translator.translate_file(source, target)
            self.assertTrue(success)
            self.assertEqual("[English](same.md)", target.read_text(encoding="utf-8"))
            self.assertNotIn("same.md", translator.last_input)

    def test_html_validation_ignores_tags_inside_code(self):
        source = "```xml\n<source>中文</source>\n```\n<div>中文</div>"
        translated = "```xml\n<translated>English</translated>\n```\n<div>English</div>"
        validate_translation(source, translated, Path("index.md"), False, False)

    def test_code_comment_is_visible_to_translation_but_fence_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("```yaml\n# 是否校验证书\nverify: false\n```\n", encoding="utf-8")
            translator = StubTranslator(lambda text: text.replace("是否校验证书", "Whether to verify the certificate"))

            success, _ = translator.translate_file(source, target)

            self.assertTrue(success)
            self.assertIn("是否校验证书", translator.last_input)
            self.assertNotIn("```yaml", translator.last_input)
            self.assertEqual(
                "```yaml\n# Whether to verify the certificate\nverify: false\n```\n",
                target.read_text(encoding="utf-8"),
            )

    def test_disabled_structure_check_sends_raw_source_and_accepts_structure_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("[中文](original.md)\n```yaml\n# 注释\nvalue: false\n```\n", encoding="utf-8")
            translator = StubTranslator(
                lambda _text: "[English](changed.md)\n```yaml\n# Comment\nvalue: true\n```\n"
            )
            translator.check_structure = False

            success, _ = translator.translate_file(source, target)

            self.assertTrue(success)
            self.assertIn("original.md", translator.last_input)
            self.assertNotIn("GXP_", translator.last_input)
            self.assertIn("value: true", target.read_text(encoding="utf-8"))

    def test_disabled_structure_check_still_rejects_empty_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("中文", encoding="utf-8")
            translator = StubTranslator(lambda _text: "")
            translator.check_structure = False

            success, details = translator.translate_file(source, target)

            self.assertFalse(success)
            self.assertEqual("Translation result is empty", details["error_message"])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
