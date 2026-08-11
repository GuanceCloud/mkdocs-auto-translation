import shutil
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, List, Set


TRANSLATABLE_SUFFIXES = {".md", ".pages"}
CONTROL_NAMES = {
    ".translate-blacklist",
    "metadata.json",
    "last-metadata.json",
    "translation.log",
}
CONTROL_DIRECTORIES = {".mkdocs-translator", ".translation-cache", "__pycache__"}


def is_translatable_path(path: Path) -> bool:
    return path.name == ".pages" or path.suffix in TRANSLATABLE_SUFFIXES


def get_translatable_files(directory: Path) -> List[Path]:
    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file()
            and is_translatable_path(path)
            and not any(part in CONTROL_DIRECTORIES for part in path.relative_to(directory).parts)
        ),
        key=lambda path: path.relative_to(directory).as_posix(),
    )


def load_blacklist(blacklist_path: Path) -> Set[str]:
    if not blacklist_path.exists():
        return set()
    with blacklist_path.open("r", encoding="utf-8") as handle:
        return {
            line.strip()
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        }


def is_blacklisted(relative_path: Path, blacklist: Iterable[str]) -> bool:
    value = relative_path.as_posix()
    for pattern in blacklist:
        normalized = pattern.replace("\\", "/")
        if value == normalized:
            return True
        if normalized.endswith("/") and value.startswith(normalized):
            return True
        if ("*" in normalized or "?" in normalized) and fnmatch(value, normalized):
            return True
    return False


def _is_control_path(relative_path: Path) -> bool:
    return (
        (len(relative_path.parts) == 1 and relative_path.name in CONTROL_NAMES)
        or any(part in CONTROL_DIRECTORIES for part in relative_path.parts)
        or relative_path.name.endswith(".tmp")
    )


def _resource_paths(directory: Path) -> Set[Path]:
    if not directory.exists():
        return set()
    return {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file()
        and not is_translatable_path(path)
        and not _is_control_path(path.relative_to(directory))
    }


def copy_resources(
    source_dir: Path,
    target_dir: Path,
    overwrite_resources: bool = False,
    delete_removed_resources: bool = False,
) -> None:
    source_resources = _resource_paths(source_dir)
    target_resources = _resource_paths(target_dir)
    for relative_path in sorted(source_resources, key=lambda value: value.as_posix()):
        source_file = source_dir / relative_path
        target_file = target_dir / relative_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if overwrite_resources or not target_file.exists():
            shutil.copy2(source_file, target_file)

    if delete_removed_resources:
        for relative_path in sorted(target_resources - source_resources, key=lambda value: value.as_posix()):
            target_file = target_dir / relative_path
            if target_file.is_file():
                target_file.unlink()
            parent = target_file.parent
            while parent != target_dir and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
