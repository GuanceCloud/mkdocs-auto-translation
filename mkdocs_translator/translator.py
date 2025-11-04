import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import requests
import json
from tqdm import tqdm
import hashlib
from datetime import datetime
import logging  # 保留导入，因为还需要使用 logging.info()
import re  # 添加re模块用于正则表达式匹配中文字符

class DocumentTranslator:
    """The main class for handling document translation."""
    
    def __init__(self, target_lang: str, user: str, query: str, response_mode: str = "streaming", api_key: Optional[str] = None, check_chinese: bool = False):
        """
        Initialize the translator.
        
        Args:
            target_lang: The target language code
            user: The user name
            query: The query string
            response_mode: The response mode, optional values are "streaming" or "blocking".
            api_key: The Dify AI API key
            check_chinese: Whether to check if translation results contain Chinese characters
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
        
        self.progress_bars = {}
        self.active_positions = set()  # Track active worker positions
        self.current_tasks = {}  # Track current task for each worker
        self.max_workers = None  # Store the maximum number of workers
        self.check_chinese = check_chinese  # Whether to check for Chinese characters in translation results
        
        # 设置翻译日志
        self._setup_translation_logger()
        
    def _setup_translation_logger(self):
        """设置翻译日志记录器"""
        self.translation_logger = logging.getLogger('translation')
        self.translation_logger.setLevel(logging.INFO)
        
        # 避免重复添加handler
        if not self.translation_logger.handlers:
            # 创建文件handler，输出到translation.log
            log_file = Path.cwd() / 'translation.log'
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # 设置日志格式
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            
            # 只添加文件handler，不添加控制台handler
            self.translation_logger.addHandler(file_handler)
        
    def _contains_chinese(self, text: str) -> bool:
        """
        检查文本是否包含中文字符
        
        Args:
            text: 要检查的文本
            
        Returns:
            bool: 如果包含中文字符返回True，否则返回False
        """
        # 使用正则表达式匹配中文字符（只检查中文字，不包括中文标点符号）
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
        return bool(chinese_pattern.search(text))
        
    def _create_progress_bar(self, position: int, desc: str) -> tqdm:
        """Create a new progress bar with fixed position"""
        # Add position to active positions
        self.active_positions.add(position)
        
        if position not in self.progress_bars:
            # Use the position directly instead of calculating it
            self.progress_bars[position] = tqdm(
                desc=desc,
                unit=" chunks",
                position=position,  # Use absolute position
                leave=True,
                dynamic_ncols=True,
                bar_format='{desc}'  # Only show description, no default stats
            )
        
        pbar = self.progress_bars[position]
        pbar.reset()  # Reset counter
        pbar.set_description(desc)  # Update description
        
        # Record current task
        self.current_tasks[position] = desc
        
        return pbar

    def translate_text(self, text: str, position: int = 0, desc: str = "Translating") -> Tuple[str, Dict]:
        """
        Translate text using the Dify AI API
        
        Args:
            text: The text to translate
            position: The position for the progress bar
            desc: Description for the progress bar
            
        Returns:
            The translated text and metadata
        """
        try:
            # 记录翻译开始
            self.translation_logger.info(f"开始翻译 - {desc} - 文本长度: {len(text)} 字符")
            
            full_translation = []
            conversation_id = ""
            start_time = datetime.now()
            
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
            
            chunk_count = 0
            
            # Ensure we're using the correct progress bar for this worker
            pbar = self._create_progress_bar(position, desc)
            current_task = desc  # Store the current task description
            
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
                
                # 记录API请求
                if not conversation_id:
                    self.translation_logger.info(f"发送翻译请求 - {desc} - 目标语言: {self.target_lang}")
                else:
                    self.translation_logger.info(f"继续翻译请求 - {desc} - 会话ID: {conversation_id}")
                
                response = requests.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,
                    stream=self.response_mode == "streaming"
                )
                
                if response.status_code != 200:
                    error_msg = f"API请求失败 - {desc} - 状态码: {response.status_code} - 响应: {response.text}"
                    self.translation_logger.error(error_msg)
                    raise TranslationError(f"API request failed with status code {response.status_code}: {response.text}")
                
                current_translation = []
                reached_token_limit = False
                
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
                                            cumulative_usage["exceed_token_limit"] = True

                                            self.translation_logger.warning(f"达到token限制 - {desc} - 完成tokens: {usage.get('completion_tokens')} - 会话ID: {conversation_id}")
                                            print("data: ", line)
                                            print(f"Reached token limit: {usage.get('completion_tokens')} tokens, conversation_id: {conversation_id}")
                                # print("message end: ", line)
                                break
                                
                            if "answer" in data:
                                chunk = data["answer"]
                                # 检查翻译结果是否包含中文字符（如果启用了检测）
                                if self.check_chinese and self._contains_chinese(chunk):
                                    error_msg = f"翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {chunk[:100]}..."
                                    self.translation_logger.error(error_msg)
                                    raise TranslationError(f"翻译结果包含中文字符，翻译失败。检测到的中文字符内容: {chunk[:100]}...")
                                
                                current_translation.append(chunk)
                                chunk_count += 1
                                elapsed = (datetime.now() - start_time).total_seconds()
                                chunks_per_second = chunk_count / elapsed if elapsed > 0 else 0
                                
                                # 记录翻译进度
                                if chunk_count % 10 == 0:  # 每10个chunk记录一次进度
                                    self.translation_logger.info(f"翻译进度 - {desc} - 已翻译: {chunk_count} chunks - 速度: {chunks_per_second:.1f} chunks/s - 耗时: {elapsed:.1f}s")
                                
                                # Only update if this is still the current task for this worker
                                if position in self.progress_bars and self.current_tasks.get(position) == current_task:
                                    status = f"{desc} [{chunk_count} chunks, {chunks_per_second:.1f} chunks/s, {elapsed:.1f}s]"
                                    self.progress_bars[position].set_description(status)
                                    self.progress_bars[position].update(1)
                            elif "error" in data:
                                error_msg = f"API错误 - {desc} - 错误信息: {data['error']}"
                                self.translation_logger.error(error_msg)
                                raise TranslationError(f"API error: {data['error']}")
                        except json.JSONDecodeError:
                            continue
                else:
                    # Process blocking mode responses
                    data = response.json()
                    if "answer" in data:
                        answer = data["answer"]
                        # 检查翻译结果是否包含中文字符（如果启用了检测）
                        if self.check_chinese and self._contains_chinese(answer):
                            error_msg = f"翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {answer[:100]}..."
                            self.translation_logger.error(error_msg)
                            raise TranslationError(f"翻译结果包含中文字符，翻译失败。检测到的中文字符内容: {answer[:100]}...")
                        
                        current_translation.append(answer)
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
                        error_msg = f"API错误 - {desc} - 错误信息: {data['error']}"
                        self.translation_logger.error(error_msg)
                        raise TranslationError(f"API error: {data['error']}")
                
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
            
            # 最终检查完整的翻译结果是否包含中文字符（如果启用了检测）
            final_translation = "".join(full_translation)
            if self.check_chinese and self._contains_chinese(final_translation):
                error_msg = f"最终翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {final_translation[:200]}..."
                self.translation_logger.error(error_msg)
                raise TranslationError(f"最终翻译结果包含中文字符，翻译失败。检测到的中文字符内容: {final_translation[:200]}...")
            
            # Calculate total translation time
            total_time = (datetime.now() - start_time).total_seconds()
            
            # Update final status only if this is still the current task for this worker
            if position in self.progress_bars and self.current_tasks.get(position) == current_task:
                final_status = f"{desc} [Done in {total_time:.1f}s, {chunk_count} chunks]"
                self.progress_bars[position].set_description(final_status)
                self.progress_bars[position].refresh()
            
            # Add translation time to metadata
            if last_metadata:
                last_metadata['translation_time'] = round(total_time, 2)  # Round to 2 decimal places
            
            # 记录翻译成功
            self.translation_logger.info(f"翻译完成 - {desc} - 耗时: {total_time:.1f}s - 总chunks: {chunk_count} - 总tokens: {cumulative_usage['total_tokens']}")
            
            return final_translation, last_metadata
                
        except Exception as e:
            # 记录翻译失败
            error_msg = f"翻译失败 - {desc} - 错误信息: {str(e)}"
            self.translation_logger.error(error_msg)
            
            if position in self.progress_bars:
                self.progress_bars[position].clear()
            raise TranslationError(f"Translation failed: {str(e)}")

    def translate_file(self, source_path: Path, target_path: Path, position: int = 0, 
                      desc: str = "Translating", current_file: int = 1, total_files: int = 1) -> Tuple[bool, Dict]:
        """
        Translate a single file
        
        Args:
            source_path: The source file path
            target_path: The target file path
            position: The position for the progress bar
            desc: Description for the progress bar
            current_file: The current file number
            total_files: The total number of files
            
        Returns:
            Tuple[bool, Dict]: Whether the translation is successful and the metadata of the file
        """
        try:
            # 记录文件翻译开始
            self.translation_logger.info(f"开始翻译文件 - {source_path.name} ({current_file}/{total_files}) - 源路径: {source_path}")
            
            with open(source_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update desc to include file progress
            desc = f"{desc} ({current_file}/{total_files})"
            
            translated_content, translated_metadata = self.translate_text(
                content,
                position=position,
                desc=desc
            )
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
            
            # 记录文件翻译成功
            self.translation_logger.info(f"文件翻译成功 - {source_path.name} - 目标路径: {target_path} - 翻译后长度: {len(translated_content)} 字符")
                
            return True, translated_metadata
        except Exception as e:
            # 记录文件翻译失败
            error_msg = f"文件翻译失败 - {source_path.name} - 错误信息: {str(e)}"
            self.translation_logger.error(error_msg)
            print(f"Error translating {source_path}: {str(e)}")
            # 返回包含错误信息的metadata
            error_metadata = {'error_message': str(e)}
            return False, error_metadata

    def __del__(self):
        """Clean up all progress bars"""
        for pbar in self.progress_bars.values():
            pbar.clear()
            pbar.close()

class TranslationError(Exception):
    """Error during translation"""
    pass 