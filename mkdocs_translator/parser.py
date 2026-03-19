import re
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Paragraph:
    content_hash: str
    full_hash: str
    content: str
    paragraph_type: str


CODE_BLOCK_PATTERN = re.compile(r'^(`{3,}|~{3,})[\s\S]*?\1', re.MULTILINE)
ADMONITION_PATTERN = re.compile(r'^(!{3,4}|\?{3,4})\s*\w+.*?(?=\n!{3,4}|\n\?{3,4}|\Z)', re.MULTILINE | re.DOTALL)
TABLE_PATTERN = re.compile(r'^(?:\|.+\|[\s]*\n?)+', re.MULTILINE)
FRONTMATTER_PATTERN = re.compile(r'^---\n[\s\S]*?\n---\n', re.MULTILINE)


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


def extract_all_blocks(content: str) -> List[tuple]:
    blocks = []
    search_start = 0

    while True:
        code_match = CODE_BLOCK_PATTERN.search(content, search_start)
        admonition_match = ADMONITION_PATTERN.search(content, search_start)
        frontmatter_match = FRONTMATTER_PATTERN.search(content, search_start)

        candidates = []
        if code_match:
            candidates.append((code_match.start(), 'code', code_match))
        if admonition_match:
            candidates.append((admonition_match.start(), 'admonition', admonition_match))
        if frontmatter_match:
            candidates.append((frontmatter_match.start(), 'frontmatter', frontmatter_match))

        if not candidates:
            break

        candidates.sort(key=lambda x: x[0])
        earliest_pos, earliest_type, earliest_match = candidates[0]

        block_text = earliest_match.group(0)
        blocks.append((earliest_type, block_text, earliest_pos))
        search_start = earliest_pos + len(block_text)

    return blocks


def parse_content(content: str) -> List[Paragraph]:
    paragraphs = []

    extracted_blocks = extract_all_blocks(content)

    if extracted_blocks:
        parts = []
        last_end = 0
        for block_type, block_text, pos in extracted_blocks:
            if pos > last_end:
                text_part = content[last_end:pos]
                if text_part.strip():
                    parts.append(('text', text_part))
            parts.append((block_type, block_text))
            last_end = pos + len(block_text)
        if last_end < len(content):
            text_part = content[last_end:]
            if text_part.strip():
                parts.append(('text', text_part))
    else:
        parts = [('text', content)]

    logger.debug(f"[parse_content] Total parts after extraction: {len(parts)}")
    for idx, (part_type, part_content) in enumerate(parts):
        logger.debug(f"[parse_content] Part {idx}: type={part_type}, length={len(part_content)}")

    for part_type, part_content in parts:
        if part_type != 'text':
            content_hash, full_hash = compute_hash(part_content)
            paragraphs.append(Paragraph(
                content_hash=content_hash,
                full_hash=full_hash,
                content=part_content,
                paragraph_type=part_type
            ))
            logger.debug(f"[parse_content] Added {part_type} block: hash={content_hash}, length={len(part_content)}")
        else:
            text_paragraphs = split_text_paragraphs(part_content)
            logger.debug(f"[parse_content] Split into {len(text_paragraphs)} text paragraphs before merge")
            text_paragraphs = merge_short_paragraphs(text_paragraphs)
            logger.debug(f"[parse_content] After merge: {len(text_paragraphs)} text paragraphs")
            for para_idx, para_text in enumerate(text_paragraphs):
                if para_text.strip():
                    content_hash, full_hash = compute_hash(para_text)
                    paragraphs.append(Paragraph(
                        content_hash=content_hash,
                        full_hash=full_hash,
                        content=para_text,
                        paragraph_type='normal'
                    ))
                    logger.debug(f"[parse_content] Added text paragraph {para_idx}: hash={content_hash}, length={len(para_text)}, preview={para_text[:50]!r}...")

    logger.debug(f"[parse_content] Total paragraphs: {len(paragraphs)}")
    return paragraphs


def split_text_paragraphs(text: str) -> List[str]:
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    parts = normalized.split('\n\n')
    return [p + '\n' if p.endswith('\n') else p for p in parts if p.strip()]


def merge_short_paragraphs(paragraphs: List[str], min_length: int = 200) -> List[str]:
    if not paragraphs:
        return []
    
    logger.debug(f"[merge_short_paragraphs] Input: {len(paragraphs)} paragraphs, min_length={min_length}")
    for idx, p in enumerate(paragraphs):
        logger.debug(f"[merge_short_paragraphs] Before merge [{idx}]: length={len(p)}, preview={p[:50]!r}...")
    
    merged = []
    i = 0
    
    while i < len(paragraphs):
        current_para = paragraphs[i]
        merge_count = 0
        
        while len(current_para) < min_length and i + 1 < len(paragraphs):
            i += 1
            current_para = current_para.rstrip('\n') + '\n\n' + paragraphs[i]
            merge_count += 1
        
        if merge_count > 0:
            logger.debug(f"[merge_short_paragraphs] Merged {merge_count + 1} paragraphs into one, final length={len(current_para)}")
        merged.append(current_para)
        i += 1
    
    logger.debug(f"[merge_short_paragraphs] Output: {len(merged)} paragraphs")
    return merged


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