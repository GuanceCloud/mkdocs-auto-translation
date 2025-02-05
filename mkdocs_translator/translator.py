import os
from pathlib import Path
from typing import Optional, Dict, List
import requests
import json
from tqdm import tqdm

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
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        
    def translate_text(self, text: str) -> str:
        """
        Translate text using the Dify AI API
        
        Args:
            text: The text to translate
            
        Returns:
            The translated text
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
            
            # Used to store the complete translation results.
            full_translation = []
            
            # Create a progress bar
            pbar = tqdm(desc="Translating", unit=" chunks")
            
            if self.response_mode == "streaming":
                # Process streaming responses
                for line in response.iter_lines(decode_unicode=True):
                    # print(line)
                    if not line:
                        continue
                        
                    try:
                        # Remove the "data: " prefix (if it exists)
                        if line.startswith('data: '):
                            line = line[6:]
                            data = json.loads(line)
                        else:
                            continue
                        
                        if "event" in data:
                            message_event = data["event"]

                        if message_event == "message_end":
                            break
                            
                        # process translation result
                        if message_event == "agent_message" and "answer" in data:
                            chunk = data["answer"]
                            full_translation.append(chunk)
                            pbar.update(1)
                        elif "error" in data:
                            raise TranslationError(f"API error: {data['error']}")
                    except json.JSONDecodeError as e:
                        continue
            else:
                # Process blocking mode responses
                data = response.json()
                if "answer" in data:
                    full_translation.append(data["answer"])
                    pbar.update(1)
                elif "error" in data:
                    raise TranslationError(f"API error: {data['error']}")
            
            pbar.close()

            # Merge all translation fragments
            final_translation = "".join(full_translation)
            
            if not final_translation:
                raise TranslationError("No translation received from API")
                
            return final_translation
                
        except Exception as e:
            raise TranslationError(f"Translation failed: {str(e)}")

    def translate_file(self, source_path: Path, target_path: Path) -> bool:
        """
        Translate a single file
        
        Args:
            source_path: The source file path
            target_path: The target file path
            
        Returns:
            bool: Whether the translation is successful
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
    """Error during translation"""
    pass 