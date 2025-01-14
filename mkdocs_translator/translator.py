import os
from pathlib import Path
from typing import Optional, Dict, List
import requests
from tqdm import tqdm

class DocumentTranslator:
    """处理文档翻译的主类"""
    
    def __init__(self, target_lang: str, user: str, query: str = "请翻译。", response_mode: str = "streaming", api_key: Optional[str] = None):
        """
        初始化翻译器
        
        Args:
            target_lang: 目标语言代码
            user: 用户名
            query: 查询语句
            response_mode: 响应模式，可选值为 "streaming" 或 "blocking"
            api_key: Dify AI API密钥
        """
        self.target_lang = target_lang
        self.user = user
        self.query = query
        self.response_mode = response_mode
        self.api_key = api_key or os.getenv('DIFY_API_KEY')
        if not self.api_key:
            raise ValueError("Dify API key must be provided either through api_key parameter or DIFY_API_KEY environment variable")
        
        self.api_url = "https://dify.guance.com/v1/chat-messages"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        
    def translate_text(self, text: str) -> str:
        """
        使用Dify AI API翻译文本
        
        Args:
            text: 要翻译的文本
            
        Returns:
            翻译后的文本
        """
        try:
            payload = {
                "inputs": {
                    "target_language": self.target_lang,
                    "input_content": text
                },
                "query": self.query,
                "response_mode": self.response_mode,
                "conversation_id": "",
                "user": self.user
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                stream=self.response_mode == "streaming"
            )
            
            if response.status_code != 200:
                raise TranslationError(f"API request failed with status code {response.status_code}: {response.text}")
            
            # 用于存储完整的翻译结果
            full_translation = []
            
            # 创建进度条
            pbar = tqdm(desc="Translating", unit=" chunks")
            
            # 处理流式响应
            for line in response.iter_lines():
                if line:
                    try:
                        data = response.json()
                        if "answer" in data:
                            chunk = data["answer"]
                            full_translation.append(chunk)
                            pbar.update(1)  # 更新进度
                        elif "error" in data:
                            raise TranslationError(f"API error: {data['error']}")
                    except Exception as e:
                        continue
            
            pbar.close()  # 关闭进度条
            
            # 合并所有翻译片段
            final_translation = "".join(full_translation)
            
            if not final_translation:
                raise TranslationError("No translation received from API")
                
            return final_translation
                
        except Exception as e:
            raise TranslationError(f"Translation failed: {str(e)}")

    def translate_file(self, source_path: Path, target_path: Path) -> bool:
        """
        翻译单个文件
        
        Args:
            source_path: 源文件路径
            target_path: 目标文件路径
            
        Returns:
            bool: 翻译是否成功
        """
        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            translated_content = self.translate_text(content)
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
                
            return True
        except Exception as e:
            print(f"Error translating {source_path}: {str(e)}")
            return False

class TranslationError(Exception):
    """翻译过程中的错误"""
    pass 