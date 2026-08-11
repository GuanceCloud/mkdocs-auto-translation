import tempfile
import unittest
from pathlib import Path

from mkdocs_translator.translator import DocumentTranslator
from mkdocs_translator.validation import ValidationError, contains_han_in_translatable_text, validate_translation


class StubTranslator(DocumentTranslator):
    def __init__(self, result: str):
        super().__init__("en", api_key="dummy", client=object(), system_prompt="prompt")
        self.result = result

    def translate_text(self, text, **kwargs):
        return self.result, {"usage": None, "translation_time": 0.1}


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
            translator = StubTranslator("[English](changed.md)")
            success, details = translator.translate_file(source, target)
            self.assertFalse(success)
            self.assertIn("target changed", details["error_message"])
            self.assertEqual("Previous valid translation", target.read_text(encoding="utf-8"))

    def test_success_atomically_replaces_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            target = root / "target.md"
            source.write_text("[中文](same.md)", encoding="utf-8")
            target.write_text("old", encoding="utf-8")
            translator = StubTranslator("[English](same.md)")
            success, _ = translator.translate_file(source, target)
            self.assertTrue(success)
            self.assertEqual("[English](same.md)", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
