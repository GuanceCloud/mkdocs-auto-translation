import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .cache_manager import CachedBlock, TranslationUnit

logger = logging.getLogger(__name__)


@dataclass
class Paragraph:
    content_hash: str
    full_hash: str
    content: str
    paragraph_type: str


@dataclass
class PlannedTranslationUnit:
    unit_id: str
    unit_type: str
    block_hashes: List[str]
    source_hash: str
    context_signature: str
    section_path: List[str]
    source_text: str
    translation: str
    need_translate: bool
    context_before: str = ""
    context_after: str = ""


@dataclass
class BlockWithContext:
    paragraph: Paragraph
    section_path: List[str] = field(default_factory=list)


TABLE_PATTERN = re.compile(r'^\s*\|.*\|\s*$')
TABLE_DELIMITER_PATTERN = re.compile(r'^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$')
FRONTMATTER_PATTERN = re.compile(r'^---\n[\s\S]*?\n---\n?', re.MULTILINE)
FENCE_START_PATTERN = re.compile(r'^(\s*)(`{3,}|~{3,})(.*)$')
ADMONITION_START_PATTERN = re.compile(r'^\s*(!{3,4}|\?{3,4})\s+\S+.*$')
ATX_HEADING_PATTERN = re.compile(r'^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#*\s*)?$')
SETEXT_UNDERLINE_PATTERN = re.compile(r'^\s{0,3}(=+|-+)\s*$')
BLOCKQUOTE_PATTERN = re.compile(r'^\s{0,3}>')
UNORDERED_LIST_PATTERN = re.compile(r'^\s{0,3}[-+*]\s+')
ORDERED_LIST_PATTERN = re.compile(r'^\s{0,3}\d+[.)]\s+')
THEMATIC_BREAK_PATTERN = re.compile(r'^\s{0,3}(?:\*\s*){3,}$|^\s{0,3}(?:-\s*){3,}$|^\s{0,3}(?:_\s*){3,}$')

STANDALONE_UNIT_TYPES = {'frontmatter', 'pages', 'code', 'thematic_break'}
COMPANION_BLOCK_TYPES = {'list', 'table', 'blockquote', 'admonition'}
BODY_BLOCK_TYPES = {'normal', 'list', 'table', 'blockquote', 'admonition', 'code', 'thematic_break'}


def compute_hash(content: str) -> tuple:
    full_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    return full_hash[:6], full_hash


def compute_doc_hash(paragraphs: List[Paragraph]) -> str:
    combined = ''.join(p.content for p in paragraphs)
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def _join_lines(lines: List[str]) -> str:
    return "\n".join(lines).rstrip("\n")


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_table_start(lines: List[str], index: int) -> bool:
    return index + 1 < len(lines) and bool(
        TABLE_PATTERN.match(lines[index]) and TABLE_DELIMITER_PATTERN.match(lines[index + 1])
    )


def _is_list_start(line: str) -> bool:
    return bool(UNORDERED_LIST_PATTERN.match(line) or ORDERED_LIST_PATTERN.match(line))


def _is_indented_continuation(line: str) -> bool:
    if _is_blank(line):
        return True
    stripped = line.lstrip()
    return len(line) - len(stripped) >= 2


