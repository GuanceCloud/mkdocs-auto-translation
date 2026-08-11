import tempfile
import unittest
from pathlib import Path

from mkdocs_translator.utils import copy_resources, get_translatable_files


class UtilsTests(unittest.TestCase):
    def test_pages_and_pages_suffix_are_translatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pages").write_text("nav: []", encoding="utf-8")
            (root / "nested.pages").write_text("nav: []", encoding="utf-8")
            (root / "index.md").write_text("text", encoding="utf-8")
            names = [path.name for path in get_translatable_files(root)]
            self.assertEqual([".pages", "index.md", "nested.pages"], names)

    def test_resource_sync_excludes_control_files_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            (source / "image.png").write_bytes(b"image")
            (source / "metadata.json").write_text("{}", encoding="utf-8")
            (source / ".translate-blacklist").write_text("draft.md", encoding="utf-8")
            state = target / ".mkdocs-translator" / "metadata.json"
            state.parent.mkdir(parents=True)
            state.write_text("{}", encoding="utf-8")
            stale = target / "stale.css"
            stale.write_text("stale", encoding="utf-8")

            copy_resources(source, target, delete_removed_resources=True)

            self.assertEqual(b"image", (target / "image.png").read_bytes())
            self.assertFalse((target / "metadata.json").exists())
            self.assertFalse((target / ".translate-blacklist").exists())
            self.assertEqual("{}", state.read_text(encoding="utf-8"))
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
