import hashlib
import json
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import yaml

from .languages import LANGUAGE_PROFILES


class TerminologyError(ValueError):
    """Raised when a terminology file is invalid."""


@dataclass(frozen=True)
class ConceptTranslation:
    full: str
    short: str


@dataclass(frozen=True)
class ConceptTerm:
    translations: Dict[str, ConceptTranslation]
    usage: str = "first_mention"
    ui: str = "short"


@dataclass(frozen=True)
class ConceptRule:
    full: str
    short: str
    usage: str
    ui: str


@dataclass(frozen=True)
class TerminologySet:
    # ``terms`` retains the legacy short-string view for compatibility. Concept
    # entries are filtered out by ``for_language`` and exposed with their policy
    # through ``concepts_for_language``.
    terms: Dict[str, Dict[str, str]]
    concepts: Dict[str, ConceptTerm] = field(default_factory=dict)

    def for_language(self, language: str) -> Tuple[Dict[str, str], Tuple[str, ...]]:
        effective = {}
        missing = []
        for source, translations in self.terms.items():
            concept = self.concepts.get(source)
            if concept is not None and language in concept.translations:
                continue
            value = translations.get(language)
            if value:
                effective[source] = value
            else:
                missing.append(source)
        return effective, tuple(missing)

    def concepts_for_language(
        self, language: str
    ) -> Tuple[Dict[str, ConceptRule], Tuple[str, ...]]:
        effective = {}
        missing = []
        for source, concept in self.concepts.items():
            translation = concept.translations.get(language)
            if translation is None:
                # A fixed custom override for this language is handled by
                # ``for_language`` and is therefore not missing.
                if not self.terms.get(source, {}).get(language):
                    missing.append(source)
                continue
            effective[source] = ConceptRule(
                full=translation.full,
                short=translation.short,
                usage=concept.usage,
                ui=concept.ui,
            )
        return effective, tuple(missing)


@dataclass(frozen=True)
class _ParsedTerminology:
    terms: Dict[str, Dict[str, str]]
    concepts: Dict[str, ConceptTerm]


