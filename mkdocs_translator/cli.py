import click
from pathlib import Path
from typing import Optional
import logging
from .translator import DocumentTranslator
from .metadata import MetadataManager
from .utils import get_translatable_files, copy_resources, load_blacklist
from tqdm import tqdm

@click.command()
@click.option('--source', required=True, type=click.Path(exists=True), help='The source document directory')
@click.option('--target', required=True, type=click.Path(), help='The target translation directory')
@click.option('--target-language', required=True, help='The target language code')
@click.option('--api-key', help='DifyAI API key')
@click.option('--user', help='User name')
@click.option('--query', help='Query string', default='请翻译。')
@click.option('--response-mode', help='Response mode', type=click.Choice(['streaming', 'blocking']), default='streaming')
def translate(source: str, target: str,
             target_language: str, api_key: Optional[str], user: Optional[str], 
             query: Optional[str], response_mode: str):
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
    
    # Get files to translate
    files_to_translate = [f for f in get_translatable_files(source_path) 
                         if str(f.relative_to(source_path)) not in blacklist]
    
    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)
    
    # Copy resource files
    copy_resources(source_path, target_path)
    
    # Translate files
    success_count = 0
    error_count = 0
    
    # clear last metadata
    last_metadata_manager.clear_metadata()

    for source_file in tqdm(files_to_translate, desc="Translation progress"):
        relative_path = source_file.relative_to(source_path)
        if not metadata_manager.needs_translation(relative_path):
            continue

        target_file = target_path / relative_path
        
        success, translated_metadata = translator.translate_file(source_file, target_file)
        
        if success:
            success_count += 1
            metadata_manager.update_file_status(relative_path, True)
            last_metadata_manager.update_file_status(relative_path, True, translated_metadata)
        else:
            error_count += 1
    
    # Print summary
    click.echo(f"\nTranslation completed!")
    click.echo(f"Success: {success_count} files")
    click.echo(f"Failed: {error_count} files")

if __name__ == '__main__':
    translate() 