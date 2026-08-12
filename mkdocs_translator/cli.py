import concurrent.futures
import json
import logging
import os
import queue
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from tqdm import tqdm

from .languages import get_profile, normalize_language, parse_languages
from .metadata import METADATA_VERSION, MetadataManager
from .prompts import PromptBundle, build_prompt_bundle
from .terminology import TerminologyError, load_terminology
from .translator import DocumentTranslator
from .utils import copy_resources, get_translatable_files, is_blacklisted, load_blacklist


@dataclass(frozen=True)
class TranslationTask:
    language: str
    source_file: Path
    relative_path: Path


@dataclass
class LanguageContext:
    language: str
    target_dir: Path
    prompt: PromptBundle
    metadata: MetadataManager
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: List[Dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: str, relative_path: Path, details: Optional[Dict] = None) -> None:
        details = details or {}
        with self.lock:
            if status == "success":
                self.success += 1
            elif status == "failed":
                self.failed += 1
            elif status == "skipped":
                self.skipped += 1
            result = {"path": relative_path.as_posix(), "status": status}
            result.update(details)
            self.results.append(result)


class ProgressReporter:
    def __init__(self, total: int, worker_totals: List[int], contexts: Dict[str, LanguageContext]):
        self.total = total
        self.worker_count = len(worker_totals)
        self.contexts = contexts
        self.lock = threading.RLock()
        self.disabled = not sys.stderr.isatty() or total == 0
        self.worker_bars = [
            tqdm(
                desc=f"Worker {index + 1}: waiting",
                total=worker_total,
                position=index,
                unit="tasks",
                bar_format="{desc} {percentage:3.0f}%|{bar}| [{n_fmt}/{total_fmt}]",
                dynamic_ncols=True,
                leave=False,
                disable=self.disabled,
            )
            for index, worker_total in enumerate(worker_totals)
        ]
        self.total_bar = tqdm(
            total=total,
            desc=self._total_description(),
            unit="tasks",
            position=self.worker_count,
            dynamic_ncols=True,
            disable=self.disabled,
        )

    def _total_description(self) -> str:
        language_counts = " ".join(
            f"{language}:✓{context.success}/✗{context.failed}/↷{context.skipped}"
            for language, context in self.contexts.items()
        )
        return f"Total [{language_counts}]"

    def start(self, worker_id: int, task: TranslationTask) -> None:
        with self.lock:
            self.worker_bars[worker_id].set_description(
                f"Worker {worker_id + 1}: [{task.language}] {task.relative_path.as_posix()}"
            )
            self.worker_bars[worker_id].refresh()

    def chunks(self, worker_id: int, task: TranslationTask, count: int) -> None:
        if count % 10:
            return
        with self.lock:
            self.worker_bars[worker_id].set_description(
                f"Worker {worker_id + 1}: [{task.language}] {task.relative_path.as_posix()} [{count} chunks]"
            )
            self.worker_bars[worker_id].refresh()

    def complete(self, worker_id: int) -> None:
        with self.lock:
            worker_bar = self.worker_bars[worker_id]
            worker_bar.update(1)
            state = "done" if worker_bar.n >= worker_bar.total else "waiting"
            worker_bar.set_description(f"Worker {worker_id + 1}: {state}")
            worker_bar.refresh()
            self.total_bar.set_description(self._total_description())
            self.total_bar.update(1)

    def close(self) -> None:
        for bar in self.worker_bars:
            bar.close()
        self.total_bar.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_task_totals(task_count: int, worker_count: int) -> List[int]:
    """Return balanced fixed task quotas so every worker has a visible total."""
    if worker_count <= 0:
        return []
    base, remainder = divmod(task_count, worker_count)
    return [base + (1 if index < remainder else 0) for index in range(worker_count)]


def _is_blank_source(path: Path) -> bool:
    """Return whether a UTF-8 source contains only a BOM and whitespace."""
    return not path.read_text(encoding="utf-8-sig").strip()