def _validate_string(value: object, field: str, source_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TerminologyError(f"{source_name}: {field} must be a non-empty string")
    return value.strip()


def _validate_document(
    document: object, source_name: str, allow_partial: bool
) -> _ParsedTerminology:
    if not isinstance(document, dict):
        raise TerminologyError(f"{source_name}: glossary root must be a mapping")
    version = document.get("version")
    if version not in {1, 2}:
        raise TerminologyError(f"{source_name}: glossary version must be 1 or 2")
    unknown_root_keys = set(document) - {"version", "terms"}
    if unknown_root_keys:
        unknown = ", ".join(sorted(repr(key) for key in unknown_root_keys))
        raise TerminologyError(f"{source_name}: unknown fields: {unknown}")
    raw_terms = document.get("terms")
    if not isinstance(raw_terms, dict):
        raise TerminologyError(f"{source_name}: terms must be a mapping")

    result: Dict[str, Dict[str, str]] = {}
    concepts: Dict[str, ConceptTerm] = {}
    supported = set(LANGUAGE_PROFILES)
    policy_fields = {"usage", "ui"}
    for source, translations in raw_terms.items():
        if not isinstance(source, str) or not source.strip():
            raise TerminologyError(f"{source_name}: every source term must be a non-empty string")
        source = source.strip()
        if not isinstance(translations, dict):
            raise TerminologyError(f"{source_name}: translations for '{source}' must be a mapping")
        invalid_fields = [key for key in translations if not isinstance(key, str)]
        if invalid_fields:
            invalid = ", ".join(sorted(repr(key) for key in invalid_fields))
            raise TerminologyError(f"{source_name}: invalid fields for '{source}': {invalid}")

        language_fields = set(translations) - policy_fields
        unknown_languages = language_fields - supported
        if unknown_languages:
            raise TerminologyError(
                f"{source_name}: unsupported language fields for '{source}': "
                f"{', '.join(sorted(unknown_languages))}"
            )
        if not allow_partial and language_fields != supported:
            raise TerminologyError(f"{source_name}: '{source}' must define en, ja, and ko")

        is_concept = bool(policy_fields & set(translations)) or any(
            isinstance(translations.get(language), dict) for language in language_fields
        )
        if is_concept:
            if version < 2:
                raise TerminologyError(
                    f"{source_name}: concept term '{source}' requires glossary version 2"
                )
            usage = translations.get("usage", "first_mention")
            ui = translations.get("ui", "short")
            if usage != "first_mention":
                raise TerminologyError(
                    f"{source_name}: '{source}.usage' must be 'first_mention'"
                )
            if ui not in {"short", "full"}:
                raise TerminologyError(f"{source_name}: '{source}.ui' must be 'short' or 'full'")
            concept_translations = {}
            legacy_translations = {}
            for language in language_fields:
                value = translations[language]
                if not isinstance(value, dict) or set(value) != {"full", "short"}:
                    raise TerminologyError(
                        f"{source_name}: concept translation '{source}.{language}' "
                        "must define only full and short"
                    )
                full = _validate_string(
                    value.get("full"), f"translation '{source}.{language}.full'", source_name
                )
                short = _validate_string(
                    value.get("short"), f"translation '{source}.{language}.short'", source_name
                )
                concept_translations[language] = ConceptTranslation(full=full, short=short)
                legacy_translations[language] = short
            concepts[source] = ConceptTerm(
                translations=concept_translations,
                usage=usage,
                ui=ui,
            )
            result[source] = legacy_translations
            continue

        if policy_fields & set(translations):
            raise TerminologyError(f"{source_name}: fixed term '{source}' cannot define usage or ui")
        normalized = {}
        for language in language_fields:
            normalized[language] = _validate_string(
                translations[language], f"translation '{source}.{language}'", source_name
            )
        result[source] = normalized
    return _ParsedTerminology(terms=result, concepts=concepts)


def _load_yaml(path_or_resource, source_name: str, allow_partial: bool) -> _ParsedTerminology:
    try:
        with path_or_resource.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise TerminologyError(f"Cannot load glossary {source_name}: {exc}") from exc
    return _validate_document(document, source_name, allow_partial)


def _merge_terminology(base: _ParsedTerminology, custom: _ParsedTerminology) -> TerminologySet:
    merged_terms = {source: dict(values) for source, values in base.terms.items()}
    merged_concepts = {
        source: ConceptTerm(dict(concept.translations), concept.usage, concept.ui)
        for source, concept in base.concepts.items()
    }

    for source, translations in custom.terms.items():
        custom_concept = custom.concepts.get(source)
        for language, value in translations.items():
            merged_terms.setdefault(source, {})[language] = value
            if custom_concept is None or language not in custom_concept.translations:
                existing = merged_concepts.get(source)
                if existing is not None and language in existing.translations:
                    remaining = dict(existing.translations)
                    remaining.pop(language)
                    if remaining:
                        merged_concepts[source] = ConceptTerm(
                            remaining, existing.usage, existing.ui
                        )
                    else:
                        merged_concepts.pop(source)

        if custom_concept is not None:
            existing = merged_concepts.get(source)
            concept_translations = dict(existing.translations) if existing else {}
            concept_translations.update(custom_concept.translations)
            merged_concepts[source] = ConceptTerm(
                translations=concept_translations,
                usage=custom_concept.usage,
                ui=custom_concept.ui,
            )

    return TerminologySet(terms=merged_terms, concepts=merged_concepts)


def load_terminology(custom_path: Optional[Path] = None) -> TerminologySet:
    resource = files("mkdocs_translator.data").joinpath("terminology.yml")
    built_in = _load_yaml(resource, "built-in terminology.yml", allow_partial=False)
    if custom_path is None:
        return TerminologySet(terms=built_in.terms, concepts=built_in.concepts)

    custom_path = Path(custom_path)
    if not custom_path.is_file():
        raise TerminologyError(f"Custom glossary does not exist or is not a file: {custom_path}")
    custom = _load_yaml(custom_path, str(custom_path), allow_partial=True)
    return _merge_terminology(built_in, custom)


def terminology_digest(
    language: str,
    terms: Mapping[str, str],
    concepts: Optional[Mapping[str, ConceptRule]] = None,
) -> str:
    concept_payload = {
        source: {
            "full": rule.full,
            "short": rule.short,
            "usage": rule.usage,
            "ui": rule.ui,
        }
        for source, rule in sorted((concepts or {}).items())
    }
    canonical = json.dumps(
        {
            "language": language,
            "terms": dict(sorted(terms.items())),
            "concepts": concept_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
