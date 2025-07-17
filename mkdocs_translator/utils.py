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

def copy_resources(source_dir: Path, target_dir: Path, overwrite_resources: bool = False, delete_removed_resources: bool = False):
    """
    Copy non-translatable files to the target directory.
    Skip .md files and .pages file (not extension, but full filename).
    
    Args:
        source_dir: The source directory
        target_dir: The target directory
        overwrite_resources: Whether to overwrite existing files in target directory
        delete_removed_resources: Whether to delete files in target directory that no longer exist in source directory
    """
    # Get all source resource files
    source_resources = set()
    for source_file in source_dir.glob('**/*'):
        if source_file.is_dir():
            continue
            
        if source_file.suffix == '.md' or source_file.name == '.pages':
            continue
            
        relative_path = source_file.relative_to(source_dir)
        source_resources.add(relative_path)
    
    # Get all existing target resource files
    target_resources = set()
    if target_dir.exists():
        for target_file in target_dir.glob('**/*'):
            if target_file.is_dir():
                continue
                
            if target_file.suffix == '.md' or target_file.name == '.pages':
                continue
                
            relative_path = target_file.relative_to(target_dir)
            target_resources.add(relative_path)
    
    # Copy source resources to target
    for relative_path in source_resources:
        source_file = source_dir / relative_path
        target_file = target_dir / relative_path
        
        target_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy if target file doesn't exist or if overwrite is enabled
        if not target_file.exists() or overwrite_resources:
            target_file.write_bytes(source_file.read_bytes())
    
    # Delete removed resources if enabled
    if delete_removed_resources:
        removed_resources = target_resources - source_resources
        for relative_path in removed_resources:
            target_file = target_dir / relative_path
            if target_file.exists():
                target_file.unlink()
                # Remove empty directories
                for parent in target_file.parents:
                    if parent == target_dir:
                        break
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()

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
