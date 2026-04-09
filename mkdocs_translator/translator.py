import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from tqdm import tqdm
from datetime import datetime
import logging
import re
import time
from openai import OpenAI
from .prompts import TRANSLATION_SYSTEM_PROMPT

MAX_RETRIES = 3
REQUEST_TIMEOUT = 120

class DocumentTranslator:
    """The main class for handling document translation."""
    
    def __init__(self, target_lang: str, response_mode: str = "streaming", api_key: Optional[str] = None, check_chinese: bool = False, check_line_count: bool = False, base_url: Optional[str] = None, model: str = "gpt-4o"):
        """
        Initialize the translator.
        
        Args:
            target_lang: The target language code
            response_mode: The response mode, optional values are "streaming" or "blocking".
            api_key: The LLM API key (compatible with OpenAI format)
            check_chinese: Whether to check if translation results contain Chinese characters
            check_line_count: Whether to check if line count difference exceeds 5%
            base_url: The base URL for the LLM API (optional, for compatible API endpoints)
            model: The model name to use (default: gpt-4o)
        """
        self.target_lang = target_lang
        self.response_mode = response_mode
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("API key must be provided either through api_key parameter or OPENAI_API_KEY environment variable")
        
        self.base_url = base_url or os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
        self.model = model
        
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        self.progress_bars = {}
        self.active_positions = set()
        self.current_tasks = {}
        self.check_chinese = check_chinese
        self.check_line_count = check_line_count
        
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

    def _call_llm_api(self, messages: List[Dict], is_continuation: bool = False, position: int = 0, desc: str = "Translating", stream_callback: Optional[callable] = None) -> Tuple[str, Dict]:
        """
        Call LLM API with retry mechanism and timeout control.
        
        Args:
            messages: The messages to send to the API
            is_continuation: Whether this is a continuation request
            position: The position for the progress bar
            desc: Description for the progress bar
            stream_callback: Optional callback function for streaming updates (receives chunk_text)
            
        Returns:
            The response content and usage metadata
        """
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                if is_continuation:
                    self.translation_logger.info(f"重试第 {attempt + 1}/{MAX_RETRIES} 次 - 继续翻译 - {desc}")
                else:
                    self.translation_logger.info(f"重试第 {attempt + 1}/{MAX_RETRIES} 次 - 翻译请求 - {desc}")
                
                if self.response_mode == "streaming" and stream_callback:
                    return self._call_llm_api_streaming(messages, position, desc, stream_callback)
                
                response = self.client.chat.completions.with_raw_response.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code != 200:
                    error_msg = f"API请求失败 - {desc} - 状态码: {response.status_code} - 响应: {response.text}"
                    self.translation_logger.error(error_msg)
                    last_error = f"API request failed with status code {response.status_code}: {response.text}"
                    time.sleep(2 ** attempt)
                    continue
                
                result = response.parse()
                
                content = result.choices[0].message.content
                usage = result.usage
                
                usage_data = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens
                }
                
                self.translation_logger.info(f"API调用成功 - {desc} - 使用tokens: {usage.total_tokens}")
                
                return content, usage_data
                
            except Exception as e:
                error_msg = f"API调用异常 - {desc} - 错误信息: {str(e)}"
                self.translation_logger.error(error_msg)
                last_error = str(e)
                time.sleep(2 ** attempt)
                continue
        
        raise TranslationError(f"API调用失败，已达最大重试次数 {MAX_RETRIES}: {last_error}")

    def _call_llm_api_streaming(self, messages: List[Dict], position: int, desc: str, stream_callback: callable) -> Tuple[str, Dict]:
        """
        Call LLM API with streaming mode for real-time progress updates.
        
        Args:
            messages: The messages to send to the API
            position: The position for the progress bar
            desc: Description for the progress bar
            stream_callback: Callback function for streaming updates
            
        Returns:
            The response content and usage metadata
        """
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                self.translation_logger.info(f"重试第 {attempt + 1}/{MAX_RETRIES} 次 - 流式翻译请求 - {desc}")
                
                response = self.client.chat.completions.with_raw_response.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=REQUEST_TIMEOUT,
                    stream=True
                )
                
                if response.status_code != 200:
                    error_msg = f"API请求失败 - {desc} - 状态码: {response.status_code} - 响应: {response.text}"
                    self.translation_logger.error(error_msg)
                    last_error = f"API request failed with status code {response.status_code}: {response.text}"
                    time.sleep(2 ** attempt)
                    continue
                
                full_content = []
                chunk_count = 0
                
                for chunk in response.parse():
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            content_piece = delta.content
                            full_content.append(content_piece)
                            chunk_count += 1
                            stream_callback(content_piece, chunk_count)
                
                content = "".join(full_content)
                
                usage_data = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
                
                self.translation_logger.info(f"API流式调用成功 - {desc} - chunks: {chunk_count}")
                
                return content, usage_data
                
            except Exception as e:
                error_msg = f"API流式调用异常 - {desc} - 错误信息: {str(e)}"
                self.translation_logger.error(error_msg)
                last_error = str(e)
                time.sleep(2 ** attempt)
                continue
        
        raise TranslationError(f"API调用失败，已达最大重试次数 {MAX_RETRIES}: {last_error}")

    def translate_paragraph(
        self,
        text: str,
        translation_memory: Optional[List[Dict]] = None,
        section_path: Optional[List[str]] = None,
        context_before: str = "",
        context_after: str = "",
        position: int = 0,
        desc: str = "Translating"
    ) -> Tuple[str, Dict]:
        """
        Translate a single paragraph with context and terminology memory.

        Args:
            text: The text to translate
            translation_memory: List of terminology entries
            position: The position for the progress bar
            desc: Description for the progress bar

        Returns:
            The translated text and metadata
        """
        try:
            self.translation_logger.info(f"开始翻译段落 - {desc} - 文本长度: {len(text)} 字符")

            system_prompt = self._build_enhanced_prompt(translation_memory)
            user_message = self._build_user_message(
                text,
                section_path=section_path,
                context_before=context_before,
                context_after=context_after
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

            self.translation_logger.info(f"发送翻译请求 - {desc} - 目标语言: {self.target_lang}")

            translation, usage_data = self._call_llm_api(
                messages,
                is_continuation=False,
                position=position,
                desc=desc
            )

            if self.check_chinese and self._contains_chinese(translation):
                error_msg = f"翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {translation[:100]}..."
                self.translation_logger.error(error_msg)
                raise TranslationError(f"翻译结果包含中文字符，翻译失败。")

            self.translation_logger.info(f"段落翻译完成 - {desc} - tokens: {usage_data['total_tokens']}")

            return translation, usage_data

        except Exception as e:
            error_msg = f"段落翻译失败 - {desc} - 错误信息: {str(e)}"
            self.translation_logger.error(error_msg)
            raise TranslationError(f"Paragraph translation failed: {str(e)}")

    def _build_enhanced_prompt(
        self,
        translation_memory: Optional[List[Dict]] = None
    ) -> str:
        """Build enhanced system prompt with terminology."""
        prompt_parts = [TRANSLATION_SYSTEM_PROMPT]

        if translation_memory:
            terms_text = "\n".join(
                f"- {entry['source']} → {entry['translation']}"
                for entry in translation_memory[:50]
            )
            prompt_parts.append(f"\n\n## 术语表（必须保持一致）\n{terms_text}")

        return "".join(prompt_parts)

    def _build_user_message(
        self,
        text: str,
        section_path: Optional[List[str]] = None,
        context_before: str = "",
        context_after: str = ""
    ) -> str:
        """Build user message for translation."""
        section_context = " > ".join(section_path or [])
        return f"""<input>
<input_content>{text}</input_content>
<target_language>{self.target_lang}</target_language>
<section_context>{section_context}</section_context>
<context_before>{context_before}</context_before>
<context_after>{context_after}</context_after>
</input>"""

    def translate_text(self, text: str, position: int = 0, desc: str = "Translating") -> Tuple[str, Dict]:
        """
        Translate text using the LLM API (OpenAI compatible)
        
        Args:
            text: The text to translate
            position: The position for the progress bar
            desc: Description for the progress bar
            
        Returns:
            The translated text and metadata
        """
        try:
            self.translation_logger.info(f"开始翻译 - {desc} - 文本长度: {len(text)} 字符")
            
            full_translation = []
            start_time = datetime.now()
            
            cumulative_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
            
            chunk_count = 0
            
            pbar = self._create_progress_bar(position, desc)
            current_task = desc
            
            while True:
                user_message = f"""<input>
<input_content>{text}</input_content>
<target_language>{self.target_lang}</target_language>
</input>"""
                
                if not full_translation:
                    messages = [
                        {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message}
                    ]
                    self.translation_logger.info(f"发送翻译请求 - {desc} - 目标语言: {self.target_lang}")
                else:
                    messages = [
                        {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                        {"role": "user", "content": "请继续翻译"}
                    ]
                    self.translation_logger.info(f"继续翻译请求 - {desc}")
                
                def stream_callback(chunk_text: str, current_chunk_count: int):
                    nonlocal chunk_count
                    chunk_count = current_chunk_count
                    elapsed = (datetime.now() - start_time).total_seconds()
                    chunks_per_second = chunk_count / elapsed if elapsed > 0 else 0
                    
                    if chunk_count % 10 == 0:
                        self.translation_logger.info(f"翻译进度 - {desc} - 已翻译: {chunk_count} chunks - 速度: {chunks_per_second:.1f} chunks/s - 耗时: {elapsed:.1f}s")
                    
                    if position in self.progress_bars and self.current_tasks.get(position) == current_task:
                        status = f"{desc} [{chunk_count} chunks, {chunks_per_second:.1f} chunks/s, {elapsed:.1f}s]"
                        self.progress_bars[position].set_description(status)
                        self.progress_bars[position].update(1)
                
                current_translation, usage_data = self._call_llm_api(
                    messages, 
                    is_continuation=bool(full_translation),
                    position=position,
                    desc=desc,
                    stream_callback=stream_callback
                )
                
                cumulative_usage["prompt_tokens"] += usage_data["prompt_tokens"]
                cumulative_usage["completion_tokens"] += usage_data["completion_tokens"]
                cumulative_usage["total_tokens"] += usage_data["total_tokens"]
                
                if self.check_chinese and self._contains_chinese(current_translation):
                    error_msg = f"翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {current_translation[:100]}..."
                    self.translation_logger.error(error_msg)
                    raise TranslationError(f"翻译结果包含中文字符，翻译失败。检测到的中文字符内容: {current_translation[:100]}...")
                
                full_translation.append(current_translation)
                elapsed = (datetime.now() - start_time).total_seconds()
                chunks_per_second = chunk_count / elapsed if elapsed > 0 else 0
                
                if chunk_count % 10 == 0:
                    self.translation_logger.info(f"翻译进度 - {desc} - 已翻译: {chunk_count} chunks - 速度: {chunks_per_second:.1f} chunks/s - 耗时: {elapsed:.1f}s")
                
                if position in self.progress_bars and self.current_tasks.get(position) == current_task:
                    status = f"{desc} [{chunk_count} chunks, {chunks_per_second:.1f} chunks/s, {elapsed:.1f}s]"
                    self.progress_bars[position].set_description(status)
                    self.progress_bars[position].update(1)
                
                break
            
            final_translation = "".join(full_translation)
            
            if self.check_chinese and self._contains_chinese(final_translation):
                error_msg = f"最终翻译结果包含中文字符 - {desc} - 检测到的中文字符内容: {final_translation[:200]}..."
                self.translation_logger.error(error_msg)
                raise TranslationError(f"最终翻译结果包含中文字符，翻译失败。检测到的中文字符内容: {final_translation[:200]}...")
            
            total_time = (datetime.now() - start_time).total_seconds()
            
            if position in self.progress_bars and self.current_tasks.get(position) == current_task:
                final_status = f"{desc} [Done in {total_time:.1f}s, {chunk_count} chunks]"
                self.progress_bars[position].set_description(final_status)
                self.progress_bars[position].refresh()
            
            last_metadata = {
                'usage': cumulative_usage,
                'translation_time': round(total_time, 2)
            }
            
            self.translation_logger.info(f"翻译完成 - {desc} - 耗时: {total_time:.1f}s - 总chunks: {chunk_count} - 总tokens: {cumulative_usage['total_tokens']}")
            
            return final_translation, last_metadata
                
        except Exception as e:
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
            
            # 读取源文件内容并计算行数
            with open(source_path, 'r', encoding='utf-8') as f:
                content = f.read()
                source_lines = content.count('\n') + (1 if content else 0)  # 计算源文件行数
            
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
            
            # 如果启用了行数检查，比较行数差异
            if self.check_line_count:
                target_lines = translated_content.count('\n') + (1 if translated_content else 0)  # 计算翻译结果行数
                line_diff = abs(target_lines - source_lines)
                line_diff_percent = (line_diff / source_lines * 100) if source_lines > 0 else 0
                
                self.translation_logger.info(f"行数检查 - {source_path.name} - 源文件行数: {source_lines} - 翻译结果行数: {target_lines} - 差异: {line_diff} ({line_diff_percent:.2f}%)")
                
                # 如果行数差异超过5%，删除翻译结果文件并抛出错误
                if line_diff_percent > 5:
                    error_msg = f"翻译结果行数差异超过5% - {source_path.name} - 源文件行数: {source_lines} - 翻译结果行数: {target_lines} - 差异: {line_diff_percent:.2f}%"
                    self.translation_logger.error(error_msg)
                    
                    # 删除翻译结果文件
                    try:
                        if target_path.exists():
                            target_path.unlink()
                            self.translation_logger.info(f"已删除翻译结果文件 - {target_path}")
                    except Exception as delete_error:
                        self.translation_logger.warning(f"删除翻译结果文件失败 - {target_path} - 错误: {str(delete_error)}")
                    
                    raise TranslationError(error_msg)
            
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
