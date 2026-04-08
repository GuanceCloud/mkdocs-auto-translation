import re
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Paragraph:
    content_hash: str
    full_hash: str
    content: str
    paragraph_type: str


@dataclass
class PlannedMergeUnit:
    hashes: List[str]
    merged_content: str
    translation: str
    need_translate: bool


CODE_BLOCK_PATTERN = re.compile(r'^(`{3,}|~{3,})[\s\S]*?\1', re.MULTILINE)
ADMONITION_PATTERN = re.compile(r'^(!{3,4}|\?{3,4})\s*\w+.*?(?=\n!{3,4}|\n\?{3,4}|\Z)', re.MULTILINE | re.DOTALL)
TABLE_PATTERN = re.compile(r'^\s*\|.*\|\s*$')
TABLE_DELIMITER_PATTERN = re.compile(r'^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$')
FRONTMATTER_PATTERN = re.compile(r'^---\n[\s\S]*?\n---\n?', re.MULTILINE)
FENCE_START_PATTERN = re.compile(r'^(\s*)(`{3,}|~{3,})(.*)$')
ADMONITION_START_PATTERN = re.compile(r'^\s*(!{3,4}|\?{3,4})\s+\S+.*$')
ATX_HEADING_PATTERN = re.compile(r'^\s{0,3}#{1,6}\s+')
SETEXT_UNDERLINE_PATTERN = re.compile(r'^\s{0,3}(=+|-+)\s*$')
BLOCKQUOTE_PATTERN = re.compile(r'^\s{0,3}>')
UNORDERED_LIST_PATTERN = re.compile(r'^\s{0,3}[-+*]\s+')
ORDERED_LIST_PATTERN = re.compile(r'^\s{0,3}\d+[.)]\s+')
THEMATIC_BREAK_PATTERN = re.compile(r'^\s{0,3}(?:\*\s*){3,}$|^\s{0,3}(?:-\s*){3,}$|^\s{0,3}(?:_\s*){3,}$')


def compute_hash(content: str) -> tuple:
    full_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    return full_hash[:6], full_hash


def is_code_block(text: str) -> bool:
    return bool(CODE_BLOCK_PATTERN.match(text))


def is_admonition(text: str) -> bool:
    return bool(ADMONITION_PATTERN.match(text))


def is_table(text: str) -> bool:
    lines = text.strip().split('\n')
    if not lines:
        return False
    first_line = lines[0].strip()
    if not first_line.startswith('|'):
        return False
    col_count = first_line.count('|')
    if col_count < 2:
        return False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if not line.startswith('|') or line.count('|') != col_count:
            return False
        if set(line.replace('|', '').replace('-', '').replace(':', '').replace(' ', '')):
            return False
    return True


def is_frontmatter(text: str) -> bool:
    return bool(FRONTMATTER_PATTERN.match(text))


