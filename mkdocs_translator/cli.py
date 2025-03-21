import click
from pathlib import Path
from typing import Optional
import logging
from .translator import DocumentTranslator
from .metadata import MetadataManager
from .utils import get_translatable_files, copy_resources, load_blacklist
from tqdm import tqdm
import concurrent.futures
from functools import partial

@click.command()
@click.option('--source', required=True, type=click.Path(exists=True), help='The source document directory')
@click.option('--target', required=True, type=click.Path(), help='The target translation directory')
@click.option('--target-language', required=True, help='The target language code')
@click.option('--api-key', help='DifyAI API key')
@click.option('--user', help='User name')
@click.option('--query', help='Query string', default='请翻译。')
@click.option('--response-mode', help='Response mode', type=click.Choice(['streaming', 'blocking']), default='streaming')
@click.option('--workers', type=int, default=1, help='Number of parallel workers')
def translate(source: str, target: str,
             target_language: str, api_key: Optional[str], user: Optional[str], 
             query: Optional[str], response_mode: str, workers: int):
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
    blacklist = load_blacklist(source_path / blacklist_file)
    
    # Initialize components
    translator = DocumentTranslator(target_language, user=user, query=query, response_mode=response_mode, api_key=api_key)
    metadata_manager = MetadataManager(metadata_path, source_path)
    last_metadata_manager = MetadataManager(last_metadata_path, source_path)
    
    def is_blacklisted(file_path: str, blacklist: set) -> bool:
        """Check if a file path matches any blacklist pattern"""

        # Check exact match
        if file_path in blacklist:
            return True
        # Check directory prefix match
        return any(
            (pattern.endswith('/') and file_path.startswith(pattern)) 
            for pattern in blacklist
        )
    
    # Get files to translate
    files_to_translate = [f for f in get_translatable_files(source_path) 
                         if not is_blacklisted(str(f.relative_to(source_path)), blacklist)]

    # get files to translate that are not translated
    files_to_translate_exclude_translated = [f for f in files_to_translate if metadata_manager.needs_translation(f.relative_to(source_path))]

    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)
    
    # Copy resource files
    copy_resources(source_path, target_path)
    
    # clear last metadata
    last_metadata_manager.clear_metadata()

    def process_file(source_file, translator, target_path, source_path, metadata_manager, 
                    last_metadata_manager, worker_id, worker_tasks_count):
        relative_path = source_file.relative_to(source_path)
        target_file = target_path / relative_path
        
        # Get total files for this worker and calculate current file number
        total_files = len(worker_tasks_count[worker_id])
        current_file_num = worker_tasks_count[worker_id].index(source_file) + 1
        
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
            else:
                metadata_manager.update_file_status(relative_path, True)
                last_metadata_manager.update_file_status(relative_path, True, translated_metadata)
            return True
        return False

    # 并行执行翻译
    success_count = 0
    error_count = 0
    
    logging.info(f"Starting translation with {workers} workers")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # Create tasks with worker IDs
        tasks = [(file, i % workers) for i, file in enumerate(files_to_translate_exclude_translated)]
        
        # Group tasks by worker
        worker_tasks = {}
        for file, worker_id in tasks:
            if worker_id not in worker_tasks:
                worker_tasks[worker_id] = []
            worker_tasks[worker_id].append(file)
        
        # Create main progress bar for overall progress
        main_pbar = tqdm(
            total=len(files_to_translate_exclude_translated),
            desc="Total progress",
            position=workers,
            unit="files"
        )
        
        # Create partial function with worker task counts
        process_func = partial(
            process_file,
            translator=translator,
            target_path=target_path,
            source_path=source_path,
            metadata_manager=metadata_manager,
            last_metadata_manager=last_metadata_manager,
            worker_tasks_count=worker_tasks  # Pass the worker tasks information
        )
        
        futures = []
        for file, worker_id in tasks:
            future = executor.submit(process_func, source_file=file, worker_id=worker_id)
            futures.append(future)
        
        # Monitor completion
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is True:
                success_count += 1
            elif result is False:
                error_count += 1
            main_pbar.update(1)
        
        main_pbar.clear()
        main_pbar.close()
        
        click.echo('\n' * (workers + 1))
        click.echo(f"Translation completed!")
        click.echo(f"Success: {success_count} files")
        click.echo(f"Failed: {error_count} files")

if __name__ == '__main__':
    translate() 