def split_markdown_blocks(content: str) -> List[Tuple[str, str]]:
    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    if not normalized.strip():
        return []

    blocks: List[Tuple[str, str]] = []
    lines = normalized.split('\n')
    total = len(lines)
    i = 0

    if normalized.startswith('---\n'):
        end = 1
        while end < total:
            if lines[end].strip() == '---':
                blocks.append(('frontmatter', _join_lines(lines[:end + 1])))
                i = end + 1
                while i < total and _is_blank(lines[i]):
                    i += 1
                break
            end += 1

    while i < total:
        if _is_blank(lines[i]):
            i += 1
            continue

        line = lines[i]
        fence_match = FENCE_START_PATTERN.match(line)
        if fence_match:
            indent, fence, _ = fence_match.groups()
            j = i + 1
            while j < total:
                if lines[j].startswith(indent + fence[0] * len(fence)):
                    j += 1
                    break
                j += 1
            blocks.append(('code', _join_lines(lines[i:j])))
            i = j
            continue

        if ADMONITION_START_PATTERN.match(line):
            j = i + 1
            while j < total:
                current = lines[j]
                if _is_blank(current):
                    j += 1
                    continue
                if current.startswith('    ') or current.startswith('\t'):
                    j += 1
                    continue
                break
            blocks.append(('admonition', _join_lines(lines[i:j])))
            i = j
            continue

        if _is_table_start(lines, i):
            j = i + 2
            while j < total and TABLE_PATTERN.match(lines[j]):
                j += 1
            blocks.append(('table', _join_lines(lines[i:j])))
            i = j
            continue

        if ATX_HEADING_PATTERN.match(line):
            blocks.append(('heading', line.rstrip()))
            i += 1
            continue

        if i + 1 < total and lines[i].strip() and SETEXT_UNDERLINE_PATTERN.match(lines[i + 1]):
            blocks.append(('heading', _join_lines(lines[i:i + 2])))
            i += 2
            continue

        if THEMATIC_BREAK_PATTERN.match(line):
            blocks.append(('thematic_break', line.rstrip()))
            i += 1
            continue

        if BLOCKQUOTE_PATTERN.match(line):
            j = i + 1
            while j < total and (BLOCKQUOTE_PATTERN.match(lines[j]) or _is_blank(lines[j])):
                j += 1
            blocks.append(('blockquote', _join_lines(lines[i:j])))
            i = j
            continue

        if _is_list_start(line):
            j = i + 1
            while j < total:
                current = lines[j]
                if _is_blank(current):
                    if j + 1 < total and (_is_list_start(lines[j + 1]) or _is_indented_continuation(lines[j + 1])):
                        j += 1
                        continue
                    break
                if _is_list_start(current) or _is_indented_continuation(current):
                    j += 1
                    continue
                break
            blocks.append(('list', _join_lines(lines[i:j])))
            i = j
            continue

        j = i + 1
        while j < total:
            current = lines[j]
            if _is_blank(current):
                break
            if (
                FENCE_START_PATTERN.match(current)
                or ADMONITION_START_PATTERN.match(current)
                or _is_table_start(lines, j)
                or ATX_HEADING_PATTERN.match(current)
                or (j + 1 < total and lines[j].strip() and SETEXT_UNDERLINE_PATTERN.match(lines[j + 1]))
                or THEMATIC_BREAK_PATTERN.match(current)
                or BLOCKQUOTE_PATTERN.match(current)
                or _is_list_start(current)
            ):
                break
            j += 1
        blocks.append(('normal', _join_lines(lines[i:j])))
        i = j

    return blocks


def parse_content(content: str) -> List[Paragraph]:
    paragraphs: List[Paragraph] = []
    for part_type, part_content in split_markdown_blocks(content):
        content_hash, full_hash = compute_hash(part_content)
        paragraphs.append(Paragraph(
            content_hash=content_hash,
            full_hash=full_hash,
            content=part_content,
            paragraph_type=part_type
        ))
    return paragraphs


def split_text_paragraphs(text: str) -> List[str]:
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    parts = normalized.split('\n\n')
    return [p + '\n' if p.endswith('\n') else p for p in parts if p.strip()]


def parse_file(file_path: Path) -> List[Paragraph]:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return parse_content(content)


def is_pages_file(file_path: Path) -> bool:
    return file_path.name == '.pages'