def _join_lines(lines: List[str]) -> str:
    return "\n".join(lines).rstrip("\n")


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_table_start(lines: List[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return bool(TABLE_PATTERN.match(lines[index]) and TABLE_DELIMITER_PATTERN.match(lines[index + 1]))


def _is_list_start(line: str) -> bool:
    return bool(UNORDERED_LIST_PATTERN.match(line) or ORDERED_LIST_PATTERN.match(line))


def _is_indented_continuation(line: str) -> bool:
    if _is_blank(line):
        return True
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    return indent >= 2


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
                closing = lines[j]
                if closing.startswith(indent + fence[0] * len(fence)):
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
    paragraphs = []

    parts = split_markdown_blocks(content)

    logger.debug(f"[parse_content] Total blocks after markdown split: {len(parts)}")
    for idx, (part_type, part_content) in enumerate(parts):
        logger.debug(f"[parse_content] Part {idx}: type={part_type}, length={len(part_content)}")

    for part_type, part_content in parts:
        content_hash, full_hash = compute_hash(part_content)
        paragraphs.append(Paragraph(
            content_hash=content_hash,
            full_hash=full_hash,
            content=part_content,
            paragraph_type=part_type
        ))
        logger.debug(f"[parse_content] Added {part_type} block: hash={content_hash}, length={len(part_content)}")

    logger.debug(f"[parse_content] Total paragraphs: {len(paragraphs)}")
    return paragraphs


def split_text_paragraphs(text: str) -> List[str]:
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    parts = normalized.split('\n\n')
    return [p + '\n' if p.endswith('\n') else p for p in parts if p.strip()]


def compute_doc_hash(paragraphs: List[Paragraph]) -> str:
    combined = ''.join(p.content for p in paragraphs)
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


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


def plan_merge_units(
    paragraphs: List[Paragraph],
    old_merge_units: List[Any],
    min_length: int = 200
) -> List[PlannedMergeUnit]:
    """
    Plan merge units for translation.
    
    Strategy:
    1. If all paragraphs in an old merge_unit still exist consecutively, reuse it
    2. Otherwise, greedily merge paragraphs until reaching min_length
    3. Stop merging if next paragraph can reuse an old merge_unit
    
    Args:
        paragraphs: List of Paragraph objects from current document
        old_merge_units: List of old MergeUnit objects from cache
        min_length: Minimum character count for merging (default 200)
        
    Returns:
        List of PlannedMergeUnit objects
    """
    if not paragraphs:
        return []
    
    para_hashes = [p.content_hash for p in paragraphs]
    
    old_merge_map: Dict[str, Any] = {}
    for mu in old_merge_units:
        for h in mu.hashes:
            old_merge_map[h] = mu
    
    def can_reuse_merge_unit(start_idx: int, merge_unit: Any) -> bool:
        """Check if merge_unit can be reused starting from start_idx (consecutive match)"""
        if start_idx + len(merge_unit.hashes) > len(para_hashes):
            return False
        for offset, h in enumerate(merge_unit.hashes):
            if para_hashes[start_idx + offset] != h:
                return False
        return True
    
    planned_units: List[PlannedMergeUnit] = []
    i = 0
    
    while i < len(paragraphs):
        para = paragraphs[i]
        para_hash = para.content_hash

        if para.paragraph_type != 'normal':
            planned_units.append(PlannedMergeUnit(
                hashes=[para_hash],
                merged_content=para.content,
                translation="",
                need_translate=True
            ))
            logger.debug(f"[plan_merge_units] Structural unit kept standalone: {para.paragraph_type}, hash={para_hash}")
            i += 1
            continue

        if para_hash in old_merge_map:
            old_mu = old_merge_map[para_hash]
            if can_reuse_merge_unit(i, old_mu) and all(
                paragraphs[i + offset].paragraph_type == 'normal'
                for offset in range(len(old_mu.hashes))
            ):
                planned_units.append(PlannedMergeUnit(
                    hashes=old_mu.hashes.copy(),
                    merged_content="",
                    translation=old_mu.translation,
                    need_translate=False
                ))
                i += len(old_mu.hashes)
                logger.debug(f"[plan_merge_units] Reused merge_unit: {old_mu.hashes}")
                continue
        
        merged_hashes = [para_hash]
        merged_content = para.content
        j = i + 1
        
        while j < len(paragraphs) and len(merged_content) < min_length:
            next_para = paragraphs[j]
            next_hash = next_para.content_hash

            if next_para.paragraph_type != 'normal':
                break
            
            if next_hash in old_merge_map:
                old_mu = old_merge_map[next_hash]
                if can_reuse_merge_unit(j, old_mu) and all(
                    paragraphs[j + offset].paragraph_type == 'normal'
                    for offset in range(len(old_mu.hashes))
                ):
                    logger.debug(f"[plan_merge_units] Stop merge at {j}, next can reuse old merge_unit")
                    break
            
            merged_hashes.append(next_hash)
            merged_content += "\n\n" + next_para.content
            j += 1
        
        planned_units.append(PlannedMergeUnit(
            hashes=merged_hashes,
            merged_content=merged_content,
            translation="",
            need_translate=True
        ))
        logger.debug(f"[plan_merge_units] New merge_unit: {merged_hashes}, length={len(merged_content)}")
        i = j
    
    logger.debug(f"[plan_merge_units] Total planned units: {len(planned_units)}, need translate: {sum(1 for u in planned_units if u.need_translate)}")
    return planned_units


def assemble_translation(planned_units: List[PlannedMergeUnit]) -> str:
    """
    Assemble final translation from planned merge units.
    """
    return "\n\n".join(mu.translation for mu in planned_units if mu.translation)