def _copy_blank_source(source_file: Path, target_file: Path) -> None:
    """Synchronize a blank source verbatim without sending it for translation."""
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_file, target_file)


def _resolve_target_directories(target: Path, languages: Tuple[str, ...], multi_mode: bool) -> Dict[str, Path]:
    return {
        language: (target / language if multi_mode else target).resolve()
        for language in languages
    }


def _validate_paths(source: Path, target_directories: Dict[str, Path]) -> None:
    resolved_values = list(target_directories.values())
    if len(set(resolved_values)) != len(resolved_values):
        raise click.UsageError("Target language directories resolve to the same path")
    for language, target_dir in target_directories.items():
        if target_dir == source or source in target_dir.parents:
            raise click.UsageError(
                f"Target directory for '{language}' must not be the source directory or be inside it: {target_dir}"
            )


def _validate_existing_metadata(target_directories: Dict[str, Path]) -> None:
    for language, target_dir in target_directories.items():
        metadata_path = target_dir / ".mkdocs-translator" / "metadata.json"
        if not metadata_path.exists():
            continue
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise click.UsageError(f"Cannot read metadata file {metadata_path}: {exc}") from exc
        if metadata.get("version") != METADATA_VERSION:
            raise click.UsageError(f"Unsupported metadata format in {metadata_path}")
        if metadata.get("target_language") != language:
            raise click.UsageError(
                f"Target directory {target_dir} is bound to language "
                f"'{metadata.get('target_language')}', not '{language}'"
            )


