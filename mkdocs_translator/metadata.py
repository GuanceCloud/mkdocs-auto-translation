import json
from pathlib import Path
from typing import Dict, Optional
import hashlib
from datetime import datetime

class MetadataManager:
    """Manage metadata for translated files"""
    
    def __init__(self, metadata_path: Path, source_path: Path):
        """
        Initialize the metadata manager
        
        Args:
            metadata_path: The path to the metadata file
            source_path: The path to the source directory
        """
        self.metadata_path = metadata_path
        self.source_path = source_path
        self.metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict:
        """Load metadata from file"""
        if self.metadata_path.exists():
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
        
    def save_metadata(self):
        """Save metadata to file"""
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2)

    def clear_metadata(self):
        """Clear metadata"""
        self.metadata = {}
        self.save_metadata()
            
    def get_file_hash(self, file_path: Path) -> str:
        """
        Calculate the hash value of a file
        
        Args:
            file_path: The path to the file
            
        Returns:
            The SHA256 hash value of the file
        """
        with open(self.source_path / file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
            
    def needs_translation(self, file_path: Path) -> bool:
        """
        Check if a file needs translation
        
        Args:
            file_path: The path to the file
            
        Returns:
            bool: True if the file needs translation, False otherwise
        """
        current_hash = self.get_file_hash(file_path)
        file_key = str(file_path)
        
        if file_key not in self.metadata:
            return True
            
        return self.metadata[file_key]['hash'] != current_hash
        
    def update_file_status(self, file_path: Path, success: bool, translated_metadata: Dict = None):
        """
        Update the translation status of a file
        
        Args:
            file_path: The path to the file
            success: Whether the translation is successful
            translated_metadata: The metadata of the file
        """
        if success:
            file_key = str(file_path)
            self.metadata[file_key] = {
                'hash': self.get_file_hash(file_path),
                'last_translated': datetime.now().isoformat()
            }

            if translated_metadata:
                self.metadata[file_key]['usage'] = translated_metadata.get('usage', {})
                # self.metadata[file_key]['request_id'] = last_file_metadata.get('request_id')

            self.save_metadata() 