"""Digest engine for autotester — chunk-by-chunk keyword extraction.

Chunks are created programmatically (no LLM), stored in ``chunks.json``,
then each chunk is sent sequentially to a local LLM for keyword extraction.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.utils.logging_setup import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DigestSummary:
    """Aggregate result of a completed (or cancelled) digest run."""

    project_name: str
    state: str  # complete | cancelled
    chunks: int
    keywords: int
    duration_seconds: float
    total_words: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "state": self.state,
            "chunks": self.chunks,
            "keywords": self.keywords,
            "duration_seconds": self.duration_seconds,
            "total_words": self.total_words,
        }


# ---------------------------------------------------------------------------
# LazyAIManager
# ---------------------------------------------------------------------------


_DEFAULT_STATE: dict[str, Any] = {
    "state": "queued",
    "total_words": 0,
    "total_chunks": 0,
    "chunks_processed": 0,
    "total_keywords": 0,
    "consecutive_failures": 0,
    "title": "",
    "error": None,
    "updated_at": 0.0,
}

_TERMINAL_STATES = {"complete", "failed"}


class LazyAIManager:
    """Orchestrate one-chunk-at-a-time keyword extraction for a project.

    Uses a ``SemanticSegmenter`` for PDF→text extraction, programmatic
    chunking, and LLM keyword extraction. Maintains ``digest.json`` for
    progress tracking and resume support.
    """

    def __init__(self, segmenter: Any, file_manager: Any) -> None:
        self.segmenter = segmenter
        self.file_manager = file_manager
        self._cancel_events: dict[str, threading.Event] = {}

    # ----- paths ----------------------------------------------------------

    def _project_dir(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name)

    def _state_path(self, project_name: str) -> Path:
        return self._project_dir(project_name) / "digest.json"

    # ----- state persistence ---------------------------------------------

    def _load_state(self, project_name: str) -> dict[str, Any]:
        path = self._state_path(project_name)
        if not path.exists():
            return dict(_DEFAULT_STATE)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(_DEFAULT_STATE)
            merged.update({k: v for k, v in data.items() if k in _DEFAULT_STATE})
            return merged
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULT_STATE)

    def _persist_state(self, project_name: str, **fields: Any) -> dict[str, Any]:
        current = self._load_state(project_name)
        current.update(fields)
        current["updated_at"] = time.time()
        path = self._state_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(path)
        return current

    # ----- public API -----------------------------------------------------

    def ensure_cache(self, project_name: str, pdf_path: Path) -> str:
        """Extract the PDF to ``<project>.txt`` if not already cached.

        Returns the full text. Idempotent.
        """
        text = self.segmenter.ensure_text_cache(project_name, pdf_path)
        state = self._load_state(project_name)
        if not state.get("total_words"):
            total_words = len(text.split())
            self._persist_state(project_name, total_words=total_words)
        return text

    def generate_title(self, project_name: str) -> str:
        """Generate a project title from the first 100 words of the cached text.

        Uses the LLM with ``title_system_prompt`` and ``title_user_prompt_tpl``
        from the IA config. Skips if a title was already generated.

        Returns the title or an empty string on failure. Non-fatal — the
        supervisor continues with chunk processing regardless.
        """
        state = self._load_state(project_name)
        if state.get("title"):
            return state["title"]

        text_cache = self._project_dir(project_name) / f"{project_name}.txt"
        if not text_cache.exists():
            logger.warning("Cannot generate title: no text cache for %s", project_name)
            return ""

        text = text_cache.read_text(encoding="utf-8")
        words = text.split()
        if not words:
            logger.warning("Cannot generate title: empty text for %s", project_name)
            return ""

        first_words = " ".join(words[:100])
        settings = self.segmenter._get_ia_settings()
        model = settings["ollama_model"]
        system_prompt = settings.get(
            "title_system_prompt",
            "You are a helpful assistant that generates concise, descriptive project titles.",
        )
        user_prompt_tpl = settings.get(
            "title_user_prompt_tpl",
            "Based on the following text, generate a short title of 1 to 7 words "
            "that represents the project:\n\n{text}\n\nTitle:",
        )
        prompt = user_prompt_tpl.format(text=first_words)

        logger.info(
            "Title generation started | project=%s model=%s words=%d",
            project_name, model, len(first_words.split()),
        )
        try:
            raw = self.segmenter.llm.generate(
                model, prompt, system=system_prompt, format_json=False,
            )
        except Exception as exc:
            logger.warning(
                "Title generation failed for %s: %s: %s",
                project_name, type(exc).__name__, exc,
            )
            return ""

        title = raw.strip().strip('"').strip("'").strip()
        if title:
            self._persist_state(project_name, title=title)
            logger.info(
                "Title generation finished | project=%s title=%s",
                project_name, title,
            )
        else:
            logger.warning("Title generation returned empty for %s", project_name)
        return title

    def project_status(self, project_name: str) -> dict[str, Any]:
        """Return the current digest state for the project.

        If the project does not exist on disk, returns ``{"state": "error"}``.
        """
        if not self._project_dir(project_name).exists():
            return {"state": "error", "error": "project not found"}
        return self._load_state(project_name)

    def mark_failed(self, project_name: str, reason: str) -> dict[str, Any]:
        """Mark the project as ``failed`` (terminal). Used by the supervisor."""
        return self._persist_state(project_name, state="failed", error=reason)

    def mark_unfailed(self, project_name: str) -> dict[str, Any]:
        """Reset state to ``queued`` and clear error. Keep failure counter."""
        state_data = self._load_state(project_name)
        return self._persist_state(
            project_name,
            state="queued",
            error=None,
            consecutive_failures=state_data.get("consecutive_failures", 0),
        )

    def needs_digest(self, project_name: str) -> bool:
        """Return True if the project still has pending work."""
        if not self._project_dir(project_name).exists():
            return False
        state = self._load_state(project_name)
        if state.get("state") in _TERMINAL_STATES:
            return False
        if state.get("state") == "complete":
            return False
        text_cache = self.file_manager.project_path(project_name) / f"{project_name}.txt"
        if not text_cache.exists():
            return True
        chunks_path = self.segmenter._chunks_json_path(project_name)
        if not chunks_path.exists():
            return True
        processed = int(state.get("chunks_processed", 0))
        total = int(state.get("total_chunks", 0))
        if total == 0:
            return False
        return processed < total

    def process_one_chunk(
        self,
        project_name: str,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> Optional[dict[str, Any]]:
        """Process the next unprocessed chunk; return progress info or ``None`` when done.

        On first call, creates ``chunks.json`` with all chunks marked
        ``text_keywords: null`` (programmatic chunking, no LLM). Then
        sends one chunk at a time to the LLM for keyword extraction.
        """
        state = self._load_state(project_name)
        if state.get("state") in _TERMINAL_STATES:
            return None

        # Create/update state to processing
        self._persist_state(project_name, state="processing")

        text_cache = self.file_manager.project_path(project_name) / f"{project_name}.txt"
        if not text_cache.exists():
            self._persist_state(project_name, state="complete")
            return None

        chunks_path = self.segmenter._chunks_json_path(project_name)

        # First time: create initial chunks.json from the cached text
        if not chunks_path.exists():
            text = text_cache.read_text(encoding="utf-8")
            words = text.split()
            if not words:
                self._persist_state(project_name, state="complete", total_words=0)
                return None
            chunk_tuples = self.segmenter.chunk_text(text)
            total_chunks = len(chunk_tuples)
            if total_chunks == 0:
                self._persist_state(project_name, state="complete", total_words=len(words))
                return None
            texts = [c[0] for c in chunk_tuples]
            self.segmenter._init_chunks(project_name, texts)
            self._persist_state(
                project_name,
                total_words=len(words),
                total_chunks=total_chunks,
                chunks_processed=0,
            )
            state = self._load_state(project_name)

        chunks = self.segmenter._load_chunks(project_name)
        total_chunks = len(chunks)
        processed = int(state.get("chunks_processed", 0))

        if processed >= total_chunks:
            self._persist_state(project_name, state="complete")
            return None

        chunk_data = chunks[processed]
        chunk_text = chunk_data["original_text"]
        chunk_num = processed + 1

        try:
            keywords = self.segmenter.extract_keywords(
                chunk_text,
                model=self.segmenter._get_ia_settings()["ollama_model"],
            )
        except Exception as exc:  # noqa: BLE001
            failures = int(state.get("consecutive_failures", 0)) + 1
            self._persist_state(
                project_name,
                state="error",
                error=f"{type(exc).__name__}: {exc}",
                consecutive_failures=failures,
            )
            raise

        # Update the chunk in chunks.json
        chunks[processed]["text_keywords"] = keywords if keywords else None
        self.segmenter._save_chunks(project_name, chunks)

        current_keywords = int(state.get("total_keywords", 0)) + (len(keywords) if keywords else 0)
        new_processed = processed + 1

        if new_processed >= total_chunks:
            info = {
                "chunk": chunk_num,
                "total_chunks": total_chunks,
                "chunks_processed": new_processed,
                "total_keywords": current_keywords,
                "state": "complete",
                "progress_pct": 100,
            }
            self._persist_state(
                project_name,
                state="complete",
                total_chunks=total_chunks,
                chunks_processed=new_processed,
                total_keywords=current_keywords,
                consecutive_failures=0,
            )
            if on_progress:
                on_progress({"phase": "chunk_done", **info})
            return None

        info = {
            "chunk": chunk_num,
            "total_chunks": total_chunks,
            "chunks_processed": new_processed,
            "total_keywords": current_keywords,
            "state": "processing",
            "progress_pct": int((new_processed / total_chunks) * 100) if total_chunks > 0 else 0,
        }
        self._persist_state(
            project_name,
            total_chunks=total_chunks,
            chunks_processed=new_processed,
            total_keywords=current_keywords,
            consecutive_failures=0,
        )
        if on_progress:
            on_progress({"phase": "chunk_done", **info})
        return info

    def cancel(self, project_name: str) -> None:
        """Signal that a running digest for this project should stop."""
        ev = self._cancel_events.setdefault(project_name, threading.Event())
        ev.set()

    def is_cancelled(self, project_name: str) -> bool:
        return self._cancel_events.get(project_name, threading.Event()).is_set()

    def clear_cancel(self, project_name: str) -> None:
        ev = self._cancel_events.get(project_name)
        if ev:
            ev.clear()

    def run_to_completion(
        self,
        project_name: str,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> DigestSummary:
        """Loop ``process_one_chunk`` until complete or cancelled."""
        started = time.monotonic()
        cleared = False
        while True:
            if self.is_cancelled(project_name) and not cleared:
                self._persist_state(project_name, state="cancelled")
                cleared = True
            if cleared:
                break
            info = self.process_one_chunk(project_name, on_progress=on_progress)
            if info is None:
                break

        duration = time.monotonic() - started
        state = self._load_state(project_name)
        final_state = "cancelled" if cleared else "complete"
        self._persist_state(project_name, state=final_state)
        if on_progress:
            on_progress({"phase": "done", "state": final_state, "duration_seconds": duration})
        return DigestSummary(
            project_name=project_name,
            state=final_state,
            chunks=int(state.get("total_chunks", 0)),
            keywords=int(state.get("total_keywords", 0)),
            duration_seconds=round(duration, 3),
            total_words=int(state.get("total_words", 0)),
        )

    def project_pdf_path(self, project_name: str) -> Optional[Path]:
        """Return the path to the project's PDF, or None if not found."""
        project_dir = self._project_dir(project_name)
        if not project_dir.exists():
            return None
        pdfs = sorted(project_dir.glob("*.pdf"))
        return pdfs[0] if pdfs else None

    def start(self, project_name: str, job_runner: Any) -> str:
        """Schedule ``run_to_completion`` for the project on the job runner.

        Returns the job_id. Idempotent.
        """
        if hasattr(job_runner, "find_by_project"):
            existing = job_runner.find_by_project(project_name)
            if existing:
                return existing
        pdf = self.project_pdf_path(project_name)
        if pdf is None:
            raise FileNotFoundError(f"No PDF found for project {project_name!r}")
        self.clear_cancel(project_name)
        job_id = job_runner.submit(self._run_wrapper, project_name, pdf)
        if hasattr(job_runner, "register_project"):
            job_runner.register_project(job_id, project_name)
        return job_id

    def _run_wrapper(self, project_name: str, pdf_path: Path) -> dict[str, Any]:
        """Process a single chunk for the project.

        Called once per supervisor iteration. The ``.txt`` cache is created
        on first call if missing.
        """
        state = self._load_state(project_name)
        if state.get("state") == "failed":
            return {"state": "failed"}
        try:
            self.ensure_cache(project_name, pdf_path)
        except FileNotFoundError as exc:
            self.mark_failed(project_name, f"{type(exc).__name__}: {exc}")
            return {"state": "failed", "error": str(exc)}
        info = self.process_one_chunk(project_name)
        if info is None:
            return {"state": "complete"}
        return info
