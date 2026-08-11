import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from .languages import LanguageProfile


PROMPT_VERSION = 2

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
8. 原文出现术语表中的词语时，必须始终使用指定的产品术语。
9. 术语表未覆盖的专业词语，应采用目标语言在可观测性、APM、RUM、日志、云计算和安全领域的通行表达。
</format_rules>"""


@dataclass(frozen=True)
class PromptBundle:
    language: str
    system_prompt: str
    fingerprint: str
    terminology: Dict[str, str]
    missing_terms: Tuple[str, ...]


def _format_terminology(terms: Mapping[str, str]) -> str:
    return "\n".join(f"- {source}: {translation}" for source, translation in sorted(terms.items()))


def build_prompt_bundle(
    profile: LanguageProfile,
    terminology: Mapping[str, str],
    missing_terms: Tuple[str, ...] = (),
) -> PromptBundle:
    system_prompt = (
        f"{COMMON_RULES}\n\n{profile.rules}\n\n<terminology>\n"
        f"{_format_terminology(terminology)}\n</terminology>"
    )
    fingerprint_payload = json.dumps(
        {
            "language": profile.code,
            "profile_version": profile.profile_version,
            "prompt_version": PROMPT_VERSION,
            "terms": dict(sorted(terminology.items())),
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
        missing_terms=tuple(missing_terms),
    )


def build_translation_system_prompt(profile: LanguageProfile, terminology: Mapping[str, str]) -> str:
    return build_prompt_bundle(profile, terminology).system_prompt
