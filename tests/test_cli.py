import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from mkdocs_translator.cli import (
    ProgressReporter,
    TranslationTask,
    _worker_task_totals,
    translate,
)


class FakeProgressBar:
    def __init__(self, total=None, desc=None, bar_format=None, **kwargs):
        self.total = total
        self.desc = desc
        self.bar_format = bar_format
        self.n = 0

    def set_description(self, desc):
        self.desc = desc

    def refresh(self):
        pass

    def update(self, amount):
        self.n += amount

    def close(self):
        pass


class FakeTranslator:
    active = 0
    max_active = 0
    calls = 0
    lock = threading.Lock()

    def __init__(self, target_lang, **kwargs):
        self.target_lang = target_lang

    def translate_file(self, source_path, target_path, **kwargs):
        with self.lock:
            type(self).active += 1
            type(self).calls += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            time.sleep(0.01)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(f"{self.target_lang}: translated", encoding="utf-8")
            return True, {"translation_time": 0.01, "usage": None}
        finally:
            with self.lock:
                type(self).active -= 1


class PartiallyFailingTranslator(FakeTranslator):
    def translate_file(self, source_path, target_path, **kwargs):
        if self.target_lang == "ja" and source_path.name == "0.md":
            return False, {"error_message": "intentional failure"}
        return super().translate_file(source_path, target_path, **kwargs)


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeTranslator.active = 0
        FakeTranslator.max_active = 0
        FakeTranslator.calls = 0

    def test_single_language_target_is_exact_directory_and_second_run_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            target = root / "english-output"
            source.mkdir()
            (source / "index.md").write_text("中文", encoding="utf-8")
            runner = CliRunner()
            args = ["--source", str(source), "--target", str(target), "--target-language", "en", "--api-key", "dummy"]
            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                first = runner.invoke(translate, args)
                second = runner.invoke(translate, args)
            self.assertEqual(0, first.exit_code, first.output)
            self.assertEqual(0, second.exit_code, second.output)
            self.assertTrue((target / "index.md").is_file())
            self.assertFalse((target / "en").exists())
            self.assertEqual(1, FakeTranslator.calls)
            self.assertIn("skipped=1", second.output)

    def test_glossary_change_does_not_retranslate_existing_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            target = root / "en"
            glossary = root / "glossary.yml"
            source.mkdir()
            (source / "index.md").write_text("服务拓扑", encoding="utf-8")
            glossary.write_text(
                "version: 1\nterms:\n  服务拓扑:\n    en: Service Map A\n",
                encoding="utf-8",
            )
            args = [
                "--source", str(source),
                "--target", str(target),
                "--target-language", "en",
                "--glossary", str(glossary),
                "--api-key", "dummy",
            ]
            runner = CliRunner()
            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                first = runner.invoke(translate, args)
                glossary.write_text(
                    "version: 1\nterms:\n  服务拓扑:\n    en: Service Map B\n",
                    encoding="utf-8",
                )
                second = runner.invoke(translate, args)

            self.assertEqual(0, first.exit_code, first.output)
            self.assertEqual(0, second.exit_code, second.output)
            self.assertEqual(1, FakeTranslator.calls)
            self.assertIn("skipped=1", second.output)

    def test_blank_sources_are_copied_without_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            target = root / "docs"
            source.mkdir()
            (source / "empty.md").write_bytes(b"")
            (source / "whitespace.md").write_text(" \n\t", encoding="utf-8")
            stale_target = target / "en" / "empty.md"
            stale_target.parent.mkdir(parents=True)
            stale_target.write_text("stale translation", encoding="utf-8")
            args = [
                "--source", str(source),
                "--target", str(target),
                "--target-languages", "en,ja,ko",
                "--api-key", "dummy",
            ]

            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                first = CliRunner().invoke(translate, args)
                second = CliRunner().invoke(translate, args)

            self.assertEqual(0, first.exit_code, first.output)
            self.assertEqual(0, second.exit_code, second.output)
            self.assertEqual(0, FakeTranslator.calls)
            for language in ("en", "ja", "ko"):
                self.assertEqual(b"", (target / language / "empty.md").read_bytes())
                self.assertEqual(" \n\t", (target / language / "whitespace.md").read_text(encoding="utf-8"))
                metadata = json.loads(
                    (target / language / ".mkdocs-translator" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertEqual("success", metadata["files"]["empty.md"]["status"])
                self.assertEqual("success", metadata["files"]["whitespace.md"]["status"])
            self.assertIn("total: success=0, failed=0, skipped=6", first.output)
            self.assertIn("total: success=0, failed=0, skipped=6", second.output)

    def test_blank_source_becoming_non_blank_is_translated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            target = root / "en"
            source.mkdir()
            source_file = source / "index.md"
            source_file.write_text("\n", encoding="utf-8")
            args = [
                "--source", str(source),
                "--target", str(target),
                "--target-language", "en",
                "--api-key", "dummy",
            ]

            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                first = CliRunner().invoke(translate, args)
                source_file.write_text("中文内容", encoding="utf-8")
                second = CliRunner().invoke(translate, args)

            self.assertEqual(0, first.exit_code, first.output)
            self.assertEqual(0, second.exit_code, second.output)
            self.assertEqual(1, FakeTranslator.calls)
            self.assertEqual("en: translated", (target / "index.md").read_text(encoding="utf-8"))

    def test_multi_language_uses_language_subdirectories_and_global_worker_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            source = docs / "zh"
            source.mkdir(parents=True)
            for index in range(10):
                (source / f"{index}.md").write_text(f"中文 {index}", encoding="utf-8")
            runner = CliRunner()
            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                result = runner.invoke(
                    translate,
                    [
                        "--source", str(source),
                        "--target", str(docs),
                        "--target-languages", "en,ja,ko",
                        "--workers", "10",
                        "--api-key", "dummy",
                    ],
                )
            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual(30, FakeTranslator.calls)
            self.assertLessEqual(FakeTranslator.max_active, 10)
            self.assertGreater(FakeTranslator.max_active, 1)
            for language in ("en", "ja", "ko"):
                self.assertTrue((docs / language / "0.md").is_file())
                metadata = json.loads(
                    (docs / language / ".mkdocs-translator" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertEqual(language, metadata["target_language"])
                self.assertEqual(10, len(metadata["files"]))
            run_ids = {
                json.loads(
                    (docs / language / ".mkdocs-translator" / "last-run.json").read_text(encoding="utf-8")
                )["run_id"]
                for language in ("en", "ja", "ko")
            }
            self.assertEqual(1, len(run_ids))

    def test_worker_task_totals_are_balanced_and_cover_every_task(self):
        totals = _worker_task_totals(task_count=64, worker_count=3)

        self.assertEqual([22, 21, 21], totals)
        self.assertEqual(64, sum(totals))
        self.assertLessEqual(max(totals) - min(totals), 1)
        self.assertEqual([], _worker_task_totals(task_count=0, worker_count=0))

    def test_worker_progress_shows_assigned_total_and_updates_completed_count(self):
        contexts = {
            "en": SimpleNamespace(success=0, failed=0, skipped=0),
        }
        task = TranslationTask("en", Path("source.md"), Path("guide/source.md"))

        with patch("mkdocs_translator.cli.tqdm", FakeProgressBar), patch(
            "mkdocs_translator.cli.sys.stderr.isatty", return_value=True
        ):
            progress = ProgressReporter(total=2, worker_totals=[2], contexts=contexts)
            progress.start(0, task)
            self.assertIn("[en] guide/source.md", progress.worker_bars[0].desc)
            self.assertIn("[{n_fmt}/{total_fmt}]", progress.worker_bars[0].bar_format)

            progress.complete(0)
            self.assertEqual(1, progress.worker_bars[0].n)
            self.assertEqual("Worker 1: waiting", progress.worker_bars[0].desc)

            progress.complete(0)
            self.assertEqual(2, progress.worker_bars[0].n)
            self.assertEqual("Worker 1: done", progress.worker_bars[0].desc)

    def test_existing_language_directory_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            target_root = root / "target"
            source.mkdir()
            (source / "index.md").write_text("中文", encoding="utf-8")
            (target_root / "en").mkdir(parents=True)
            marker = target_root / "en" / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with patch("mkdocs_translator.cli.DocumentTranslator", FakeTranslator):
                result = CliRunner().invoke(
                    translate,
                    ["--source", str(source), "--target", str(target_root), "--target-languages", "en,ja", "--api-key", "dummy"],
                )
            self.assertEqual(0, result.exit_code, result.output)
            self.assertEqual("keep", marker.read_text(encoding="utf-8"))

    def test_conflicting_cli_modes_and_unsafe_target_fail_before_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            source.mkdir()
            runner = CliRunner()
            conflict = runner.invoke(
                translate,
                ["--source", str(source), "--target", str(root / "out"), "--target-language", "en", "--target-languages", "ja,ko", "--api-key", "dummy"],
            )
            unsafe = runner.invoke(
                translate,
                ["--source", str(source), "--target", str(source / "out"), "--target-language", "en", "--api-key", "dummy"],
            )
            self.assertEqual(2, conflict.exit_code)
            self.assertEqual(2, unsafe.exit_code)

    def test_no_check_structure_is_available_and_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            source.mkdir()
            (source / "index.md").write_text("中文", encoding="utf-8")
            captured = {}

            class CapturingTranslator(FakeTranslator):
                def __init__(self, target_lang, **kwargs):
                    captured.update(kwargs)
                    super().__init__(target_lang, **kwargs)

            with patch("mkdocs_translator.cli.DocumentTranslator", CapturingTranslator):
                result = CliRunner().invoke(
                    translate,
                    [
                        "--source", str(source),
                        "--target", str(root / "en"),
                        "--target-language", "en",
                        "--no-check-structure",
                        "--api-key", "dummy",
                    ],
                )

            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("Structure protection and validation are disabled", result.output)
            self.assertFalse(captured["check_structure"])

    def test_one_language_failure_does_not_cancel_other_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zh"
            source.mkdir()
            (source / "0.md").write_text("中文 0", encoding="utf-8")
            (source / "1.md").write_text("中文 1", encoding="utf-8")
            target = root / "target"
            with patch("mkdocs_translator.cli.DocumentTranslator", PartiallyFailingTranslator), patch(
                "mkdocs_translator.cli.logging.error"
            ) as log_error:
                result = CliRunner().invoke(
                    translate,
                    ["--source", str(source), "--target", str(target), "--target-languages", "en,ja", "--workers", "2", "--api-key", "dummy"],
                )
            self.assertEqual(1, result.exit_code, result.output)
            self.assertIn("Failed translations (1):", result.output)
            self.assertIn("- [ja] 0.md: intentional failure", result.output)
            log_error.assert_any_call("Translation failure summary: %d failed task(s)", 1)
            log_error.assert_any_call("FAILED [%s] %s: %s", "ja", "0.md", "intentional failure")
            self.assertTrue((target / "en" / "0.md").is_file())
            self.assertTrue((target / "en" / "1.md").is_file())
            self.assertFalse((target / "ja" / "0.md").exists())
            self.assertTrue((target / "ja" / "1.md").is_file())
            ja_report = json.loads(
                (target / "ja" / ".mkdocs-translator" / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual("partial_failure", ja_report["status"])
            self.assertEqual(1, ja_report["counts"]["failed"])


if __name__ == "__main__":
    unittest.main()
