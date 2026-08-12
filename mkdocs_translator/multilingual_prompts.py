"""Backward-compatible imports for the pre-implementation prompt module.

New code should use :mod:`mkdocs_translator.prompts` and
:mod:`mkdocs_translator.terminology`. No terminology is defined here.
"""

from .languages import get_profile
from .prompts import build_translation_system_prompt as _build_prompt
from .terminology import load_terminology


OBSERVABILITY_TERMINOLOGY = load_terminology().terms


def build_translation_system_prompt(language: str) -> str:
    profile = get_profile(language)
    terminology = load_terminology()
    terms, _ = terminology.for_language(profile.code)
    concepts, _ = terminology.concepts_for_language(profile.code)
    return _build_prompt(profile, terms, concepts)


JAPANESE_TRANSLATION_SYSTEM_PROMPT = build_translation_system_prompt("ja")
KOREAN_TRANSLATION_SYSTEM_PROMPT = build_translation_system_prompt("ko")
