from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    display_name: str
    model_name: str
    aliases: Tuple[str, ...]
    profile_version: int
    supports_han_residual_check: bool
    rules: str


LANGUAGE_PROFILES: Dict[str, LanguageProfile] = {
    "en": LanguageProfile(
        code="en",
        display_name="英语",
        model_name="English",
        aliases=("en", "english", "英语", "英文"),
        profile_version=1,
        supports_han_residual_check=True,
        rules="""<target_language_rules>
- The target language is English. Use concise, professional observability product documentation style.
- Use half-width English punctuation.
- Translate standalone Chinese common nouns as plural English nouns when that is grammatically natural.
- Preserve established abbreviations and product names such as APM, RUM, SLO, API, SDK, HTTP, JSON, YAML, DataKit, and Guance.
- Use terminology customary in observability, cloud computing, and security documentation instead of literal word-for-word translations.
</target_language_rules>""",
    ),
    "ja": LanguageProfile(
        code="ja",
        display_name="日语",
        model_name="Japanese",
        aliases=("ja", "japanese", "日语", "日文"),
        profile_version=1,
        supports_han_residual_check=False,
        rules="""<target_language_rules>
- 翻訳先は日本語です。可観測性製品の公式技術文書として、正確で簡潔な「です・ます」調を使用してください。
- UI ラベル、見出し、表の項目名は自然な名詞句にしてください。
- 日本語の本文では「、」「。」など自然な日本語の句読点を使用してください。
- APM、RUM、SLO、API、SDK、HTTP、JSON、YAML などの標準的な技術略語、および製品名は原文の表記を維持してください。
- 中国語の語順を直訳せず、日本のエンジニアが自然に理解できる可観測性・クラウド・セキュリティ分野の定着した表現を使用してください。
</target_language_rules>""",
    ),
    "ko": LanguageProfile(
        code="ko",
        display_name="韩语",
        model_name="Korean",
        aliases=("ko", "korean", "韩语", "韩文"),
        profile_version=1,
        supports_han_residual_check=True,
        rules="""<target_language_rules>
- 번역 대상 언어는 한국어입니다. 관측 가능성 제품의 공식 기술 문서에 적합한 정확하고 간결한 `합니다`체를 사용하세요.
- UI 레이블, 제목, 표 항목은 자연스러운 명사구로 번역하세요.
- 한국어 본문에는 한국 기술 문서의 자연스러운 문장 부호와 띄어쓰기를 사용하세요.
- APM, RUM, SLO, API, SDK, HTTP, JSON, YAML 등의 표준 기술 약어와 제품명은 원래 표기를 유지하세요.
- 중국어 어순을 그대로 옮기지 말고 관측 가능성, 클라우드, 보안 분야의 정착된 표현을 사용하세요.
</target_language_rules>""",
    ),
}


_ALIASES = {
    alias.casefold(): code
    for code, profile in LANGUAGE_PROFILES.items()
    for alias in profile.aliases
}


def normalize_language(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or normalized not in _ALIASES:
        supported = ", ".join(LANGUAGE_PROFILES)
        raise ValueError(f"Unsupported target language '{value}'. Supported codes: {supported}")
    return _ALIASES[normalized]


def parse_languages(values: str) -> Tuple[str, ...]:
    raw_values = values.split(",")
    if any(not value.strip() for value in raw_values):
        raise ValueError("--target-languages contains an empty language item")
    result = []
    for value in raw_values:
        language = normalize_language(value)
        if language not in result:
            result.append(language)
    return tuple(result)


def get_profile(language: str) -> LanguageProfile:
    return LANGUAGE_PROFILES[normalize_language(language)]


def supported_languages() -> Iterable[str]:
    return LANGUAGE_PROFILES.keys()
