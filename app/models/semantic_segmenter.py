"""Semantic segmentation engine for autotester.

Splits PDF text into word-based chunks programmatically, sends each chunk
to a local LLM (via Ollama) for keyword extraction, and returns chunk dicts
with page numbers. Chunk persistence is handled by the caller (digest.json).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.models.config_manager import _DEFAULT_SYSTEM_PROMPT, _DEFAULT_USER_PROMPT_TPL
from app.utils.logging_setup import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SemanticRecord:
    """A single processed chunk."""

    original_text: str
    text_keywords: list[str] | None
    page_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Semantic segmenter
# ---------------------------------------------------------------------------


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


def _parse_keywords_response(raw: str) -> list[str]:
    """Parse the LLM response JSON and return the keywords list.

    Expects ``{"text_keywords": ["kw1", "kw2", ...]}``.
    Returns the list (may be empty).
    """
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("LLM returned an empty response — check that the model is installed and the prompt is valid")
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1:]
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
    if not isinstance(data.get("text_keywords"), list):
        raise ValueError("LLM response missing 'text_keywords' array")
    return data["text_keywords"]


class SemanticSegmenter:
    """Orchestrate PDF text extraction, chunking, LLM keyword extraction and JSON persistence."""

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
            "ollama_url": "http://dummy-server",
            "ollama_model": None,
            "chunk_size": 100,
            "chunk_overlap": 10,
            "system_prompt": _DEFAULT_SYSTEM_PROMPT,
            "user_prompt_tpl": _DEFAULT_USER_PROMPT_TPL,
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
        pages = self.extract_text_by_page(pdf_path)
        return "\n".join(t for _, t in pages)

    def extract_text_by_page(self, pdf_path: Path) -> list[tuple[int, str]]:
        """Extract PDF text per page.

        Returns a list of ``(page_number_1_indexed, page_text)`` tuples.
        """
        import fitz

        doc = fitz.open(str(pdf_path))
        try:
            pages = [(i + 1, page.get_text("text") or "") for i, page in enumerate(doc)]
        finally:
            doc.close()
        return pages

    # ----- chunking ------------------------------------------------------

    def chunk_text(self, text: str) -> list[tuple[str, int, int]]:
        """Split text into word-count chunks based on current config."""
        settings = self._get_ia_settings()
        return _chunk_text_by_words(
            text,
            chunk_size=int(settings["chunk_size"]),
            chunk_overlap=int(settings["chunk_overlap"]),
        )

    # ----- LLM keyword extraction ---------------------------------------

    def extract_keywords(self, chunk_text: str, model: str) -> list[str]:
        """Send a chunk to the LLM and return the extracted keywords list."""
        settings = self._get_ia_settings()
        system_prompt = settings["system_prompt"]
        user_prompt_tpl = settings["user_prompt_tpl"]
        prompt = user_prompt_tpl.format(text=chunk_text)
        logger.info(
            "LLM call | model=%s chunk_words=%d chunk_preview=%.200s",
            model,
            len(chunk_text.split()),
            chunk_text,
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
        return _parse_keywords_response(raw)

    # ----- page-word boundary helpers ------------------------------------

    @staticmethod
    def _compute_page_word_ranges(pages: list[tuple[int, str]]) -> list[tuple[int, int, int]]:
        """Build page word ranges from per-page extracted text.

        Returns ``[(page_num, start_word_index, end_word_index_exclusive), ...]``.
        """
        ranges: list[tuple[int, int, int]] = []
        offset = 0
        for page_num, page_text in pages:
            word_count = len(page_text.split())
            end = offset + word_count
            ranges.append((page_num, offset, end))
            offset = end
        return ranges

    @staticmethod
    def _page_number_from_word_index(word_idx: int, page_ranges: list[tuple[int, int, int]]) -> int:
        """Return the 1-indexed page number containing the given word index."""
        for page_num, start, end in page_ranges:
            if start <= word_idx < end:
                return page_num
        return page_ranges[-1][0] if page_ranges else 1

    # ----- chunk dict builder -------------------------------------------

    def _build_chunk_dicts(
        self,
        texts: list[str],
        page_numbers: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Build chunk dicts with ``page_number``.

        Returns ``[{"original_text": ..., "text_keywords": None, "page_number": N}, ...]``.
        Does NOT write to disk.
        """
        chunks: list[dict[str, Any]] = []
        for i, t in enumerate(texts):
            chunks.append({
                "original_text": t,
                "text_keywords": None,
                "page_number": page_numbers[i] if page_numbers else None,
            })
        return chunks

    # ----- full pipeline -------------------------------------------------

    def ensure_text_cache(self, project_name: str, pdf_path: Path) -> str:
        """Extract PDF text and return it.

        No disk caching. Always re-extracts from the PDF.
        Returns the full text.
        """
        return self.extract_text(pdf_path)
