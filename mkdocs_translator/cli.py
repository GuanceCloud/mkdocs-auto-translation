import click
from pathlib import Path
from typing import Optional
from .translator import DocumentTranslator
from .metadata import MetadataManager
from .utils import get_translatable_files, copy_resources
from tqdm import tqdm

@click.command()
@click.option('--source', required=True, type=click.Path(exists=True), help='源文档目录')
@click.option('--target', required=True, type=click.Path(), help='目标翻译目录')
@click.option('--target-language', required=True, help='目标语言代码')
@click.option('--api-key', help='DifyAI API 密钥')
@click.option('--user', help='用户名')
@click.option('--query', help='查询语句')
@click.option('--response-mode', help='响应模式', type=click.Choice(['streaming', 'blocking']), default='streaming')
def translate(source: str, target: str,
             target_language: str, api_key: Optional[str], user: Optional[str], query: Optional[str], response_mode: str):
    """翻译MkDocs文档"""
    source_path = Path(source)
    target_path = Path(target)
    metadata_path = source_path / 'metadata.json'
    
    # 初始化组件
    translator = DocumentTranslator(target_language, user=user, query=query, response_mode=response_mode, api_key=api_key)
    metadata_manager = MetadataManager(metadata_path)
    
    # 获取需要翻译的文件
    files_to_translate = get_translatable_files(source_path)
    
    # 创建目标目录
    target_path.mkdir(parents=True, exist_ok=True)
    
    # 复制资源文件
    copy_resources(source_path, target_path)
    
    # 翻译文件
    success_count = 0
    error_count = 0
    
    for source_file in tqdm(files_to_translate, desc="翻译进度"):
        if not metadata_manager.needs_translation(source_file):
            continue
            
        relative_path = source_file.relative_to(source_path)
        target_file = target_path / relative_path
        
        success = translator.translate_file(source_file, target_file)
        
        if success:
            success_count += 1
            metadata_manager.update_file_status(source_file, True)
        else:
            error_count += 1
    
    # 打印总结
    click.echo(f"\n翻译完成！")
    click.echo(f"成功：{success_count} 个文件")
    click.echo(f"失败：{error_count} 个文件")

if __name__ == '__main__':
    translate() 