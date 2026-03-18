import click
from pathlib import Path
from typing import Optional, List, Tuple, Dict
import logging
from datetime import datetime
from .translator import DocumentTranslator
from .metadata import MetadataManager
from .utils import get_translatable_files, copy_resources, load_blacklist
from .parser import parse_file_incremental, compute_doc_hash, is_pages_file
from .cache_manager import CacheManager, CacheData
from tqdm import tqdm
import concurrent.futures
from functools import partial
from fnmatch import fnmatch

_worker_pbars: Dict[int, Optional[tqdm]] = {}

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
    metadata_path = source_path / 'metadata.json'
    last_metadata_path = source_path / 'last-metadata.json'
    blacklist_file = source_path / '.translate-blacklist'
    # Load blacklist
    blacklist = load_blacklist(blacklist_file)
    
    # Initialize components
    translator = DocumentTranslator(
        target_language, 
        response_mode=response_mode, 
        api_key=api_key, 
        check_chinese=check_chinese, 
        check_line_count=check_line_count,
        base_url=base_url,
        model=model
    )
    metadata_manager = MetadataManager(metadata_path, source_path)
    last_metadata_manager = MetadataManager(last_metadata_path, source_path)
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

    # get files to translate that are not translated
    files_to_translate_exclude_translated = [f for f in files_to_translate if metadata_manager.needs_translation(f.relative_to(source_path))]

    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)
    
    # Copy resource files
    copy_resources(source_path, target_path, overwrite_resources=overwrite_resources, delete_removed_resources=delete_removed_resources)
    
    # clear last metadata
    last_metadata_manager.clear_metadata()

    def process_file(source_file, translator, target_path, source_path, metadata_manager, 
                    last_metadata_manager, worker_id, worker_tasks_count):
        relative_path = source_file.relative_to(source_path)
        target_file = target_path / relative_path
        
        # Get total files for this worker and calculate current file number
        total_files = len(worker_tasks_count[worker_id])
        current_file_num = worker_tasks_count[worker_id].index(source_file) + 1
        
        try:
            success, translated_metadata = translator.translate_file(
                source_file, 
                target_file,
                position=worker_id,
                desc=f"Worker {worker_id + 1}: {relative_path}",
                current_file=current_file_num,
                total_files=total_files
            )
            
            if success:
                # Update both metadata files with translation time
                if translated_metadata and 'translation_time' in translated_metadata:
                    metadata_manager.update_file_status(relative_path, True, {'translation_time': translated_metadata['translation_time']})
                    last_metadata_manager.update_file_status(relative_path, True, translated_metadata)
                    logging.info(f"文件翻译成功并更新metadata - {relative_path} - 翻译时间: {translated_metadata['translation_time']}s")
                else:
                    metadata_manager.update_file_status(relative_path, True)
                    last_metadata_manager.update_file_status(relative_path, True, translated_metadata)
                    logging.info(f"文件翻译成功并更新metadata - {relative_path}")
                return True
            else:
                # 翻译失败但没有异常
                error_metadata = {'error_message': 'Translation failed without specific error'}
                metadata_manager.update_file_status(relative_path, False, error_metadata)
                last_metadata_manager.update_file_status(relative_path, False, error_metadata)
                logging.error(f"文件翻译失败（无具体错误） - {relative_path}")
                return False
                
        except Exception as e:
            # 捕获翻译过程中的异常
            error_message = str(e)
            logging.error(f"翻译文件 {relative_path} 时发生异常: {error_message}")
            print(f"翻译文件 {relative_path} 时发生错误: {error_message}")
            
            # 记录失败情况到两个metadata文件中
            error_metadata = {'error_message': error_message}
            metadata_manager.update_file_status(relative_path, False, error_metadata)
            last_metadata_manager.update_file_status(relative_path, False, error_metadata)
            
            return False

    def process_file_incremental(
        source_file: Path,
        translator: DocumentTranslator,
        target_path: Path,
        source_path: Path,
        metadata_manager: MetadataManager,
        last_metadata_manager: MetadataManager,
        cache_manager: CacheManager,
        worker_id: int,
        worker_tasks_count: dict
    ) -> bool:
        relative_path = source_file.relative_to(source_path)
        target_file = target_path / relative_path

        total_files = len(worker_tasks_count[worker_id])
        current_file_num = worker_tasks_count[worker_id].index(source_file) + 1

        try:
            logging.info(f"开始增量翻译 - {relative_path} ({current_file_num}/{total_files})")

            is_pages = is_pages_file(source_file)
            paragraphs = parse_file_incremental(source_file, is_pages)
            doc_hash = compute_doc_hash(paragraphs)

            cache = cache_manager.load_cache(relative_path)
            if cache is None:
                cache = CacheData()

            if cache.source_doc_hash == doc_hash:
                all_cached = True
                for para in paragraphs:
                    if para.content_hash not in cache.paragraphs:
                        all_cached = False
                        break

                if all_cached:
                    logging.info(f"文档未变化，使用缓存 - {relative_path}")
                    
                    pbar = _worker_pbars.get(worker_id)
                    if pbar is None:
                        pbar = tqdm(
                            total=1,
                            desc=f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p {len(paragraphs)}/{len(paragraphs)}] (使用缓存:{len(paragraphs)}/{len(paragraphs)})",
                            position=worker_id,
                            leave=True,
                            dynamic_ncols=True,
                            mininterval=0.5,
                            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}'
                        )
                        _worker_pbars[worker_id] = pbar
                    else:
                        pbar.reset(total=1)
                        pbar.set_description(f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p {len(paragraphs)}/{len(paragraphs)}] (使用缓存:{len(paragraphs)}/{len(paragraphs)})")
                    pbar.update(1)
                    
                    _assemble_from_cache(paragraphs, cache, target_file)
                    metadata_manager.update_file_status(relative_path, True, {'translation_time': 0})
                    last_metadata_manager.update_file_status(relative_path, True, {'translation_time': 0})
                    return True

            need_translate = []
            for para in paragraphs:
                if para.content_hash in cache.paragraphs:
                    cached_para = cache.paragraphs[para.content_hash]
                    if cached_para.source_content == para.content:
                        continue

                similar = cache_manager.find_similar_paragraph(para.content, cache, 0.6)
                if similar:
                    need_translate.append((para, similar[0]))
                else:
                    need_translate.append((para, None))

            total_need = len(need_translate)
            total_paragraphs = len(paragraphs)
            cached_count = total_paragraphs - total_need
            cache_info = f"(缓存:{cached_count}/{total_paragraphs})"

            pbar = _worker_pbars.get(worker_id)
            if pbar is None:
                pbar = tqdm(
                    total=total_need if total_need > 0 else 1,
                    desc=f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p 0/{total_paragraphs}] {cache_info}",
                    position=worker_id,
                    leave=True,
                    dynamic_ncols=True,
                    mininterval=0.5,
                    bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}'
                )
                _worker_pbars[worker_id] = pbar
            else:
                pbar.reset(total=total_need if total_need > 0 else 1)
                pbar.set_description(f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p 0/{total_paragraphs}] {cache_info}")

            if total_need > 0:

                cumulative_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }

                for idx, (para, reference) in enumerate(need_translate):
                    pbar.set_description(
                        f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p {idx+1}/{total_paragraphs}] {cache_info}"
                    )
                    translation, usage_data = translator.translate_paragraph(
                        para.content,
                        reference=reference,
                        translation_memory=cache.translation_memory,
                        position=worker_id,
                        desc=f"{relative_path}: {para.content_hash}"
                    )

                    cumulative_usage["prompt_tokens"] += usage_data["prompt_tokens"]
                    cumulative_usage["completion_tokens"] += usage_data["completion_tokens"]
                    cumulative_usage["total_tokens"] += usage_data["total_tokens"]

                    cache_manager.save_paragraph_translation(
                        cache,
                        para.content_hash,
                        para.content,
                        translation,
                        para.paragraph_type
                    )

                    cache_manager.extract_and_update_memory(cache, para.content, translation)

                    pbar.update(1)

                translated_metadata = {
                    'translation_time': 0,
                    'usage': cumulative_usage
                }
            else:
                translated_metadata = {'translation_time': 0}
                cache_info = f"(使用缓存:{total_paragraphs}/{total_paragraphs})"
                pbar.set_description(f"Worker {worker_id + 1}: ({current_file_num}/{total_files}) {relative_path.name} [p {total_paragraphs}/{total_paragraphs}] {cache_info}")
                pbar.update(1)

            _assemble_from_cache(paragraphs, cache, target_file)

            cache.source_doc_hash = doc_hash
            cache.last_translated = datetime.now().isoformat()
            cache_manager.save_cache(relative_path, cache)

            metadata_manager.update_file_status(
                relative_path, True,
                {'translation_time': translated_metadata.get('translation_time', 0)}
            )
            last_metadata_manager.update_file_status(relative_path, True, translated_metadata)

            logging.info(f"文件翻译成功 - {relative_path}")
            return True

        except Exception as e:
            error_message = str(e)
            logging.error(f"增量翻译文件 {relative_path} 时发生异常: {error_message}")
            print(f"翻译文件 {relative_path} 时发生错误: {error_message}")

            error_metadata = {'error_message': error_message}
            metadata_manager.update_file_status(relative_path, False, error_metadata)
            last_metadata_manager.update_file_status(relative_path, False, error_metadata)

            return False

    def _assemble_from_cache(paragraphs, cache, target_file):
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            for i, para in enumerate(paragraphs):
                if para.content_hash in cache.paragraphs:
                    f.write(cache.paragraphs[para.content_hash].translation)
                if i < len(paragraphs) - 1:
                    f.write("\n\n")

    # 并行执行翻译
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
            metadata_manager=metadata_manager,
            last_metadata_manager=last_metadata_manager,
            cache_manager=cache_manager,
            worker_tasks_count=worker_tasks  # Pass the worker tasks information
        )
        
        futures = []
        for file, worker_id in tasks:
            future = executor.submit(process_func, source_file=file, worker_id=worker_id)
            futures.append(future)
        
        # Monitor completion
        cached_paragraphs = 0
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is True:
                success_count += 1
                logging.info(f"翻译进度: {success_count}/{len(files_to_translate_exclude_translated)} 成功")
            elif result is False:
                error_count += 1
                logging.error(f"翻译进度: {error_count}/{len(files_to_translate_exclude_translated)} 失败")
            
            main_pbar.set_description(
                f"Total: {len(files_to_translate_exclude_translated)} files | Completed: {success_count} | Failed: {error_count} | Cached: {cached_paragraphs} paras"
            )
            main_pbar.update(1)
        
        main_pbar.clear()
        main_pbar.close()
        
        # Close all worker progress bars
        for worker_id, pbar in list(_worker_pbars.items()):
            if pbar is not None:
                try:
                    pbar.close()
                except Exception:
                    pass
        _worker_pbars.clear()
        
        # 记录翻译任务完成
        logging.info(f"翻译任务完成 - 成功: {success_count} 文件 - 失败: {error_count} 文件")
        
        click.echo('\n' * (workers + 1))
        click.echo(f"Translation completed!")
        click.echo(f"Success: {success_count} files")
        click.echo(f"Failed: {error_count} files")

if __name__ == '__main__':
    translate() 