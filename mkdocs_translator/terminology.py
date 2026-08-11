import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import yaml

from .languages import LANGUAGE_PROFILES


class TerminologyError(ValueError):
    """Raised when a terminology file is invalid."""


@dataclass(frozen=True)
class TerminologySet:
    terms: Dict[str, Dict[str, str]]

    def for_language(self, language: str) -> Tuple[Dict[str, str], Tuple[str, ...]]:
        effective = {}
        missing = []
        for source, translations in self.terms.items():
            value = translations.get(language)
            if value:
                effective[source] = value
            else:
                missing.append(source)
        return effective, tuple(missing)


def _validate_document(document: object, source_name: str, allow_partial: bool) -> Dict[str, Dict[str, str]]:
    if not isinstance(document, dict):
        raise TerminologyError(f"{source_name}: glossary root must be a mapping")
    if document.get("version") != 1:
        raise TerminologyError(f"{source_name}: glossary version must be 1")
    unknown_root_keys = set(document) - {"version", "terms"}
    if unknown_root_keys:
        unknown = ", ".join(sorted(repr(key) for key in unknown_root_keys))
        raise TerminologyError(f"{source_name}: unknown fields: {unknown}")
    terms = document.get("terms")
    if not isinstance(terms, dict):
        raise TerminologyError(f"{source_name}: terms must be a mapping")

    result: Dict[str, Dict[str, str]] = {}
    supported = set(LANGUAGE_PROFILES)
    for source, translations in terms.items():
        if not isinstance(source, str) or not source.strip():
            raise TerminologyError(f"{source_name}: every source term must be a non-empty string")
        if not isinstance(translations, dict):
            raise TerminologyError(f"{source_name}: translations for '{source}' must be a mapping")
        invalid_language_fields = [key for key in translations if not isinstance(key, str)]
        if invalid_language_fields:
            invalid = ", ".join(sorted(repr(key) for key in invalid_language_fields))
            raise TerminologyError(f"{source_name}: invalid language fields for '{source}': {invalid}")
        unknown_languages = set(translations) - supported
        if unknown_languages:
            raise TerminologyError(
                f"{source_name}: unsupported language fields for '{source}': "
                f"{', '.join(sorted(unknown_languages))}"
            )
        if not allow_partial and set(translations) != supported:
            raise TerminologyError(f"{source_name}: '{source}' must define en, ja, and ko")
        normalized = {}
        for language, value in translations.items():
            if not isinstance(value, str) or not value.strip():
                raise TerminologyError(
                    f"{source_name}: translation '{source}.{language}' must be a non-empty string"
                )
            normalized[language] = value.strip()
        result[source.strip()] = normalized
    return result


def _load_yaml(path_or_resource, source_name: str, allow_partial: bool) -> Dict[str, Dict[str, str]]:
    try:
        with path_or_resource.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise TerminologyError(f"Cannot load glossary {source_name}: {exc}") from exc
    return _validate_document(document, source_name, allow_partial)


def load_terminology(custom_path: Optional[Path] = None) -> TerminologySet:
    resource = files("mkdocs_translator.data").joinpath("terminology.yml")
    merged = _load_yaml(resource, "built-in terminology.yml", allow_partial=False)
    if custom_path is not None:
        custom_path = Path(custom_path)
        if not custom_path.is_file():
            raise TerminologyError(f"Custom glossary does not exist or is not a file: {custom_path}")
        custom = _load_yaml(custom_path, str(custom_path), allow_partial=True)
        for source, translations in custom.items():
            merged.setdefault(source, {}).update(translations)
    return TerminologySet(terms=merged)


def terminology_digest(language: str, terms: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {"language": language, "terms": dict(sorted(terms.items()))},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
