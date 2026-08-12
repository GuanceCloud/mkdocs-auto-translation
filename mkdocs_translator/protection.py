import re
import secrets
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


class ProtectionError(ValueError):
    """Raised when a model changes, drops, duplicates, or reorders protected content."""


_FENCE_LINE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*$")
_RAW_HTML_BLOCK_RE = re.compile(r"<(script|style|pre)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TEMPLATE_RE = re.compile(r"<<<.*?>>>", re.DOTALL)
_ANGLE_RE = re.compile(r"<[^>\n]+>")
_REFERENCE_TARGET_RE = re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(\S+)")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_YAML_PATH_RE = re.compile(r"^(?:https?://|/|\./|\.\./|#|[\w.@+-]+/).+|^[\w.@+-]+\.[A-Za-z0-9]{1,8}(?:#.*)?$")
_OUTER_FENCE_RE = re.compile(
    r"^[ \t]*(`{3,}|~{3,})(?:markdown|md|yaml|yml)?[ \t]*(?:\r?\n)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ProtectedSpan:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class ProtectedDocument:
    masked_text: str
    protected_values: Tuple[Tuple[str, str], ...]
    nonce: str

    @property
    def tokens(self) -> Tuple[str, ...]:
        return tuple(token for token, _ in self.protected_values)

    def restore(self, translated_text: str) -> str:
        expected = list(self.tokens)
        if not expected:
            return translated_text
        token_pattern = re.compile(rf"GXP_{re.escape(self.nonce)}_[0-9]{{5}}_X")
        found = token_pattern.findall(translated_text)
        if found != expected:
            expected_counts = Counter(expected)
            found_counts = Counter(found)
            missing = list((expected_counts - found_counts).elements())
            unexpected = list((found_counts - expected_counts).elements())
            duplicated = sorted(token for token, count in found_counts.items() if count > 1)
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unexpected:
                details.append(f"unexpected={unexpected}")
            if duplicated:
                details.append(f"duplicated={duplicated}")
            if not missing and not unexpected and found != expected:
                details.append("protected token order changed")
            raise ProtectionError("Protected content integrity check failed: " + "; ".join(details))

        values: Dict[str, str] = dict(self.protected_values)
        restored = token_pattern.sub(lambda match: values[match.group(0)], translated_text)
        if token_pattern.search(restored):
            raise ProtectionError("Protected content restoration left unresolved tokens")
        return restored


def _overlaps(spans: Sequence[_ProtectedSpan], start: int, end: int) -> bool:
    return any(start < span.end and end > span.start for span in spans)


def _add_span(spans: List[_ProtectedSpan], start: int, end: int, kind: str) -> None:
    if start < end and not _overlaps(spans, start, end):
        spans.append(_ProtectedSpan(start, end, kind))


def _free_ranges(text: str, spans: Sequence[_ProtectedSpan]):
    cursor = 0
    for span in sorted(spans, key=lambda item: item.start):
        if cursor < span.start:
            yield cursor, span.start
        cursor = max(cursor, span.end)
    if cursor < len(text):
        yield cursor, len(text)


def _protect_fence_markers(text: str, spans: List[_ProtectedSpan]) -> List[Tuple[int, int]]:
    """Protect fence delimiter lines while leaving fenced content visible to the model."""
    fenced_contents: List[Tuple[int, int]] = []
    offset = 0
    content_start = None
    open_marker = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        match = _FENCE_LINE_RE.match(content)
        if content_start is None and match:
            _add_span(spans, offset, offset + len(content), "fence_marker")
            content_start = offset + len(line)
            open_marker = match.group(1)
        elif content_start is not None and match:
            marker = match.group(1)
            if marker[0] == open_marker[0] and len(marker) >= len(open_marker):
                fenced_contents.append((content_start, offset))
                _add_span(spans, offset, offset + len(content), "fence_marker")
                content_start = None
                open_marker = None
        offset += len(line)
    if content_start is not None:
        fenced_contents.append((content_start, len(text)))
    return fenced_contents


def _inside_ranges(position: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _protect_inline_code(
    text: str,
    spans: List[_ProtectedSpan],
    excluded_ranges: Sequence[Tuple[int, int]] = (),
) -> None:
    for range_start, range_end in list(_free_ranges(text, spans)):
        index = range_start
        while index < range_end:
            if text[index] != "`":
                index += 1
                continue
            if _inside_ranges(index, excluded_ranges):
                index += 1
                continue
            opening_start = index
            while index < range_end and text[index] == "`":
                index += 1
            opening_length = index - opening_start
            closing_start = index
            while closing_start < range_end:
                if text[closing_start] != "`":
                    closing_start += 1
                    continue
                closing_end = closing_start
                while closing_end < range_end and text[closing_end] == "`":
                    closing_end += 1
                if closing_end - closing_start == opening_length:
                    _add_span(spans, opening_start, closing_end, "inline_code")
                    index = closing_end
                    break
                closing_start = closing_end
            else:
                index = opening_start + opening_length


def _protect_link_destinations(text: str, spans: List[_ProtectedSpan]) -> None:
    for range_start, range_end in list(_free_ranges(text, spans)):
        index = range_start
        while index + 1 < range_end:
            if text[index : index + 2] != "](" or (index and text[index - 1] == "\\"):
                index += 1
                continue
            content_start = index + 2
            cursor = content_start
            depth = 1
            quote = None
            escaped = False
            while cursor < range_end:
                character = text[cursor]
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif quote:
                    if character == quote:
                        quote = None
                elif character in {'"', "'"}:
                    quote = character
                elif character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        _add_span(spans, content_start, cursor, "link_destination")
                        index = cursor + 1
                        break
                cursor += 1
            else:
                index += 2


def _protect_regex_matches(
    text: str,
    spans: List[_ProtectedSpan],
    expression: re.Pattern,
    kind: str,
    group: int = 0,
) -> None:
    for range_start, range_end in list(_free_ranges(text, spans)):
        for match in expression.finditer(text, range_start, range_end):
            _add_span(spans, match.start(group), match.end(group), kind)


def _trim_url_end(value: str) -> int:
    end = len(value)
    while end and value[end - 1] in ".,;:!?":
        end -= 1
    while end and value[end - 1] == ")" and value[:end].count(")") > value[:end].count("("):
        end -= 1
    while end and value[end - 1] == "]" and value[:end].count("]") > value[:end].count("["):
        end -= 1
    return end


def _protect_urls(text: str, spans: List[_ProtectedSpan]) -> None:
    for range_start, range_end in list(_free_ranges(text, spans)):
        for match in _URL_RE.finditer(text, range_start, range_end):
            end = match.start() + _trim_url_end(match.group(0))
            _add_span(spans, match.start(), end, "url")


def _walk_yaml_scalars(node):
    if isinstance(node, ScalarNode):
        yield node
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _walk_yaml_scalars(item)
    elif isinstance(node, MappingNode):
        for key, value in node.value:
            yield from _walk_yaml_scalars(key)
            yield from _walk_yaml_scalars(value)


def _protect_pages_scalars(text: str, spans: List[_ProtectedSpan]) -> None:
    try:
        documents = list(yaml.compose_all(text))
    except yaml.YAMLError:
        return
    for document in documents:
        if document is None:
            continue
        for node in _walk_yaml_scalars(document):
            value = node.value
            if not _HAN_RE.search(value) or _YAML_PATH_RE.match(value):
                _add_span(spans, node.start_mark.index, node.end_mark.index, "yaml_control_or_path")


def protect_document(text: str, is_pages: bool = False) -> ProtectedDocument:
    """Mask source-controlled Markdown structures while leaving full prose context intact."""
    spans: List[_ProtectedSpan] = []
    fenced_contents = _protect_fence_markers(text, spans)
    _protect_regex_matches(text, spans, _RAW_HTML_BLOCK_RE, "raw_html_block")
    _protect_regex_matches(text, spans, _HTML_COMMENT_RE, "html_comment")
    _protect_inline_code(text, spans, fenced_contents)
    _protect_link_destinations(text, spans)
    if is_pages:
        _protect_pages_scalars(text, spans)
    _protect_regex_matches(text, spans, _TEMPLATE_RE, "template")
    _protect_regex_matches(text, spans, _ANGLE_RE, "html_or_placeholder")
    _protect_regex_matches(text, spans, _REFERENCE_TARGET_RE, "reference_target", group=1)
    _protect_urls(text, spans)
    spans.sort(key=lambda item: item.start)
    if len(spans) > 99999:
        raise ProtectionError(f"Document has too many protected regions: {len(spans)}")

    nonce = secrets.token_hex(6).upper()
    while f"GXP_{nonce}_" in text:
        nonce = secrets.token_hex(6).upper()

    parts = []
    protected_values = []
    cursor = 0
    for index, span in enumerate(spans, start=1):
        token = f"GXP_{nonce}_{index:05d}_X"
        parts.append(text[cursor : span.start])
        parts.append(token)
        protected_values.append((token, text[span.start : span.end]))
        cursor = span.end
    parts.append(text[cursor:])
    return ProtectedDocument("".join(parts), tuple(protected_values), nonce)


def strip_single_outer_fence(text: str) -> str:
    """Remove one model-added Markdown/YAML fence only when it wraps the entire response."""
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return text
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    last = next((index for index in range(len(lines) - 1, -1, -1) if lines[index].strip()), None)
    if first is None or last is None or first >= last:
        return text
    opening = _OUTER_FENCE_RE.match(lines[first])
    if not opening:
        return text
    closing_text = lines[last].strip()
    if not re.fullmatch(rf"{re.escape(opening.group(1)[0])}{{{len(opening.group(1))},}}", closing_text):
        return text
    if any(line.strip() for line in lines[:first]) or any(line.strip() for line in lines[last + 1 :]):
        return text
    return "".join(lines[first + 1 : last])
