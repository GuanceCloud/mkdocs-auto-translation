import hashlib
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Iterable, Optional


METADATA_VERSION = 2
STATE_DIR_NAME = ".mkdocs-translator"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class MetadataManager:
    """Thread-safe per-target-language incremental state."""

    def __init__(
        self,
        target_dir: Path,
        source_dir: Path,
        target_language: str,
        translation_fingerprint: str,
        migrate_legacy: bool = True,
    ):
        self.target_dir = Path(target_dir)
        self.source_dir = Path(source_dir)
        self.target_language = target_language
        self.translation_fingerprint = translation_fingerprint
        self.state_dir = self.target_dir / STATE_DIR_NAME
        self.metadata_path = self.state_dir / "metadata.json"
        self.last_run_path = self.state_dir / "last-run.json"
        self._lock = threading.RLock()
        existed = self.metadata_path.exists()
        self.metadata = self._load_or_create()
        if not existed and migrate_legacy and target_language == "en":
            self._migrate_legacy()
        self.save()

    def _new_metadata(self) -> Dict:
        return {
            "version": METADATA_VERSION,
            "target_language": self.target_language,
            "translation_fingerprint": self.translation_fingerprint,
            "files": {},
        }

    def _load_or_create(self) -> Dict:
        if not self.metadata_path.exists():
            return self._new_metadata()
        try:
            with self.metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read metadata file {self.metadata_path}: {exc}") from exc
        if not isinstance(metadata, dict) or metadata.get("version") != METADATA_VERSION:
            raise ValueError(f"Unsupported metadata format in {self.metadata_path}")
        bound_language = metadata.get("target_language")
        if bound_language != self.target_language:
            raise ValueError(
                f"Target directory {self.target_dir} is bound to language '{bound_language}', "
                f"not '{self.target_language}'"
            )
        records = metadata.get("files")
        if not isinstance(records, dict):
            raise ValueError(f"Invalid files mapping in {self.metadata_path}")
        stored_fingerprint = metadata.get("translation_fingerprint")
        for record in records.values():
            if isinstance(record, dict) and stored_fingerprint:
                record.setdefault("translation_fingerprint", stored_fingerprint)
        metadata["translation_fingerprint"] = self.translation_fingerprint
        return metadata

    @staticmethod
    def _safe_relative_path(raw_path: str) -> Optional[Path]:
        normalized = raw_path.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or PureWindowsPath(normalized).is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            return None
        return Path(*path.parts)

    def _migrate_legacy(self) -> None:
        legacy_path = self.source_dir / "metadata.json"
        summary = {"completed": True, "migrated_at": utc_now(), "imported_files": 0}
        if not legacy_path.exists():
            self.metadata["legacy_migration"] = summary
            return
        try:
            with legacy_path.open("r", encoding="utf-8") as handle:
                legacy = json.load(handle)
            if not isinstance(legacy, dict):
                raise ValueError("legacy metadata root is not a mapping")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logging.warning("Ignoring invalid legacy metadata %s: %s", legacy_path, exc)
            summary["error"] = str(exc)
            self.metadata["legacy_migration"] = summary
            return

        imported = 0
        for raw_path, record in legacy.items():
            if not isinstance(raw_path, str) or not isinstance(record, dict):
                continue
            relative_path = self._safe_relative_path(raw_path)
            if relative_path is None:
                continue
            source_file = self.source_dir / relative_path
            target_file = self.target_dir / relative_path
            old_hash = record.get("hash") or record.get("source_hash")
            if (
                record.get("status") == "success"
                and source_file.is_file()
                and target_file.is_file()
                and old_hash == file_hash(source_file)
            ):
                self.metadata["files"][relative_path.as_posix()] = {
                    "source_hash": old_hash,
                    "last_translated": record.get("last_translated") or utc_now(),
                    "translation_time": record.get("translation_time", 0),
                    "status": "success",
                    "translation_fingerprint": self.translation_fingerprint,
                    "migrated_from_legacy": True,
                }
                imported += 1
        summary["imported_files"] = imported
        self.metadata["legacy_migration"] = summary

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.metadata_path, self.metadata)

    def needs_translation(self, relative_path: Path, target_file: Optional[Path] = None) -> bool:
        source_file = self.source_dir / relative_path
        target_file = target_file or self.target_dir / relative_path
        with self._lock:
            record = self.metadata["files"].get(relative_path.as_posix())
            return not (
                isinstance(record, dict)
                and record.get("status") == "success"
                and record.get("source_hash") == file_hash(source_file)
                and target_file.is_file()
            )

    def update_file_status(self, relative_path: Path, success: bool, details: Optional[Dict] = None) -> None:
        details = details or {}
        source_file = self.source_dir / relative_path
        record = {
            "source_hash": file_hash(source_file),
            "last_translated": utc_now(),
            "status": "success" if success else "failed",
            "translation_fingerprint": self.translation_fingerprint,
        }
        if success:
            record["translation_time"] = details.get("translation_time", 0)
            if "usage" in details:
                record["usage"] = details["usage"]
        else:
            record["error_message"] = details.get("error_message", "Unknown error")
        with self._lock:
            self.metadata["files"][relative_path.as_posix()] = record
            self.metadata["translation_fingerprint"] = self.translation_fingerprint
            self.save()

    def delete_removed_translations(self, valid_paths: Iterable[Path]) -> int:
        valid = {path.as_posix() for path in valid_paths}
        removed = 0
        with self._lock:
            for raw_path in list(self.metadata["files"]):
                if raw_path in valid:
                    continue
                relative_path = self._safe_relative_path(raw_path)
                if relative_path is not None and (
                    relative_path.name == ".pages" or relative_path.suffix in {".md", ".pages"}
                ):
                    target_file = self.target_dir / relative_path
                    if target_file.is_file():
                        target_file.unlink()
                        removed += 1
                del self.metadata["files"][raw_path]
            self.save()
        return removed

    def write_last_run(self, report: Dict) -> None:
        with self._lock:
            atomic_write_json(self.last_run_path, report)
