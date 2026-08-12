import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from .languages import LanguageProfile
from .terminology import ConceptRule


PROMPT_VERSION = 3

COMMON_RULES = """<role>
你是熟悉 Datadog 等专业可观测性产品的技术翻译专家。你的任务是把 Guance 中文产品文档翻译成面向目标语言地区工程师的正式技术文档。
</role>

<task>
只翻译 `<input_content>` 内的中文 Markdown 或 YAML。只输出译文，不得添加解释、前言、XML 标签或包裹整篇结果的代码块。
</task>

<format_rules>
1. 保持标题、列表、表格、引用、空行和 Markdown 注释的结构与顺序。
2. 保持 Markdown 链接和图片语法。翻译显示文本和 alt，不得修改 URL、路径或锚点。
3. 保持粗体、斜体、行内代码和代码围栏。不得翻译代码、命令、标识符和配置值，只翻译自然语言注释。
4. 不得修改 HTML 标签、属性名和属性值，只翻译供人阅读的文本节点。
5. `<<< >>>` 包围的模板变量必须逐字保留。
6. 保持 YAML 的层级、列表结构、控制字段、路径、URL、文件名和配置值；翻译标题、说明和导航中的人类可读标签。
7. 不得增加、删除、概括、推测或擅自修正原文信息。
8. 原文出现术语表中的词语时，必须始终使用指定的产品术语；多个词条重叠时优先采用最长、最具体的完整短语。
9. 术语表未覆盖的专业词语，应采用目标语言在可观测性、APM、RUM、日志、云计算和安全领域的通行表达。
10. `GXP_..._X` 是程序生成的不可翻译保护标记，必须逐字保留，每个标记只能出现一次，不得删除、复制、拆分、改写或调整相对顺序。
</format_rules>"""


@dataclass(frozen=True)
class PromptBundle:
    language: str
    system_prompt: str
    fingerprint: str
    terminology: Dict[str, str]
    missing_terms: Tuple[str, ...]
    concepts: Dict[str, ConceptRule] = field(default_factory=dict)


def _format_terminology(terms: Mapping[str, str]) -> str:
    return "\n".join(f"- {source}: {translation}" for source, translation in sorted(terms.items()))


def _format_concepts(language: str, concepts: Mapping[str, ConceptRule]) -> str:
    if not concepts:
        return ""
    lines = [
        "<concept_terminology>",
        "以下术语同时具有全称和缩写，必须按规则选择，不得把其中任何一种永久固定到所有场景：",
        "1. 原文已经使用缩写时，原样保留缩写，不得重复展开。",
        "2. Markdown 文档标题或正文中中文全称首次出现时，使用“全称（缩写）”；同一输入文档后续只使用缩写。",
        "3. YAML 导航、菜单、按钮、表格列名等紧凑 UI 标签只使用缩写。",
        "4. 代码、URL、路径、配置项、标签名以及引用的 UI 原文不得展开。",
        "5. 中文全称旁已经带有相同缩写时，只输出一次“全称（缩写）”，不得重复缩写。",
    ]
    for source, rule in sorted(concepts.items()):
        if language == "ja":
            separator, closing = "（", "）"
        elif language == "ko":
            separator, closing = "(", ")"
        else:
            separator, closing = " (", ")"
        first = f"{rule.full}{separator}{rule.short}{closing}"
        lines.append(
            f"- {source}: 首次出现={first}; 后续/短格式={rule.short}; UI={getattr(rule, rule.ui)}"
        )
    lines.append("</concept_terminology>")
    return "\n".join(lines)


def build_prompt_bundle(
    profile: LanguageProfile,
    terminology: Mapping[str, str],
    missing_terms: Tuple[str, ...] = (),
    concepts: Optional[Mapping[str, ConceptRule]] = None,
) -> PromptBundle:
    concepts = dict(concepts or {})
    concept_section = _format_concepts(profile.code, concepts)
    system_prompt = (
        f"{COMMON_RULES}\n\n{profile.rules}\n\n<terminology>\n"
        f"{_format_terminology(terminology)}\n</terminology>"
    )
    if concept_section:
        system_prompt = f"{system_prompt}\n\n{concept_section}"
    fingerprint_payload = json.dumps(
        {
            "language": profile.code,
            "profile_version": profile.profile_version,
            "prompt_version": PROMPT_VERSION,
            "terms": dict(sorted(terminology.items())),
            "concepts": {
                source: {
                    "full": rule.full,
                    "short": rule.short,
                    "usage": rule.usage,
                    "ui": rule.ui,
                }
                for source, rule in sorted(concepts.items())
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
    return PromptBundle(
        language=profile.code,
        system_prompt=system_prompt,
        fingerprint=fingerprint,
        terminology=dict(terminology),
        concepts=concepts,
        missing_terms=tuple(missing_terms),
    )


def build_translation_system_prompt(
    profile: LanguageProfile,
    terminology: Mapping[str, str],
    concepts: Optional[Mapping[str, ConceptRule]] = None,
) -> str:
    return build_prompt_bundle(profile, terminology, concepts=concepts).system_prompt