def _aggregate_usage(results: List[Dict]) -> Optional[Dict[str, int]]:
    usages = [result.get("usage") for result in results if result.get("usage") is not None]
    if not usages:
        return None
    return {
        key: sum(int(usage.get(key, 0) or 0) for usage in usages)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def _collect_failures(contexts: Dict[str, LanguageContext]) -> List[Tuple[str, str, str]]:
    failures: List[Tuple[str, str, str]] = []
    for language, context in contexts.items():
        for result in context.results:
            if result.get("status") != "failed":
                continue
            reason = " ".join(str(result.get("error_message") or "Unknown failure").splitlines())
            failures.append((language, str(result["path"]), reason))
    return sorted(failures, key=lambda item: (item[0], item[1]))


@click.command()
@click.option("--source", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path), help="Source Chinese document directory")
@click.option("--target", required=True, type=click.Path(file_okay=False, path_type=Path), help="Language directory in single mode, or language root in multi-language mode")
@click.option("--target-language", help="One target language: en, ja, or ko")
@click.option("--target-languages", help="Comma-separated target languages; --target is their common root")
@click.option("--glossary", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Custom YAML terminology overrides")
@click.option("--api-key", help="LLM API key (compatible with OpenAI format)")
@click.option("--base-url", help="LLM API base URL")
@click.option("--model", default="gpt-4o", show_default=True, help="Model name")
@click.option("--response-mode", type=click.Choice(["streaming", "blocking"]), default="streaming", show_default=True)
@click.option("--workers", type=int, default=1, show_default=True, help="Global maximum concurrent translation tasks")
@click.option("--overwrite-resources", is_flag=True, help="Overwrite existing resource files")
@click.option("--delete-removed-resources", is_flag=True, help="Delete target resources removed from source")
@click.option("--delete-removed-translations", is_flag=True, help="Delete translated documents removed or blacklisted in source")
@click.option("--check-chinese", is_flag=True, help="Reject residual Chinese text for English and Korean")
@click.option("--check-line-count", is_flag=True, help="Reject translations whose line count differs by more than 5%")
@click.option(
    "--check-structure/--no-check-structure",
    default=True,
    show_default=True,
    help="Protect and validate Markdown/YAML structure; disabling accepts raw model output",
)
def translate(
    source: Path,
    target: Path,
    target_language: Optional[str],
    target_languages: Optional[str],
    glossary: Optional[Path],
    api_key: Optional[str],
    base_url: Optional[str],
    model: str,
    response_mode: str,
    workers: int,
    overwrite_resources: bool,
    delete_removed_resources: bool,
    delete_removed_translations: bool,
    check_chinese: bool,
    check_line_count: bool,
    check_structure: bool,
) -> None:
    """Translate Chinese MkDocs documents into English, Japanese, and/or Korean."""
    logging.basicConfig(
        filename="translation.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        encoding="utf-8",
    )
    if bool(target_language) == bool(target_languages):
        raise click.UsageError("Provide exactly one of --target-language or --target-languages")
    if workers < 1:
        raise click.UsageError("--workers must be at least 1")
    if not check_structure:
        warning = (
            "Structure protection and validation are disabled; model changes to links, code, "
            "HTML, templates, and .pages structure will not be rejected."
        )
        click.echo(f"Warning: {warning}", err=True)
        logging.warning(warning)

    try:
        languages = (
            (normalize_language(target_language),)
            if target_language
            else parse_languages(target_languages or "")
        )
        terminology = load_terminology(glossary)
    except (ValueError, TerminologyError) as exc:
        raise click.UsageError(str(exc)) from exc

    source = source.resolve()
    target = target.resolve()
    multi_mode = target_languages is not None
    target_directories = _resolve_target_directories(target, languages, multi_mode)
    _validate_paths(source, target_directories)
    _validate_existing_metadata(target_directories)

    effective_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not effective_api_key:
        raise click.UsageError("API key must be provided through --api-key or OPENAI_API_KEY")

    prompts: Dict[str, PromptBundle] = {}
    for language in languages:
        terms, missing = terminology.for_language(language)
        concepts, missing_concepts = terminology.concepts_for_language(language)
        missing = tuple(dict.fromkeys((*missing, *missing_concepts)))
        profile = get_profile(language)
        prompts[language] = build_prompt_bundle(profile, terms, missing, concepts)
        if missing:
            logging.warning(
                "[%s] %s glossary terms have no translation and will be handled by the model: %s",
                language,
                len(missing),
                ", ".join(missing),
            )
        if check_chinese and not profile.supports_han_residual_check:
            logging.info("[%s] Chinese residual check disabled because Japanese uses Han characters", language)

    contexts: Dict[str, LanguageContext] = {}
    try:
        for language in languages:
            target_dir = target_directories[language]
            metadata = MetadataManager(
                target_dir=target_dir,
                source_dir=source,
                target_language=language,
                translation_fingerprint=prompts[language].fingerprint,
                migrate_legacy=True,
            )
            contexts[language] = LanguageContext(language, target_dir, prompts[language], metadata)
        for context in contexts.values():
            copy_resources(
                source,
                context.target_dir,
                overwrite_resources=overwrite_resources,
                delete_removed_resources=delete_removed_resources,
            )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    blacklist = load_blacklist(source / ".translate-blacklist")
    source_files = [
        path
        for path in get_translatable_files(source)
        if not is_blacklisted(path.relative_to(source), blacklist)
    ]
    valid_relative_paths = [path.relative_to(source) for path in source_files]
    if delete_removed_translations:
        for context in contexts.values():
            context.metadata.delete_removed_translations(valid_relative_paths)

    tasks: List[TranslationTask] = []
    for source_file in source_files:
        relative_path = source_file.relative_to(source)
        blank_source = _is_blank_source(source_file)
        for language in languages:
            context = contexts[language]
            if context.metadata.needs_translation(relative_path):
                if blank_source:
                    _copy_blank_source(source_file, context.target_dir / relative_path)
                    details = {"reason": "blank_source", "translation_time": 0}
                    context.metadata.update_file_status(relative_path, True, details)
                    context.record("skipped", relative_path, details)
                else:
                    tasks.append(TranslationTask(language, source_file, relative_path))
            else:
                context.record("skipped", relative_path)

    run_id = str(uuid.uuid4())
    started_at = _utc_now()
    worker_count = min(workers, len(tasks)) if tasks else 0
    worker_totals = _worker_task_totals(len(tasks), worker_count)
    progress = ProgressReporter(len(tasks), worker_totals, contexts)
    task_queue: queue.Queue[TranslationTask] = queue.Queue()
    for task in tasks:
        task_queue.put(task)
    stop_event = threading.Event()

    def worker_loop(worker_id: int) -> None:
        translators: Dict[str, DocumentTranslator] = {}
        for _ in range(worker_totals[worker_id]):
            if stop_event.is_set():
                return
            try:
                task = task_queue.get_nowait()
            except queue.Empty:
                return
            context = contexts[task.language]
            progress.start(worker_id, task)
            try:
                translator = translators.get(task.language)
                if translator is None:
                    translator = DocumentTranslator(
                        target_lang=task.language,
                        response_mode=response_mode,
                        api_key=effective_api_key,
                        check_chinese=check_chinese,
                        check_line_count=check_line_count,
                        check_structure=check_structure,
                        base_url=base_url,
                        model=model,
                        system_prompt=context.prompt.system_prompt,
                    )
                    translators[task.language] = translator
                target_file = context.target_dir / task.relative_path
                success, details = translator.translate_file(
                    task.source_file,
                    target_file,
                    desc=f"[{task.language}] {task.relative_path.as_posix()}",
                    progress_callback=lambda count, t=task: progress.chunks(worker_id, t, count),
                )
                if success:
                    context.metadata.update_file_status(task.relative_path, True, details)
                    context.record("success", task.relative_path, details)
                else:
                    context.metadata.update_file_status(task.relative_path, False, details)
                    context.record("failed", task.relative_path, details)
            except Exception as exc:
                details = {"error_message": str(exc)}
                logging.exception("[%s] unexpected task failure for %s", task.language, task.relative_path)
                try:
                    context.metadata.update_file_status(task.relative_path, False, details)
                except Exception:
                    logging.exception("Failed to persist task error metadata")
                context.record("failed", task.relative_path, details)
            finally:
                task_queue.task_done()
                progress.complete(worker_id)

    interrupted = False
    if worker_count:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=worker_count)
        futures = [executor.submit(worker_loop, worker_id) for worker_id in range(worker_count)]
        try:
            for future in concurrent.futures.as_completed(futures):
                future.result()
        except KeyboardInterrupt:
            interrupted = True
            stop_event.set()
            for future in futures:
                future.cancel()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
    progress.close()

    finished_at = _utc_now()
    pending = task_queue.qsize()
    for context in contexts.values():
        report = {
            "version": 1,
            "run_id": run_id,
            "target_language": context.language,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "interrupted" if interrupted else ("partial_failure" if context.failed else "success"),
            "counts": {
                "success": context.success,
                "failed": context.failed,
                "skipped": context.skipped,
            },
            "usage": _aggregate_usage(context.results),
            "files": sorted(context.results, key=lambda result: result["path"]),
        }
        if interrupted:
            report["pending_tasks_across_languages"] = pending
        context.metadata.write_last_run(report)

    click.echo("Translation completed")
    total_success = total_failed = total_skipped = 0
    for language, context in contexts.items():
        click.echo(
            f"{language}: success={context.success}, failed={context.failed}, skipped={context.skipped}"
        )
        total_success += context.success
        total_failed += context.failed
        total_skipped += context.skipped
    click.echo(
        f"total: success={total_success}, failed={total_failed}, skipped={total_skipped}"
    )
    failures = _collect_failures(contexts)
    if failures:
        click.echo(f"Failed translations ({len(failures)}):")
        logging.error("Translation failure summary: %d failed task(s)", len(failures))
        for language, path, reason in failures:
            click.echo(f"- [{language}] {path}: {reason}")
            logging.error("FAILED [%s] %s: %s", language, path, reason)
    if interrupted:
        raise click.exceptions.Exit(130)
    if total_failed:
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    translate()
