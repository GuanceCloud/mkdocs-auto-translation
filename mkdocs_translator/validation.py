import re
from pathlib import Path
from typing import Any, List, Tuple

import yaml


class ValidationError(ValueError):
    """Raised when translated output does not preserve the source structure."""


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})[^\n]*$", re.MULTILINE)
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_HTML_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][\w:-]*)\b[^>]*?>")
_TEMPLATE_RE = re.compile(r"<<<.*?>>>", re.DOTALL)
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_PATH_RE = re.compile(r"^(?:https?://|/|\./|\.\./|#|[\w.@+-]+/).+|^[\w.@+-]+\.[A-Za-z0-9]{1,8}(?:#.*)?$")
_CONTROL_KEYS = {
    "nav",
    "title",
    "hide",
    "status",
    "template",
    "order",
    "collapse",
    "draft",
}


def strip_protected_regions(text: str) -> str:
    visible_lines = []
    open_fence = None
    for line in text.splitlines(keepends=True):
        match = _FENCE_RE.match(line.rstrip("\r\n"))
        if open_fence is None and match:
            open_fence = (match.group(1)[0], len(match.group(1)))
            continue
        if open_fence is not None:
            if match and match.group(1)[0] == open_fence[0] and len(match.group(1)) >= open_fence[1]:
                open_fence = None
            continue
        visible_lines.append(line)
    text = "".join(visible_lines)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = _TEMPLATE_RE.sub("", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = _HTML_TAG_RE.sub("", text)
    text = re.sub(r"(?<=\]\()[^)]+(?=\))", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return text


def contains_han_in_translatable_text(text: str) -> bool:
    return bool(_HAN_RE.search(strip_protected_regions(text)))


def _fence_signature(text: str) -> List[Tuple[str, int]]:
    return [(match.group(1)[0], len(match.group(1))) for match in _FENCE_RE.finditer(text)]


def _html_signature(text: str) -> List[Tuple[bool, str]]:
    visible_lines = []
    open_fence = None
    for line in text.splitlines(keepends=True):
        match = _FENCE_RE.match(line.rstrip("\r\n"))
        if open_fence is None and match:
            open_fence = (match.group(1)[0], len(match.group(1)))
            continue
        if open_fence is not None:
            if match and match.group(1)[0] == open_fence[0] and len(match.group(1)) >= open_fence[1]:
                open_fence = None
            continue
        visible_lines.append(line)
    text = "".join(visible_lines)
    text = re.sub(r"(`+)[\s\S]*?\1", "", text)
    text = _TEMPLATE_RE.sub("", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return [(bool(match.group(1)), match.group(2).lower()) for match in _HTML_TAG_RE.finditer(text)]


def _path_values(value: Any, result: List[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _path_values(item, result)
    elif isinstance(value, list):
        for item in value:
            _path_values(item, result)
    elif isinstance(value, str) and _PATH_RE.match(value):
        result.append(value)


def _yaml_shape(source: Any, translated: Any, location: str = "root") -> None:
    if type(source) is not type(translated):
        raise ValidationError(f".pages YAML type changed at {location}")
    if isinstance(source, list):
        if len(source) != len(translated):
            raise ValidationError(f".pages YAML list length changed at {location}")
        for index, (source_item, translated_item) in enumerate(zip(source, translated)):
            _yaml_shape(source_item, translated_item, f"{location}[{index}]")
    elif isinstance(source, dict):
        if len(source) != len(translated):
            raise ValidationError(f".pages YAML mapping size changed at {location}")
        translated_items = list(translated.items())
        for index, (source_key, source_value) in enumerate(source.items()):
            translated_key, translated_value = translated_items[index]
            if source_key in _CONTROL_KEYS and source_key != translated_key:
                raise ValidationError(f".pages control key '{source_key}' changed at {location}")
            _yaml_shape(source_value, translated_value, f"{location}.{source_key}")


def validate_translation(
    source_text: str,
    translated_text: str,
    source_path: Path,
    check_chinese: bool,
    check_line_count: bool,
    check_structure: bool = True,
) -> None:
    if not translated_text.strip():
        raise ValidationError("Translation result is empty")
    if check_structure:
        if _fence_signature(source_text) != _fence_signature(translated_text):
            raise ValidationError("Markdown code fence structure changed")
        if [match.group(1) for match in _LINK_RE.finditer(source_text)] != [
            match.group(1) for match in _LINK_RE.finditer(translated_text)
        ]:
            raise ValidationError("Markdown link or image target changed")
        if _html_signature(source_text) != _html_signature(translated_text):
            raise ValidationError("HTML tag names or order changed")
        if _TEMPLATE_RE.findall(source_text) != _TEMPLATE_RE.findall(translated_text):
            raise ValidationError("Template variables changed")

        if source_path.name == ".pages" or source_path.suffix == ".pages":
            try:
                source_yaml = yaml.safe_load(source_text)
                translated_yaml = yaml.safe_load(translated_text)
            except yaml.YAMLError as exc:
                raise ValidationError(f"Invalid .pages YAML: {exc}") from exc
            _yaml_shape(source_yaml, translated_yaml)
            source_paths: List[str] = []
            translated_paths: List[str] = []
            _path_values(source_yaml, source_paths)
            _path_values(translated_yaml, translated_paths)
            if source_paths != translated_paths:
                raise ValidationError(".pages path, URL, or filename values changed")

    if check_line_count:
        source_lines = max(1, len(source_text.splitlines()))
        translated_lines = len(translated_text.splitlines())
        if abs(translated_lines - source_lines) / source_lines > 0.05:
            raise ValidationError(
                f"Line count differs by more than 5% ({source_lines} -> {translated_lines})"
            )
    if check_chinese and contains_han_in_translatable_text(translated_text):
        raise ValidationError("Translation result contains Chinese characters in translatable text")
