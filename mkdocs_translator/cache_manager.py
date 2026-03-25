import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ParagraphCache:
    content: str


@dataclass
class MergeUnit:
    hashes: List[str]
    translation: str


@dataclass
class CacheData:
    version: int = 2
    source_doc_hash: str = ""
    last_translated: str = ""
    paragraphs: Dict[str, ParagraphCache] = field(default_factory=dict)
    merge_units: List[MergeUnit] = field(default_factory=list)
    translation_memory: List[Dict[str, str]] = field(default_factory=list)


class CacheManager:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self.cache_dir = target_dir / '.translation-cache'
        if not self.cache_dir.exists():
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
                version=data.get('version', 2),
                source_doc_hash=data.get('source_doc_hash', ''),
                last_translated=data.get('last_translated', ''),
                translation_memory=data.get('translation_memory', [])
            )

            for hash_key, para_data in data.get('paragraphs', {}).items():
                cache_data.paragraphs[hash_key] = ParagraphCache(
                    content=para_data.get('content', '')
                )

            for mu_data in data.get('merge_units', []):
                cache_data.merge_units.append(MergeUnit(
                    hashes=mu_data.get('hashes', []),
                    translation=mu_data.get('translation', '')
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
            'paragraphs': {},
            'merge_units': []
        }

        for hash_key, para_cache in cache_data.paragraphs.items():
            data['paragraphs'][hash_key] = {
                'content': para_cache.content
            }

        for mu in cache_data.merge_units:
            data['merge_units'].append({
                'hashes': mu.hashes,
                'translation': mu.translation
            })

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def cleanup_stale_cache(self, cache_data: CacheData, current_paragraph_hashes: List[str]) -> int:
        """
        Remove cached paragraphs and merge_units that no longer exist in the current document.
        
        Args:
            cache_data: The cache data to clean up
            current_paragraph_hashes: List of paragraph hashes from the current document
            
        Returns:
            Number of removed items
        """
        current_hash_set = set(current_paragraph_hashes)
        removed_count = 0
        
        stale_hashes = [h for h in cache_data.paragraphs.keys() if h not in current_hash_set]
        for stale_hash in stale_hashes:
            del cache_data.paragraphs[stale_hash]
            removed_count += 1
        
        cache_data.merge_units = [
            mu for mu in cache_data.merge_units
            if all(h in current_hash_set for h in mu.hashes)
        ]
        
        return removed_count

    def get_paragraph_content(self, cache_data: CacheData, para_hash: str) -> Optional[str]:
        if para_hash in cache_data.paragraphs:
            return cache_data.paragraphs[para_hash].content
        return None

    def find_merge_unit_by_hash(self, cache_data: CacheData, para_hash: str) -> Optional[MergeUnit]:
        for mu in cache_data.merge_units:
            if para_hash in mu.hashes:
                return mu
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