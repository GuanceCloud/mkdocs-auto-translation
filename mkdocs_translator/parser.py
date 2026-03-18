import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


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

    for part_type, part_content in parts:
        if part_type != 'text':
            content_hash, full_hash = compute_hash(part_content)
            paragraphs.append(Paragraph(
                content_hash=content_hash,
                full_hash=full_hash,
                content=part_content,
                paragraph_type=part_type
            ))
        else:
            text_paragraphs = split_text_paragraphs(part_content)
            for para_text in text_paragraphs:
                if para_text.strip():
                    content_hash, full_hash = compute_hash(para_text)
                    paragraphs.append(Paragraph(
                        content_hash=content_hash,
                        full_hash=full_hash,
                        content=para_text,
                        paragraph_type='normal'
                    ))

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