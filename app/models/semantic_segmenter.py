"""Semantic segmentation engine for autotester.

Replaces the old RAG/ChromaDB pipeline. Extracts raw text from a PDF,
splits it into word-based chunks, sends each chunk to a local LLM (via
Ollama) for concept grouping and keyword extraction, and persists the
results incrementally to ``chunks.json``.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from app.utils.logging_setup import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SemanticRecord:
    """A single processed chunk stored in ``chunks.json``."""

    original_text: str
    text_keywords: list[str]
    last_index: int  # word index in the original text where this chunk ends

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Semantic segmenter
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are a semantic text analyzer. Your task is to group related concepts "
    "together, maintain the original meaning and flow, and extract key keywords "
    "from each text chunk."
)

_USER_PROMPT_TPL = (
    'Analyze the following text chunk. Group related concepts, maintain the '
    'original meaning and coherence, and extract 3-7 keywords that represent '
    'the main topics.\n\n'
    'Text:\n{text}\n\n'
    'Return ONLY valid JSON with exactly these fields (no markdown, no extra text):\n'
    '{{"original_text": "the semantically grouped text", "text_keywords": ["kw1", "kw2", ...]}}'
)


def _chunk_text_by_words(text: str, chunk_size: int, chunk_overlap: int) -> list[tuple[str, int, int]]:
    """Split text into word-count-based chunks.

    Returns list of ``(chunk_text, start_word_index, end_word_index)``.
    ``end_word_index`` is exclusive (Python slice convention).
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

    words = text.split()
    if not words:
        return []

    step = chunk_size - chunk_overlap
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append((chunk_text, start, end))
        if end == len(words):
            break
        start += step

    return chunks


