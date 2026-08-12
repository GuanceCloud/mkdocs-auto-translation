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
            concepts, missing_concepts = terminology.concepts_for_language(language)
            prompts[language] = build_prompt_bundle(
                get_profile(language),
                terms,
                (*missing, *missing_concepts),
                concepts,
            )
        self.assertIn("です・ます", prompts["ja"].system_prompt)
        self.assertIn("합니다", prompts["ko"].system_prompt)
        self.assertIn("half-width English punctuation", prompts["en"].system_prompt)
        self.assertNotIn("서비스 맵", prompts["ja"].system_prompt)
        self.assertNotIn("サービスマップ", prompts["ko"].system_prompt)
        self.assertEqual("Service Map", prompts["en"].terminology["服务拓扑"])

    def test_acronym_concepts_have_first_mention_and_ui_rules(self):
        terminology = load_terminology()
        expected = {
            "en": "Application Performance Monitoring (APM)",
            "ja": "アプリケーションパフォーマンスモニタリング（APM）",
            "ko": "애플리케이션 성능 모니터링(APM)",
        }
        for language, first_mention in expected.items():
            terms, _ = terminology.for_language(language)
            concepts, missing = terminology.concepts_for_language(language)
            self.assertFalse(missing)
            self.assertNotIn("应用性能监测", terms)
            self.assertEqual("APM", concepts["应用性能监测"].short)
            self.assertEqual("short", concepts["应用性能监测"].ui)
            prompt = build_prompt_bundle(
                get_profile(language), terms, concepts=concepts
            ).system_prompt
            self.assertIn(f"首次出现={first_mention}", prompt)
            self.assertIn("后续/短格式=APM", prompt)
            self.assertIn("UI=APM", prompt)

    def test_professional_terms_and_removed_ambiguous_terms(self):
        terminology = load_terminology()
        en, _ = terminology.for_language("en")
        ja, _ = terminology.for_language("ja")
        ko, _ = terminology.for_language("ko")
        for ambiguous in ("指标", "日志", "页面", "操作", "存在", "不存在", "拨测"):
            self.assertNotIn(ambiguous, terminology.terms)
        self.assertEqual("Distributed Tracing", en["链路追踪"])
        self.assertEqual("Log Explorer", en["日志查看器"])
        self.assertEqual("ログエクスプローラー", ja["日志查看器"])
        self.assertEqual("로그 탐색기", ko["日志查看器"])
        self.assertEqual("메저먼트", ko["指标集"])

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

    def test_version_one_fixed_value_can_override_a_concept_language(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.yml"
            path.write_text(
                "version: 1\nterms:\n  应用性能监测:\n    en: Custom APM Label\n",
                encoding="utf-8",
            )
            terminology = load_terminology(path)
            en, missing = terminology.for_language("en")
            en_concepts, missing_concepts = terminology.concepts_for_language("en")
            ja_concepts, _ = terminology.concepts_for_language("ja")
            self.assertEqual("Custom APM Label", en["应用性能监测"])
            self.assertNotIn("应用性能监测", en_concepts)
            self.assertEqual("APM", ja_concepts["应用性能监测"].short)
            self.assertFalse(missing)
            self.assertFalse(missing_concepts)

    def test_custom_version_two_concept_overrides_one_language(self):
        built_in = load_terminology()
        built_in_fingerprints = {}
        for language in ("en", "ja"):
            terms, _ = built_in.for_language(language)
            concepts, _ = built_in.concepts_for_language(language)
            built_in_fingerprints[language] = build_prompt_bundle(
                get_profile(language), terms, concepts=concepts
            ).fingerprint
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.yml"
            path.write_text(
                """version: 2
terms:
  应用性能监测:
    ja:
      full: カスタムアプリケーション監視
      short: CUSTOM_APM
    usage: first_mention
    ui: short
""",
                encoding="utf-8",
            )
            terminology = load_terminology(path)
            ja, _ = terminology.concepts_for_language("ja")
            en, _ = terminology.concepts_for_language("en")
            self.assertEqual("CUSTOM_APM", ja["应用性能监测"].short)
            self.assertEqual("APM", en["应用性能监测"].short)
            for language, concepts in (("en", en), ("ja", ja)):
                terms, _ = terminology.for_language(language)
                fingerprint = build_prompt_bundle(
                    get_profile(language), terms, concepts=concepts
                ).fingerprint
                if language == "en":
                    self.assertEqual(built_in_fingerprints[language], fingerprint)
                else:
                    self.assertNotEqual(built_in_fingerprints[language], fingerprint)

    def test_concept_requires_version_two_and_full_short_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "glossary.yml"
            path.write_text(
                "version: 1\nterms:\n  应用性能监测:\n    en:\n      full: Application Performance Monitoring\n      short: APM\n",
                encoding="utf-8",
            )
            with self.assertRaises(TerminologyError):
                load_terminology(path)
            path.write_text(
                "version: 2\nterms:\n  应用性能监测:\n    en:\n      full: Application Performance Monitoring\n",
                encoding="utf-8",
            )
            with self.assertRaises(TerminologyError):
                load_terminology(path)


if __name__ == "__main__":
    unittest.main()
