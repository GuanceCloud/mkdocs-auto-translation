from pathlib import Path
from typing import Set

def get_translatable_files(directory: Path) -> Set[Path]:
    """
    获取目录中可翻译的文件
    
    Args:
        directory: 要扫描的目录
        
    Returns:
        可翻译文件的集合
    """
    translatable_extensions = {'.md', '.pages'}
    files = set()
    
    for ext in translatable_extensions:
        files.update(directory.glob(f'**/*{ext}'))
    
    return files

def copy_resources(source_dir: Path, target_dir: Path):
    """
    复制非翻译文件到目标目录
    
    Args:
        source_dir: 源目录
        target_dir: 目标目录
    """
    non_translatable_patterns = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.css', '*.js']
    
    for pattern in non_translatable_patterns:
        for source_file in source_dir.glob(f'**/{pattern}'):
            relative_path = source_file.relative_to(source_dir)
            target_file = target_dir / relative_path
            
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(source_file.read_bytes()) 