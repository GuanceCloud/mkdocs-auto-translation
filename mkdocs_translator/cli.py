import click
from pathlib import Path
from typing import Optional, List, Tuple, Dict
import logging
from datetime import datetime
from .translator import DocumentTranslator
from .utils import get_translatable_files, copy_resources, load_blacklist
from .parser import parse_file_incremental, compute_doc_hash, is_pages_file, plan_merge_units, assemble_translation, PlannedMergeUnit
from .cache_manager import CacheManager, CacheData, MergeUnit
from tqdm import tqdm
import concurrent.futures
from functools import partial
from fnmatch import fnmatch
import threading

_worker_pbars: Dict[int, Optional[tqdm]] = {}
_pbar_lock = threading.Lock()
_completed_count = 0
_error_count = 0
logger = logging.getLogger(__name__)

@click.command()
@click.option('--source', required=True, type=click.Path(exists=True), help='The source document directory')
@click.option('--target', required=True, type=click.Path(), help='The target translation directory')
@click.option('--target-language', required=True, help='The target language code')
@click.option('--api-key', help='LLM API key (compatible with OpenAI format)')
@click.option('--base-url', help='LLM API base URL (default: https://api.openai.com/v1)')
@click.option('--model', help='Model name to use', default='gpt-4o')
@click.option('--response-mode', help='Response mode', type=click.Choice(['streaming', 'blocking']), default='streaming')
@click.option('--workers', type=int, default=1, help='Number of parallel workers')
@click.option('--overwrite-resources', is_flag=True, default=False, help='Whether to overwrite resource files in target directory')
@click.option('--delete-removed-resources', is_flag=True, default=False, help='Whether to delete resource files in target directory that no longer exist in source directory')
@click.option('--check-chinese', is_flag=True, default=False, help='Whether to check if translation results contain Chinese characters')
@click.option('--check-line-count', is_flag=True, default=False, help='Whether to check if line count difference between source and translated files exceeds 5%')
def translate(source: str, target: str,
             target_language: str, api_key: Optional[str], base_url: Optional[str], model: str,
             response_mode: str, workers: int,
             overwrite_resources: bool, delete_removed_resources: bool, check_chinese: bool, check_line_count: bool):
    """Translate MkDocs documents"""
    # set log module
    logging.basicConfig(
        filename='translation.log',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    source_path = Path(source)
    target_path = Path(target)
    blacklist_file = source_path / '.translate-blacklist'
    blacklist = load_blacklist(blacklist_file)
    
    translator = DocumentTranslator(
        target_language, 
        response_mode=response_mode, 
        api_key=api_key, 
        check_chinese=check_chinese, 
        check_line_count=check_line_count,
        base_url=base_url,
        model=model
    )
    cache_manager = CacheManager(target_path)
    
    def is_blacklisted(file_path: str, blacklist: set) -> bool:
        """
        Check if a file path matches any blacklist pattern.
        Supports:
        - Exact path match (e.g. "1.md")
        - Directory prefix match (e.g. "datakit/")
        - Wildcards: * (multiple chars), ? (single char)
        """
        if file_path in blacklist:
            return True
            
        for pattern in blacklist:
            if pattern.endswith('/') and file_path.startswith(pattern):
                return True

            if '*' in pattern or '?' in pattern:
                if fnmatch(file_path, pattern):
                    return True
                
        return False
    
    # Get files to translate
    files_to_translate = [f for f in get_translatable_files(source_path) 
                         if not is_blacklisted(str(f.relative_to(source_path)), blacklist)]

    def needs_translation(source_file: Path, cache_manager: CacheManager) -> bool:
        """
        Check if a file needs translation based on cache.
        
        Args:
            source_file: The source file path
            cache_manager: The cache manager instance
            
        Returns:
            bool: True if the file needs translation, False otherwise
        """
        relative_path = source_file.relative_to(source_path)
        cache = cache_manager.load_cache(relative_path)
        
        if cache is None:
            return True
        
        is_pages = is_pages_file(source_file)
        paragraphs = parse_file_incremental(source_file, is_pages)
        doc_hash = compute_doc_hash(paragraphs)
        
        if cache.source_doc_hash != doc_hash:
            return True
        
        return False

    files_to_translate_exclude_translated = [f for f in files_to_translate if needs_translation(f, cache_manager)]

    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)
    
    # Copy resource files
    copy_resources(source_path, target_path, overwrite_resources=overwrite_resources, delete_removed_resources=delete_removed_resources)

    def process_file_incremental(
        source_file: Path,
        translator: DocumentTranslator,
        target_path: Path,
        source_path: Path,
        cache_manager: CacheManager,
        worker_id: int,
        current_file_num: int = 1,
        total_files: int = 1
    ) -> bool:
        relative_path = source_file.relative_to(source_path)
        target_file = target_path / relative_path

        try:
            logging.info(f"开始增量翻译 - {relative_path} ({current_file_num}/{total_files})")

            is_pages = is_pages_file(source_file)
            paragraphs = parse_file_incremental(source_file, is_pages)
            doc_hash = compute_doc_hash(paragraphs)

            cache = cache_manager.load_cache(relative_path)
            if cache is None:
                cache = CacheData()

            if cache.source_doc_hash == doc_hash:
                logging.info(f"文档未变化，使用缓存 - {relative_path}")
                
                with _pbar_lock:
                    pbar = _worker_pbars.get(worker_id)
                    if pbar is None:
                        pbar = tqdm(
                            total=1,
                            desc=f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} (使用缓存)",
                            position=worker_id,
                            leave=True,
                            dynamic_ncols=True,
                            mininterval=0.5,
                            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}'
                        )
                        _worker_pbars[worker_id] = pbar
                    else:
                        pbar.reset(total=1)
                        pbar.set_description(f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} (使用缓存)")
                    pbar.update(1)
                
                _write_translation(cache.merge_units, target_file)
                return True

            planned_units = plan_merge_units(paragraphs, cache.merge_units)
            
            total_units = len(planned_units)
            need_translate_count = sum(1 for u in planned_units if u.need_translate)
            reused_count = total_units - need_translate_count
            
            cache_info = f"(复用:{reused_count}/{total_units})"
            
            with _pbar_lock:
                pbar = _worker_pbars.get(worker_id)
                if pbar is None:
                    pbar = tqdm(
                        total=need_translate_count if need_translate_count > 0 else 1,
                        desc=f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} {cache_info}",
                        position=worker_id,
                        leave=True,
                        dynamic_ncols=True,
                        mininterval=0.5,
                        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}'
                    )
                    _worker_pbars[worker_id] = pbar
                else:
                    pbar.reset(total=need_translate_count if need_translate_count > 0 else 1)
                    pbar.set_description(f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} {cache_info}")

            if need_translate_count > 0:
                cumulative_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }

                for idx, unit in enumerate(planned_units):
                    if not unit.need_translate:
                        continue
                    
                    with _pbar_lock:
                        pbar.set_description(
                            f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [u {idx+1}/{total_units}] {cache_info}"
                        )
                    
                    translation, usage_data = translator.translate_paragraph(
                        unit.merged_content,
                        translation_memory=cache.translation_memory,
                        position=worker_id,
                        desc=f"{relative_path}: merge_{idx}"
                    )
                    
                    unit.translation = translation
                    
                    cumulative_usage["prompt_tokens"] += usage_data["prompt_tokens"]
                    cumulative_usage["completion_tokens"] += usage_data["completion_tokens"]
                    cumulative_usage["total_tokens"] += usage_data["total_tokens"]
                    
                    cache_manager.extract_and_update_memory(cache, unit.merged_content, translation)
                    
                    with _pbar_lock:
                        pbar.update(1)

            cache.paragraphs.clear()
            for para in paragraphs:
                cache.paragraphs[para.content_hash] = type('ParagraphCache', (), {'content': para.content})()
            
            cache.merge_units = [
                MergeUnit(hashes=u.hashes, translation=u.translation)
                for u in planned_units
            ]
            
            cache.source_doc_hash = doc_hash
            cache.last_translated = datetime.now().isoformat()
            
            cache_manager.save_cache(relative_path, cache)
            
            _write_translation(cache.merge_units, target_file)

            logging.info(f"文件翻译成功 - {relative_path}")
            return True

        except Exception as e:
            error_message = str(e)
            logging.error(f"增量翻译文件 {relative_path} 时发生异常: {error_message}")
            print(f"翻译文件 {relative_path} 时发生错误: {error_message}")
            return False

    def _write_translation(merge_units: List[MergeUnit], target_file: Path):
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write("\n\n".join(mu.translation for mu in merge_units if mu.translation))

    # 并行执行翻译
    global _completed_count, _error_count
    _completed_count = 0
    _error_count = 0
    success_count = 0
    error_count = 0
    
    logging.info(f"开始翻译任务 - 源目录: {source_path} - 目标目录: {target_path} - 工作线程数: {workers}")
    logging.info(f"需要翻译的文件数量: {len(files_to_translate_exclude_translated)}")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # Create tasks with worker IDs
        tasks = [(file, i % workers) for i, file in enumerate(files_to_translate_exclude_translated)]
        
        # Group tasks by worker
        worker_tasks = {}
        for file, worker_id in tasks:
            if worker_id not in worker_tasks:
                worker_tasks[worker_id] = []
            worker_tasks[worker_id].append(file)
        
        # Create main progress bar for overall progress (position = workers)
        main_pbar = tqdm(
            total=len(files_to_translate_exclude_translated),
            desc="Total: 0 files | Completed: 0 | Failed: 0 | Cached: 0 paras",
            position=workers,
            unit="files",
            leave=True,
            dynamic_ncols=True
        )
        
        # Create partial function with worker task counts
        process_func = partial(
            process_file_incremental,
            translator=translator,
            target_path=target_path,
            source_path=source_path,
            cache_manager=cache_manager
        )
        
        def worker_process_files(worker_id: int, files: list, main_pbar: tqdm, total_files_count: int):
            """Worker processes its assigned files sequentially"""
            local_success = 0
            local_error = 0
            total_files = len(files)
            for current_file_num, source_file in enumerate(files, 1):
                result = False
                try:
                    result = process_func(
                        source_file=source_file, 
                        worker_id=worker_id,
                        current_file_num=current_file_num,
                        total_files=total_files
                    )
                    if result:
                        local_success += 1
                    else:
                        local_error += 1
                except Exception as e:
                    logging.error(f"Worker {worker_id} 处理文件 {source_file} 异常: {e}")
                    local_error += 1
                
                # Update total progress after each file
                with _pbar_lock:
                    global _completed_count, _error_count
                    _completed_count += 1 if result else 0
                    _error_count += 0 if result else 1
                    main_pbar.set_description(
                        f"Total: {total_files_count} files | Completed: {_completed_count} | Failed: {_error_count} | Cached: 0 paras"
                    )
                    main_pbar.update(1)
            return local_success, local_error
        
        futures = []
        total_files_count = len(files_to_translate_exclude_translated)
        for worker_id, files in worker_tasks.items():
            future = executor.submit(worker_process_files, worker_id, files, main_pbar, total_files_count)
            futures.append(future)
        
        # Monitor completion - just wait for all workers to finish
        for future in concurrent.futures.as_completed(futures):
            try:
                local_success, local_error = future.result()
                success_count += local_success
                error_count += local_error
            except Exception as e:
                logging.error(f"Worker 执行异常: {e}")
                error_count += 1
        
        # Close all worker progress bars first (in order)
        with _pbar_lock:
            for worker_id in sorted(_worker_pbars.keys()):
                pbar = _worker_pbars[worker_id]
                if pbar is not None:
                    try:
                        pbar.close()
                    except Exception:
                        pass
            _worker_pbars.clear()
        
        # Close main progress bar last to keep it at the bottom
        main_pbar.close()
        
        # 记录翻译任务完成
        logging.info(f"翻译任务完成 - 成功: {success_count} 文件 - 失败: {error_count} 文件")

if __name__ == '__main__':
    translate() 