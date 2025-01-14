import json
from pathlib import Path
from typing import Dict, Optional
import hashlib

class MetadataManager:
    """管理翻译文件的元数据"""
    
    def __init__(self, metadata_path: Path):
        """
        初始化元数据管理器
        
        Args:
            metadata_path: 元数据文件路径
        """
        self.metadata_path = metadata_path
        self.metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict:
        """加载元数据文件"""
        if self.metadata_path.exists():
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
        
    def save_metadata(self):
        """保存元数据到文件"""
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2)
            
    def get_file_hash(self, file_path: Path) -> str:
        """
        计算文件的哈希值
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件的SHA256哈希值
        """
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
            
    def needs_translation(self, file_path: Path) -> bool:
        """
        检查文件是否需要翻译
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 如果文件需要翻译则返回True
        """
        current_hash = self.get_file_hash(file_path)
        file_key = str(file_path)
        
        if file_key not in self.metadata:
            return True
            
        return self.metadata[file_key]['hash'] != current_hash
        
    def update_file_status(self, file_path: Path, success: bool):
        """
        更新文件的翻译状态
        
        Args:
            file_path: 文件路径
            success: 翻译是否成功
        """
        if success:
            file_key = str(file_path)
            self.metadata[file_key] = {
                'hash': self.get_file_hash(file_path),
                'last_translated': str(Path.ctime(file_path))
            }
            self.save_metadata() 