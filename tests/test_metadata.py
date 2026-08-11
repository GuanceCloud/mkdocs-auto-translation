import json
import tempfile
import threading
import unittest
from pathlib import Path

from mkdocs_translator.metadata import MetadataManager, file_hash


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "zh"
        self.target = self.root / "en"
        self.source.mkdir()
        self.target.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_incremental_state_requires_file_hash_fingerprint_and_target(self):
        source_file = self.source / "guide.md"
        target_file = self.target / "guide.md"
        source_file.write_text("中文", encoding="utf-8")
        target_file.write_text("English", encoding="utf-8")
        manager = MetadataManager(self.target, self.source, "en", "fingerprint-a")
        self.assertTrue(manager.needs_translation(Path("guide.md")))
        manager.update_file_status(Path("guide.md"), True, {"translation_time": 1.2})
        self.assertFalse(manager.needs_translation(Path("guide.md")))
        target_file.unlink()
        self.assertTrue(manager.needs_translation(Path("guide.md")))

        target_file.write_text("English", encoding="utf-8")
        changed = MetadataManager(self.target, self.source, "en", "fingerprint-b")
        self.assertTrue(changed.needs_translation(Path("guide.md")))

    def test_legacy_english_metadata_migrates_without_modifying_source(self):
        source_file = self.source / "guide.md"
        target_file = self.target / "guide.md"
        source_file.write_text("中文", encoding="utf-8")
        target_file.write_text("English", encoding="utf-8")
        legacy = {"guide.md": {"hash": file_hash(source_file), "status": "success"}}
        legacy_path = self.source / "metadata.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        original = legacy_path.read_text(encoding="utf-8")

        manager = MetadataManager(self.target, self.source, "en", "fingerprint")
        self.assertFalse(manager.needs_translation(Path("guide.md")))
        self.assertEqual(original, legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(1, manager.metadata["legacy_migration"]["imported_files"])

    def test_other_languages_do_not_import_legacy_metadata(self):
        source_file = self.source / "guide.md"
        source_file.write_text("中文", encoding="utf-8")
        (self.target / "guide.md").write_text("English", encoding="utf-8")
        (self.source / "metadata.json").write_text(
            json.dumps({"guide.md": {"hash": file_hash(source_file), "status": "success"}}),
            encoding="utf-8",
        )
        manager = MetadataManager(self.target, self.source, "ja", "fingerprint")
        self.assertTrue(manager.needs_translation(Path("guide.md")))

    def test_target_directory_cannot_be_rebound_to_another_language(self):
        MetadataManager(self.target, self.source, "en", "fingerprint")
        with self.assertRaises(ValueError):
            MetadataManager(self.target, self.source, "ja", "fingerprint")

    def test_delete_removed_translation_removes_file_and_record(self):
        source_file = self.source / "removed.md"
        target_file = self.target / "removed.md"
        source_file.write_text("中文", encoding="utf-8")
        target_file.write_text("English", encoding="utf-8")
        manager = MetadataManager(self.target, self.source, "en", "fingerprint")
        manager.update_file_status(Path("removed.md"), True, {})
        source_file.unlink()
        self.assertEqual(1, manager.delete_removed_translations([]))
        self.assertFalse(target_file.exists())
        self.assertNotIn("removed.md", manager.metadata["files"])

    def test_concurrent_updates_remain_complete_json(self):
        manager = MetadataManager(self.target, self.source, "en", "fingerprint")
        relative_paths = []
        for index in range(20):
            relative = Path(f"{index}.md")
            relative_paths.append(relative)
            (self.source / relative).write_text(str(index), encoding="utf-8")
            (self.target / relative).write_text(str(index), encoding="utf-8")
        threads = [
            threading.Thread(target=manager.update_file_status, args=(path, True, {}))
            for path in relative_paths
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        loaded = json.loads(manager.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(20, len(loaded["files"]))


if __name__ == "__main__":
    unittest.main()