def parse_file_incremental(file_path: Path, is_pages: bool = False) -> List[Paragraph]:
    if is_pages or is_pages_file(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content_hash, full_hash = compute_hash(content)
        return [Paragraph(
            content_hash=content_hash,
            full_hash=full_hash,
            content=content,
            paragraph_type='pages'
        )]
    return parse_file(file_path)


def extract_heading_text(content: str) -> str:
    lines = content.split('\n')
    match = ATX_HEADING_PATTERN.match(lines[0])
    if match:
        return match.group(2).strip()
    if len(lines) >= 2 and SETEXT_UNDERLINE_PATTERN.match(lines[1]):
        return lines[0].strip()
    return content.strip()


def get_heading_level(paragraph: Paragraph) -> Optional[int]:
    if paragraph.paragraph_type != 'heading':
        return None
    lines = paragraph.content.split('\n')
    match = ATX_HEADING_PATTERN.match(lines[0])
    if match:
        return len(match.group(1))
    if len(lines) >= 2 and SETEXT_UNDERLINE_PATTERN.match(lines[1]):
        return 1 if lines[1].lstrip().startswith('=') else 2
    return None


def annotate_sections(paragraphs: List[Paragraph]) -> List[BlockWithContext]:
    annotated: List[BlockWithContext] = []
    heading_stack: List[Tuple[int, str]] = []

    for paragraph in paragraphs:
        if paragraph.paragraph_type == 'heading':
            level = get_heading_level(paragraph) or 1
            heading_text = extract_heading_text(paragraph.content)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
            section_path = [title for _, title in heading_stack]
        else:
            section_path = [title for _, title in heading_stack]

        annotated.append(BlockWithContext(paragraph=paragraph, section_path=section_path))

    return annotated


def build_cached_blocks(paragraphs: List[Paragraph]) -> List[CachedBlock]:
    blocks = []
    for block in annotate_sections(paragraphs):
        para = block.paragraph
        blocks.append(CachedBlock(
            short_hash=para.content_hash,
            block_type=para.paragraph_type,
            content=para.content,
            section_path=block.section_path
        ))
    return blocks


def _hash_string(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _make_context_signature(section_path: List[str], unit_type: str) -> str:
    return _hash_string(f"{unit_type}||{' > '.join(section_path)}")


def _combine_unit_hash(blocks: List[BlockWithContext], unit_type: str, section_path: List[str]) -> str:
    payload = "||".join([unit_type, *section_path, *(block.paragraph.full_hash for block in blocks)])
    return _hash_string(payload)


def _make_unit_id(blocks: List[BlockWithContext], unit_type: str, section_path: List[str]) -> str:
    payload = "|".join([unit_type, "/".join(section_path), *(block.paragraph.content_hash for block in blocks)])
    return _hash_string(payload)[:12]


def _serialize_blocks(blocks: List[BlockWithContext]) -> str:
    return "\n\n".join(block.paragraph.content for block in blocks if block.paragraph.content)


def _snippet(text: str, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit]


def _build_semantic_groups(blocks: List[BlockWithContext]) -> List[List[BlockWithContext]]:
    groups: List[List[BlockWithContext]] = []
    i = 0
    while i < len(blocks):
        current = blocks[i]
        block_type = current.paragraph.paragraph_type

        if block_type in STANDALONE_UNIT_TYPES:
            groups.append([current])
            i += 1
            continue

        if (
            block_type == 'normal'
            and i + 1 < len(blocks)
            and blocks[i + 1].paragraph.paragraph_type in COMPANION_BLOCK_TYPES
            and len(current.paragraph.content) <= 260
        ):
            groups.append([current, blocks[i + 1]])
            i += 2
            continue

        groups.append([current])
        i += 1

    return groups


def _split_into_sections(blocks: List[BlockWithContext]) -> List[List[BlockWithContext]]:
    sections: List[List[BlockWithContext]] = []
    current: List[BlockWithContext] = []

    for block in blocks:
        if block.paragraph.paragraph_type == 'heading':
            if current:
                sections.append(current)
            current = [block]
            continue

        if not current:
            current = [block]
        else:
            current.append(block)

    if current:
        sections.append(current)

    return sections


def _plan_units_for_section(
    section_blocks: List[BlockWithContext],
    old_units: Dict[Tuple[str, str], TranslationUnit],
    preferred_chars: int,
    max_chars: int
) -> List[PlannedTranslationUnit]:
    groups = _build_semantic_groups(section_blocks)
    planned: List[PlannedTranslationUnit] = []
    current_groups: List[List[BlockWithContext]] = []

    def flush_current():
        nonlocal current_groups
        if not current_groups:
            return
        flat_blocks = [block for group in current_groups for block in group]
        _append_planned_unit(planned, flat_blocks, old_units)
        current_groups = []

    for group in groups:
        group_blocks = [block for block in group]
        group_text = _serialize_blocks(group_blocks)
        group_types = {block.paragraph.paragraph_type for block in group_blocks}

        if group_types & STANDALONE_UNIT_TYPES:
            flush_current()
            _append_planned_unit(planned, group_blocks, old_units)
            continue

        current_text = _serialize_blocks([block for pending in current_groups for block in pending])

        if not current_groups:
            current_groups = [group]
            continue

        if len(current_text) >= preferred_chars:
            flush_current()
            current_groups = [group]
            continue

        combined_text = "\n\n".join(filter(None, [current_text, group_text]))
        if len(combined_text) > max_chars:
            flush_current()
            current_groups = [group]
            continue

        current_groups.append(group)

    flush_current()
    return planned


def _append_planned_unit(
    planned: List[PlannedTranslationUnit],
    blocks: List[BlockWithContext],
    old_units: Dict[Tuple[str, str], TranslationUnit]
):
    if not blocks:
        return

    section_path = blocks[0].section_path
    block_hashes = [block.paragraph.full_hash for block in blocks]
    unit_type = _derive_unit_type(blocks)
    source_text = _serialize_blocks(blocks)
    source_hash = _combine_unit_hash(blocks, unit_type, section_path)
    context_signature = _make_context_signature(section_path, unit_type)
    cached = old_units.get((source_hash, context_signature))

    planned.append(PlannedTranslationUnit(
        unit_id=_make_unit_id(blocks, unit_type, section_path),
        unit_type=unit_type,
        block_hashes=block_hashes,
        source_hash=source_hash,
        context_signature=context_signature,
        section_path=section_path,
        source_text=source_text,
        translation=cached.translation if cached else "",
        need_translate=cached is None
    ))


def _derive_unit_type(blocks: List[BlockWithContext]) -> str:
    block_types = [block.paragraph.paragraph_type for block in blocks]
    if block_types == ['heading']:
        return 'heading_only'
    if block_types and block_types[0] == 'heading':
        return 'section_opening'
    if any(block_type == 'code' for block_type in block_types):
        return 'code_block'
    if any(block_type == 'table' for block_type in block_types):
        return 'table_block'
    if any(block_type == 'list' for block_type in block_types):
        return 'list_block'
    return 'section_unit'


def _apply_adjacent_context(planned_units: List[PlannedTranslationUnit]):
    for index, unit in enumerate(planned_units):
        unit.context_before = _snippet(planned_units[index - 1].source_text) if index > 0 else ""
        unit.context_after = _snippet(planned_units[index + 1].source_text) if index + 1 < len(planned_units) else ""


def plan_translation_units(
    paragraphs: List[Paragraph],
    old_translation_units: List[TranslationUnit],
    preferred_chars: int = 900,
    max_chars: int = 1600
) -> List[PlannedTranslationUnit]:
    if not paragraphs:
        return []

    annotated = annotate_sections(paragraphs)
    old_lookup = {
        (unit.source_hash, unit.context_signature): unit
        for unit in old_translation_units
    }

    planned: List[PlannedTranslationUnit] = []
    for section in _split_into_sections(annotated):
        planned.extend(_plan_units_for_section(section, old_lookup, preferred_chars, max_chars))

    _apply_adjacent_context(planned)
    return planned


def assemble_translation(planned_units: List[PlannedTranslationUnit]) -> str:
    return "\n\n".join(unit.translation for unit in planned_units if unit.translation)
