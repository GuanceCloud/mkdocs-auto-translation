import logging
import os
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from openai import OpenAI

from .languages import get_profile
from .protection import ProtectionError, protect_document, strip_single_outer_fence
from .prompts import build_prompt_bundle
from .terminology import load_terminology
from .validation import ValidationError, contains_han_in_translatable_text, validate_translation


MAX_RETRIES = 3
REQUEST_TIMEOUT = 120
ProgressCallback = Callable[[int], None]


class TranslationError(RuntimeError):
    """Raised when translation fails after retries or validation."""


class DocumentTranslator:
    """Translate one document at a time for a fixed target language."""

    def __init__(
        self,
        target_lang: str,
        response_mode: str = "streaming",
        api_key: Optional[str] = None,
        check_chinese: bool = False,
        check_line_count: bool = False,
        check_structure: bool = True,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
        system_prompt: Optional[str] = None,
        client=None,
    ):
        self.profile = get_profile(target_lang)
        self.target_lang = self.profile.code
        if response_mode not in {"streaming", "blocking"}:
            raise ValueError("response_mode must be 'streaming' or 'blocking'")
        self.response_mode = response_mode
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if client is None and not self.api_key:
            raise ValueError(
                "API key must be provided either through --api-key or OPENAI_API_KEY"
            )
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model
        self.client = client or OpenAI(api_key=self.api_key, base_url=self.base_url)
        if system_prompt is None:
            terminology_set = load_terminology()
            terminology, _ = terminology_set.for_language(self.target_lang)
            concepts, _ = terminology_set.concepts_for_language(self.target_lang)
            system_prompt = build_prompt_bundle(
                self.profile, terminology, concepts=concepts
            ).system_prompt
        self.system_prompt = system_prompt
        self.check_chinese = check_chinese and self.profile.supports_han_residual_check
        self.check_line_count = check_line_count
        self.check_structure = check_structure
        self.translation_logger = logging.getLogger("translation")

    def _contains_chinese(self, text: str) -> bool:
        return contains_han_in_translatable_text(text)

    @staticmethod
    def _usage_dict(usage) -> Optional[Dict[str, int]]:
        if usage is None:
            return None
        return {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }

    def _request(self, messages: List[Dict], desc: str, progress_callback: Optional[ProgressCallback]):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                if self.response_mode == "streaming":
                    stream = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.1,
                        timeout=REQUEST_TIMEOUT,
                        stream=True,
                    )
                    pieces = []
                    usage = None
                    chunks = 0
                    for chunk in stream:
                        chunk_usage = getattr(chunk, "usage", None)
                        if chunk_usage is not None:
                            usage = chunk_usage
                        choices = getattr(chunk, "choices", None) or []
                        if choices:
                            content = getattr(getattr(choices[0], "delta", None), "content", None)
                            if content:
                                pieces.append(content)
                                chunks += 1
                                if progress_callback:
                                    progress_callback(chunks)
                    return "".join(pieces), self._usage_dict(usage)

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=REQUEST_TIMEOUT,
                )
                content = response.choices[0].message.content
                return content or "", self._usage_dict(getattr(response, "usage", None))
            except Exception as exc:
                last_error = exc
                self.translation_logger.warning(
                    "[%s] request attempt %s/%s failed for %s: %s",
                    self.target_lang,
                    attempt + 1,
                    MAX_RETRIES,
                    desc,
                    exc,
                )
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(2**attempt)
        raise TranslationError(f"API request failed after {MAX_RETRIES} attempts: {last_error}")

    def translate_text(
        self,
        text: str,
        desc: str = "Translating",
        progress_callback: Optional[ProgressCallback] = None,
        **_legacy_progress_args,
    ) -> Tuple[str, Dict]:
        started = datetime.now(timezone.utc)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "<input>\n"
                    f"<input_content>{text}</input_content>\n"
                    f"<target_language>{self.profile.model_name}</target_language>\n"
                    "</input>"
                ),
            },
        ]
        translated, usage = self._request(messages, desc, progress_callback)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return translated, {"usage": usage, "translation_time": round(elapsed, 2)}

    def translate_file(
        self,
        source_path: Path,
        target_path: Path,
        desc: str = "Translating",
        progress_callback: Optional[ProgressCallback] = None,
        **_legacy_progress_args,
    ) -> Tuple[bool, Dict]:
        temporary_path: Optional[Path] = None
        try:
            source_text = source_path.read_text(encoding="utf-8")
            protected_document = None
            translation_input = source_text
            if self.check_structure:
                protected_document = protect_document(
                    source_text,
                    is_pages=source_path.name == ".pages" or source_path.suffix == ".pages",
                )
                translation_input = protected_document.masked_text
            translated_text, metadata = self.translate_text(
                translation_input,
                desc=desc,
                progress_callback=progress_callback,
            )
            if protected_document is not None:
                translated_text = strip_single_outer_fence(translated_text)
                translated_text = protected_document.restore(translated_text)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target_path.name}.", suffix=".tmp", dir=target_path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(translated_text)
                handle.flush()
                os.fsync(handle.fileno())
            target_mode = stat.S_IMODE(target_path.stat().st_mode) if target_path.exists() else 0o644
            os.chmod(temporary_path, target_mode)
            validate_translation(
                source_text,
                temporary_path.read_text(encoding="utf-8"),
                source_path,
                check_chinese=self.check_chinese,
                check_line_count=self.check_line_count,
                check_structure=self.check_structure,
            )
            os.replace(temporary_path, target_path)
            temporary_path = None
            return True, metadata
        except (OSError, ProtectionError, TranslationError, ValidationError, UnicodeError, ValueError) as exc:
            self.translation_logger.error("[%s] translation failed for %s: %s", self.target_lang, desc, exc)
            return False, {"error_message": str(exc)}
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def close_progress_bars(self) -> None:
        """Compatibility no-op; progress is managed by the CLI."""
