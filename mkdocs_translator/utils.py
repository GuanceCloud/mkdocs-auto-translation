from pathlib import Path
from typing import Set

def get_translatable_files(directory: Path) -> Set[Path]:
    """
    Get translatable files in a directory
    
    Args:
        directory: The directory to scan
        
    Returns:
        A set of translatable files
    """
    translatable_extensions = {'.md', '.pages'}
    files = set()
    
    for ext in translatable_extensions:
        files.update(directory.glob(f'**/*{ext}'))
    
    return files

def copy_resources(source_dir: Path, target_dir: Path):
    """
    Copy non-translatable files to the target directory
    
    Args:
        source_dir: The source directory
        target_dir: The target directory
    """
    non_translatable_patterns = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.css', '*.js']
    
    for pattern in non_translatable_patterns:
        for source_file in source_dir.glob(f'**/{pattern}'):
            relative_path = source_file.relative_to(source_dir)
            target_file = target_dir / relative_path
            
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(source_file.read_bytes()) 