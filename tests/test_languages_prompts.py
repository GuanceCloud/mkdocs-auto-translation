import tempfile
import unittest
from pathlib import Path

from mkdocs_translator.languages import get_profile, normalize_language, parse_languages
from mkdocs_translator.prompts import build_prompt_bundle
from mkdocs_translator.terminology import TerminologyError, load_terminology


class LanguageAndPromptTests(unittest.TestCase):
    def test_aliases_and_multi_language_order(self):
        self.assertEqual("en", normalize_language(" English "))
        self.assertEqual("ja", normalize_language("日文"))
        self.assertEqual("ko", normalize_language("韩语"))
        self.assertEqual(("ja", "en", "ko"), parse_languages("ja,英语,ko,ja"))
        with self.assertRaises(ValueError):
            parse_languages("en,,ko")
        with self.assertRaises(ValueError):
            normalize_language("fr")

    def test_each_prompt_has_only_its_language_terminology(self):
        terminology = load_terminology()
        prompts = {}
        for language in ("en", "ja", "ko"):
            terms, missing = terminology.for_language(language)
            prompts[language] = build_prompt_bundle(get_profile(language), terms, missing)
        self.assertIn("です・ます", prompts["ja"].system_prompt)
        self.assertIn("합니다", prompts["ko"].system_prompt)
        self.assertIn("half-width English punctuation", prompts["en"].system_prompt)
        self.assertNotIn("서비스 맵", prompts["ja"].system_prompt)
        self.assertNotIn("サービスマップ", prompts["ko"].system_prompt)
        self.assertEqual("Service Map", prompts["en"].terminology["服务拓扑"])

    def test_custom_glossary_overrides_one_language_only(self):
        built_in = load_terminology()
        built_in_en, _ = built_in.for_language("en")
        built_in_ja, _ = built_in.for_language("ja")
        original_en_fingerprint = build_prompt_bundle(get_profile("en"), built_in_en).fingerprint
        original_ja_fingerprint = build_prompt_bundle(get_profile("ja"), built_in_ja).fingerprint
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.yml"
            path.write_text(
                "version: 1\nterms:\n  服务拓扑:\n    ja: カスタムマップ\n",
                encoding="utf-8",
            )
            terminology = load_terminology(path)
            ja, _ = terminology.for_language("ja")
            en, _ = terminology.for_language("en")
            self.assertEqual("カスタムマップ", ja["服务拓扑"])
            self.assertEqual("Service Map", en["服务拓扑"])
            self.assertEqual(
                original_en_fingerprint,
                build_prompt_bundle(get_profile("en"), en).fingerprint,
            )
            self.assertNotEqual(
                original_ja_fingerprint,
                build_prompt_bundle(get_profile("ja"), ja).fingerprint,
            )

    def test_invalid_glossary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.yml"
            path.write_text("version: 1\nterms:\n  foo:\n    fr: bar\n", encoding="utf-8")
            with self.assertRaises(TerminologyError):
                load_terminology(path)
            path.write_text("version: 1\nterms:\n  foo:\n    1: bar\n", encoding="utf-8")
            with self.assertRaises(TerminologyError):
                load_terminology(path)


if __name__ == "__main__":
    unittest.main()
