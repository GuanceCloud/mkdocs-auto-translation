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
    Copy non-translatable files to the target directory.
    Skip .md files and .pages file (not extension, but full filename).
    Do not overwrite existing files in target directory.
    
    Args:
        source_dir: The source directory
        target_dir: The target directory
    """
    for source_file in source_dir.glob('**/*'):
        if source_file.is_dir():
            continue
            
        if source_file.suffix == '.md' or source_file.name == '.pages':
            continue
            
        relative_path = source_file.relative_to(source_dir)
        target_file = target_dir / relative_path
        
        target_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Only copy if target file doesn't exist
        if not target_file.exists():
            target_file.write_bytes(source_file.read_bytes()) 

def load_blacklist(blacklist_path: Path) -> set:
    """
    Load blacklist file containing paths to ignore during translation.
    Each line in the file should be a relative path from source directory.
    
    Args:
        blacklist_path: Path to the blacklist file
        
    Returns:
        Set of paths to ignore
    """
    blacklist = set()
    if blacklist_path.exists():
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Strip whitespace and ignore empty lines and comments
                line = line.strip()
                if line and not line.startswith('#'):
                    blacklist.add(line)
    return blacklist 
