import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import requests
import json
from tqdm import tqdm
import hashlib
from datetime import datetime
import logging  # 保留导入，因为还需要使用 logging.info()

class DocumentTranslator:
    """The main class for handling document translation."""
    
    def __init__(self, target_lang: str, user: str, query: str, response_mode: str = "streaming", api_key: Optional[str] = None):
        """
        Initialize the translator.
        
        Args:
            target_lang: The target language code
            user: The user name
            query: The query string
            response_mode: The response mode, optional values are "streaming" or "blocking".
            api_key: The Dify AI API key
        """
        self.target_lang = target_lang
        self.user = user
        self.query = query
        self.response_mode = response_mode
        self.api_key = api_key or os.getenv('DIFY_API_KEY')
        if not self.api_key:
            raise ValueError("Dify API key must be provided either through api_key parameter or DIFY_API_KEY environment variable")
        
        self.api_url = "https://dify.guance.com/v1/chat-messages"
        # self.api_url = "https://dify.guance.com/v1/completion-messages"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        
    def translate_text(self, text: str) -> Tuple[str, Dict]:
        """
        Translate text using the Dify AI API
        
        Args:
            text: The text to translate
            
        Returns:
            The translated text
        """
        try:
            full_translation = []
            conversation_id = ""
            # Initialize cumulative usage
            cumulative_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "prompt_price": 0.0,
                "completion_price": 0.0,
                "total_price": 0.0,
                "currency": "USD"
            }
            
            while True:
                payload = {
                    "inputs": {
                        "target_language": self.target_lang,
                        "input_content": text
                    },
                    "query": self.query if not conversation_id else "请继续翻译",
                    "response_mode": self.response_mode,
                    "conversation_id": conversation_id,
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
                
                current_translation = []
                reached_token_limit = False
                
                # Create a progress bar
                pbar = tqdm(desc="Translating", unit=" chunks")
                
                if self.response_mode == "streaming":
                    for line in response.iter_lines(decode_unicode=True):
                        if not line:
                            continue

                        # print(line)    
                        
                        try:
                            if line.startswith('data: '):
                                line = line[6:]
                            data = json.loads(line)
                            
                            # process message end event
                            if "event" in data and data["event"] == "message_end":
                                if "metadata" in data:
                                    metadata = data["metadata"]
                                    if "usage" in metadata:
                                        usage = metadata["usage"]
                                        # Accumulate usage data
                                        cumulative_usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
                                        cumulative_usage["completion_tokens"] += int(usage.get("completion_tokens", 0))
                                        cumulative_usage["total_tokens"] = cumulative_usage["prompt_tokens"] + cumulative_usage["completion_tokens"]
                                        cumulative_usage["prompt_price"] += float(usage.get("prompt_price", 0))
                                        cumulative_usage["completion_price"] += float(usage.get("completion_price", 0))
                                        cumulative_usage["total_price"] += float(usage.get("total_price", 0))
                                        
                                        if usage.get("completion_tokens") >= 8192:
                                            reached_token_limit = True
                                            conversation_id = data.get("conversation_id", "")

                                            print("data: ", line)
                                            print(f"Reached token limit: {usage.get('completion_tokens')} tokens, conversation_id: {conversation_id}")
                                # print("message end: ", line)
                                break
                                
                            if "answer" in data:
                                chunk = data["answer"]
                                current_translation.append(chunk)
                                if "metadata" in data:
                                    metadata = data["metadata"]
                                pbar.update(1)
                            elif "error" in data:
                                raise TranslationError(f"API error: {data['error']}")
                        except json.JSONDecodeError:
                            continue
                else:
                    # Process blocking mode responses
                    data = response.json()
                    if "answer" in data:
                        current_translation.append(data["answer"])
                        if "metadata" in data:
                            metadata = data["metadata"]
                            if "usage" in metadata:
                                usage = metadata["usage"]
                                # Accumulate usage data
                                cumulative_usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
                                cumulative_usage["completion_tokens"] += int(usage.get("completion_tokens", 0))
                                cumulative_usage["total_tokens"] = cumulative_usage["prompt_tokens"] + cumulative_usage["completion_tokens"]
                                cumulative_usage["prompt_price"] += float(usage.get("prompt_price", 0))
                                cumulative_usage["completion_price"] += float(usage.get("completion_price", 0))
                                cumulative_usage["total_price"] += float(usage.get("total_price", 0))
                        pbar.update(1)
                    elif "error" in data:
                        raise TranslationError(f"API error: {data['error']}")
                
                pbar.close()
                
                # merge current translation result, handle possible overlap
                current_text = "".join(current_translation)
                
                if full_translation:
                    # find overlap
                    last_part = full_translation[-1][-100:]  # use last 100 characters for overlap search
                    overlap_start = current_text.find(last_part)
                    
                    if overlap_start != -1:
                        # if overlap found, only add new content after overlap
                        current_text = current_text[overlap_start + len(last_part):]
                
                full_translation.append(current_text)
                
                last_metadata = {}
                if metadata:
                    last_metadata = metadata.copy()
                    if "usage" in metadata:
                        # Replace the final usage data with cumulative totals
                        last_metadata['usage'] = cumulative_usage
                
                if not reached_token_limit:
                    break
                    
                # print("\nReached token limit, continuing translation...")
            
            return "".join(full_translation), last_metadata
                
        except Exception as e:
            raise TranslationError(f"Translation failed: {str(e)}")

    def translate_file(self, source_path: Path, target_path: Path) -> Tuple[bool, Dict]:
        """
        Translate a single file
        
        Args:
            source_path: The source file path
            target_path: The target file path
            
        Returns:
            Tuple[bool, Dict]: Whether the translation is successful and the metadata of the file
        """
        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            translated_content, translated_metadata = self.translate_text(content)
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
                
            return True, translated_metadata
        except Exception as e:
            print(f"Error translating {source_path}: {str(e)}")
            return False, None


class TranslationError(Exception):
    """Error during translation"""
    pass 