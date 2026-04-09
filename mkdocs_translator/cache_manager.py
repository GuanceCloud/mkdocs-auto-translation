import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class CachedBlock:
    short_hash: str
    block_type: str
    content: str
    section_path: List[str] = field(default_factory=list)


@dataclass
class TranslationUnit:
    unit_id: str
    unit_type: str
    block_hashes: List[str]
    source_hash: str
    context_signature: str
    section_path: List[str]
    translation: str


@dataclass
class CacheData:
    version: int = 3
    source_doc_hash: str = ""
    last_translated: str = ""
    blocks: Dict[str, CachedBlock] = field(default_factory=dict)
    translation_units: List[TranslationUnit] = field(default_factory=list)
    translation_memory: List[Dict[str, str]] = field(default_factory=list)


class CacheManager:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self.cache_dir = target_dir / '.translation-cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, source_rel_path: Path) -> Path:
        cache_path = self.cache_dir / f"{source_rel_path}.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        return cache_path

    def load_cache(self, source_rel_path: Path) -> Optional[CacheData]:
        cache_path = self._get_cache_path(source_rel_path)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cache_data = CacheData(
                version=data.get('version', 3),
                source_doc_hash=data.get('source_doc_hash', ''),
                last_translated=data.get('last_translated', ''),
                translation_memory=data.get('translation_memory', [])
            )

            for full_hash, block_data in data.get('blocks', {}).items():
                block = CachedBlock(
                    short_hash=block_data.get('short_hash', ''),
                    block_type=block_data.get('block_type', 'normal'),
                    content=block_data.get('content', ''),
                    section_path=block_data.get('section_path', [])
                )
                cache_key = full_hash or block_data.get('full_hash', '')
                if cache_key:
                    cache_data.blocks[cache_key] = block

            for unit_data in data.get('translation_units', []):
                cache_data.translation_units.append(TranslationUnit(
                    unit_id=unit_data.get('unit_id', ''),
                    unit_type=unit_data.get('unit_type', 'section_unit'),
                    block_hashes=unit_data.get('block_hashes', []),
                    source_hash=unit_data.get('source_hash', ''),
                    context_signature=unit_data.get('context_signature', ''),
                    section_path=unit_data.get('section_path', []),
                    translation=unit_data.get('translation', '')
                ))

            return cache_data
        except (json.JSONDecodeError, IOError):
            return None

    def save_cache(self, source_rel_path: Path, cache_data: CacheData):
        cache_path = self._get_cache_path(source_rel_path)

        data = {
            'version': cache_data.version,
            'source_doc_hash': cache_data.source_doc_hash,
            'last_translated': cache_data.last_translated,
            'translation_memory': cache_data.translation_memory,
            'blocks': {},
            'translation_units': []
        }

        for full_hash, block in cache_data.blocks.items():
            data['blocks'][full_hash] = {
                'short_hash': block.short_hash,
                'block_type': block.block_type,
                'content': block.content,
                'section_path': block.section_path
            }

        for unit in cache_data.translation_units:
            data['translation_units'].append({
                'unit_id': unit.unit_id,
                'unit_type': unit.unit_type,
                'block_hashes': unit.block_hashes,
                'source_hash': unit.source_hash,
                'context_signature': unit.context_signature,
                'section_path': unit.section_path,
                'translation': unit.translation
            })

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def replace_blocks(self, cache_data: CacheData, blocks: List[CachedBlock]):
        cache_data.blocks = {}
        for block in blocks:
            block_hash = _compute_block_full_hash(block.content)
            cache_data.blocks[block_hash] = block

    def replace_translation_units(self, cache_data: CacheData, units: List[TranslationUnit]):
        cache_data.translation_units = units

    def find_translation_unit(
        self,
        cache_data: CacheData,
        source_hash: str,
        context_signature: str
    ) -> Optional[TranslationUnit]:
        for unit in cache_data.translation_units:
            if unit.source_hash == source_hash and unit.context_signature == context_signature:
                return unit
        return None

    def update_translation_memory(
        self,
        cache_data: CacheData,
        source: str,
        translation: str
    ):
        for entry in cache_data.translation_memory:
            if entry.get('source') == source:
                return

        cache_data.translation_memory.append({
            'source': source,
            'translation': translation,
            'first_seen': datetime.now().strftime('%Y-%m-%d')
        })

    def extract_and_update_memory(
        self,
        cache_data: CacheData,
        source_content: str,
        translation: str
    ):
        english_terms = extract_english_terms(source_content, translation)
        for source, trans in english_terms:
            self.update_translation_memory(cache_data, source, trans)


def compute_similarity(s1: str, s2: str) -> float:
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    max_len = max(len1, len2)

    if max_len == 0:
        return 1.0

    distance = levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)


def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def extract_english_terms(source: str, translation: str) -> List[Tuple[str, str]]:
    import re

    terms = []

    camel_pattern = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b')
    for match in camel_pattern.finditer(translation):
        term = match.group(1)
        if len(term) >= 3:
            terms.append((term, term))

    acronym_pattern = re.compile(r'\b([A-Z]{2,})\b')
    for match in acronym_pattern.finditer(translation):
        term = match.group(1)
        if term not in ['API', 'SDK', 'HTTP', 'URL', 'JSON', 'XML', 'HTML', 'SQL', 'SSH']:
            terms.append((term, term))

    return terms


def _compute_block_full_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode('utf-8')).hexdigest()