def _parse_llm_response(raw: str) -> dict[str, Any]:
    """Parse the LLM response JSON, with fallback for common wrapping."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("LLM returned an empty response — check that the model is installed and the prompt is valid")
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("LLM response was only markdown fences with no content")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("LLM response is not valid JSON (first 500 chars): %s", raw[:500])
        raise ValueError(
            f"LLM response is not valid JSON: {exc}. First 200 characters: {raw[:200]}"
        ) from exc
    if not isinstance(data.get("original_text"), str):
        raise ValueError("LLM response missing 'original_text'")
    if not isinstance(data.get("text_keywords"), list):
        raise ValueError("LLM response missing 'text_keywords' array")
    return data


class SemanticSegmenter:
    """Orchestrate PDF text extraction, chunking, LLM processing and JSON persistence."""

    def __init__(
        self,
        config_manager: Any,
        file_manager: Any,
        llm_client: Any | None = None,
        request_timeout: float = 60.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self.config_manager = config_manager
        self.file_manager = file_manager
        from app.models.llm_client import OllamaChatClient

        self.llm = llm_client or OllamaChatClient(
            base_url=self._get_ia_settings()["ollama_url"],
            timeout=request_timeout,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
        self.request_timeout = request_timeout

    # ----- configuration -------------------------------------------------

    def _get_ia_settings(self) -> dict[str, Any]:
        cfg = self.config_manager.load()
        defaults = {
            "ollama_url": "http://localhost:11434",
            "ollama_model": "qwen3.5:latest",
            "chunk_size": 400,
            "chunk_overlap": 50,
            "system_prompt": _SYSTEM_PROMPT,
            "user_prompt_tpl": _USER_PROMPT_TPL,
        }
        ia = cfg.get("ia") or {}
        merged = dict(defaults)
        if isinstance(ia, dict):
            merged.update(ia)
        return merged

    def validate_ollama(self, url: str | None = None) -> tuple[bool, str]:
        """Check that Ollama is reachable. Returns ``(ok, message)``."""
        target_url = url or self._get_ia_settings()["ollama_url"]
        from app.models.llm_client import OllamaChatClient

        client = OllamaChatClient(
            base_url=target_url,
            timeout=5.0,
        )
        if not client.is_available():
            return False, f"Ollama not reachable at {target_url}"
        return True, f"Ollama reachable at {target_url}"

    # ----- PDF extraction ------------------------------------------------

    def extract_text(self, pdf_path: Path) -> str:
        """Return the full text of a PDF as a single string."""
        import fitz

        doc = fitz.open(str(pdf_path))
        try:
            pages = [page.get_text("text") or "" for page in doc]
        finally:
            doc.close()
        return "\n".join(pages)

    # ----- chunking ------------------------------------------------------

    def chunk_text(self, text: str) -> list[tuple[str, int, int]]:
        """Split text into word-count chunks based on current config."""
        settings = self._get_ia_settings()
        return _chunk_text_by_words(
            text,
            chunk_size=int(settings["chunk_size"]),
            chunk_overlap=int(settings["chunk_overlap"]),
        )

    # ----- LLM processing -----------------------------------------------

    def process_chunk(self, chunk_text: str, model: str) -> tuple[str, list[str]]:
        """Send a chunk to the LLM and return ``(original_text, keywords)``."""
        settings = self._get_ia_settings()
        system_prompt = settings["system_prompt"]
        user_prompt_tpl = settings["user_prompt_tpl"]
        prompt = user_prompt_tpl.format(text=chunk_text)
        logger.info(
            "LLM call | model=%s chunk_words=%d chunk_preview=%.200s prompt_preview=%.200s system_len=%d",
            model,
            len(chunk_text.split()),
            chunk_text,
            prompt,
            len(system_prompt),
        )
        raw = self.llm.generate(model, prompt, system=system_prompt)
        logger.info(
            "LLM response | model=%s response_chars=%d response_preview=%.200s",
            model,
            len(raw),
            raw,
        )
        if not raw or not raw.strip():
            logger.error("LLM returned empty content for model %s", model)
            raise ValueError(
                f"LLM returned empty response for model {model!r}. "
                "Verify the model is installed: run 'ollama pull {model}'"
            )
        data = _parse_llm_response(raw)
        return data["original_text"], data["text_keywords"]

    # ----- JSON persistence ----------------------------------------------

    def _chunks_json_path(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name) / "chunks.json"

    def _text_cache_path(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name) / f"{project_name}.txt"

    def _load_chunks(self, project_name: str) -> list[dict[str, Any]]:
        path = self._chunks_json_path(project_name)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _append_chunk(self, project_name: str, record: SemanticRecord) -> None:
        path = self._chunks_json_path(project_name)
        existing = self._load_chunks(project_name)
        existing.append(record.to_dict())
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # ----- full pipeline -------------------------------------------------

    def ensure_text_cache(self, project_name: str, pdf_path: Path) -> str:
        """Extract PDF text to ``<project>.txt`` if not already cached.

        Returns the full text. Idempotent.
        """
        cache = self._text_cache_path(project_name)
        if cache.exists():
            return cache.read_text(encoding="utf-8")
        text = self.extract_text(pdf_path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(cache)
        return text

    def run_pipeline(
        self,
        project_name: str,
        pdf_path: Path,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run the full semantic segmentation pipeline.

        Steps:
        1. Extract raw text (or load cached ``.txt``).
        2. Compute total word count.
        3. Chunk text by words.
        4. For each unprocessed chunk, call LLM and persist to ``chunks.json``.

        Returns a summary dict with ``project_name``, ``total_chunks``,
        ``chunks_processed``, ``total_keywords``, ``duration_seconds``.
        """
        settings = self._get_ia_settings()
        model = settings["ollama_model"]

        logger.info(
            "Semantic digest started: project=%s pdf=%s model=%s",
            project_name, pdf_path, model,
        )
        started = time.monotonic()

        text = self.ensure_text_cache(project_name, pdf_path)
        words = text.split()
        total_words = len(words)
        chunks = self.chunk_text(text)

        logger.debug(
            "Extracted %d words, %d chunks from %s",
            total_words, len(chunks), pdf_path.name,
        )

        if not chunks:
            # No text — nothing to process.
            duration = time.monotonic() - started
            logger.info(
                "Semantic digest finished (no chunks): project=%s duration=%.3fs",
                project_name, duration,
            )
            return {
                "project_name": project_name,
                "total_chunks": 0,
                "chunks_processed": 0,
                "total_keywords": 0,
                "duration_seconds": round(duration, 3),
                "total_words": total_words,
            }

        # Determine where to resume: count already-persisted records.
        existing = self._load_chunks(project_name)
        resume_index = len(existing)

        total_keywords = sum(len(r.get("text_keywords", [])) for r in existing)

        for i in range(resume_index, len(chunks)):
            chunk_text, start_word, end_word = chunks[i]
            logger.debug(
                "Processing chunk %d/%d (words %d-%d)",
                i + 1, len(chunks), start_word, end_word,
            )

            try:
                grouped_text, keywords = self.process_chunk(chunk_text, model)
            except Exception as exc:
                logger.error(
                    "Chunk %d/%d failed for project %s: %s: %s",
                    i + 1, len(chunks), project_name,
                    type(exc).__name__, exc,
                )
                raise

            record = SemanticRecord(
                original_text=grouped_text,
                text_keywords=keywords,
                last_index=end_word,
            )
            self._append_chunk(project_name, record)
            total_keywords += len(keywords)

            progress_pct = int((end_word / total_words) * 100) if total_words > 0 else 100
            if on_progress:
                on_progress({
                    "phase": "chunk_done",
                    "chunk": i + 1,
                    "total_chunks": len(chunks),
                    "progress_pct": progress_pct,
                    "keywords_so_far": total_keywords,
                    "last_index": end_word,
                })

        duration = time.monotonic() - started
        summary = {
            "project_name": project_name,
            "total_chunks": len(chunks),
            "chunks_processed": len(chunks),
            "total_keywords": total_keywords,
            "duration_seconds": round(duration, 3),
            "total_words": total_words,
        }
        logger.info(
            "Semantic digest finished: project=%s chunks=%s keywords=%s duration=%.3fs",
            project_name, len(chunks), total_keywords, duration,
        )
        if on_progress:
            on_progress({"phase": "done", **summary})
        return summary
