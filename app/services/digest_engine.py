"""Digest engine for autotester — chunk-by-chunk keyword extraction.

Chunks are created programmatically (no LLM), stored inside ``digest.json``
as the ``chunks`` key, then each chunk is sent sequentially to a local LLM
for keyword extraction.
"""
from __future__ import annotations

import json
import random
import re
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
    "language": "",
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

    def __init__(
        self,
        segmenter: Any,
        file_manager: Any,
        game_manager: Any = None,
        question_generator: Any = None,
        config_manager: Any = None,
    ) -> None:
        self.segmenter = segmenter
        self.file_manager = file_manager
        self.game_manager = game_manager
        self.question_generator = question_generator
        self.config_manager = config_manager
        self._cancel_events: dict[str, threading.Event] = {}
        self._question_gen_active: set[str] = set()

    # ----- paths ----------------------------------------------------------

    def _project_dir(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name)

    def _state_path(self, project_name: str) -> Path:
        return self._project_dir(project_name) / "digest.json"

    # ----- state + chunk persistence -------------------------------------

    def _read_full_state(self, project_name: str) -> dict[str, Any]:
        """Read the raw digest.json dict (state keys + chunks)."""
        path = self._state_path(project_name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_state(self, project_name: str) -> dict[str, Any]:
        data = self._read_full_state(project_name)
        merged = dict(_DEFAULT_STATE)
        merged.update({k: v for k, v in data.items() if k in _DEFAULT_STATE})
        return merged

    def _persist_state(self, project_name: str, **fields: Any) -> dict[str, Any]:
        path = self._state_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_full_state(project_name)
        state = dict(_DEFAULT_STATE)
        state.update({k: v for k, v in existing.items() if k in _DEFAULT_STATE})
        state.update(fields)
        state["updated_at"] = time.time()
        # Preserve non-state keys (e.g. chunks) from the existing file
        for extra_key in ("chunks",):
            if extra_key in existing:
                state[extra_key] = existing[extra_key]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return state

    def _load_chunks(self, project_name: str) -> list[dict[str, Any]]:
        data = self._read_full_state(project_name)
        return data.get("chunks", [])

    def _save_chunks(self, project_name: str, chunks: list[dict[str, Any]]) -> None:
        path = self._state_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_full_state(project_name)
        existing["chunks"] = chunks
        existing["updated_at"] = time.time()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # ----- public API -----------------------------------------------------

    def ensure_cache(self, project_name: str, pdf_path: Path) -> str:
        """Extract PDF text and return it.

        No disk caching. Always re-extracts from the PDF.
        Sets ``total_words`` in state on first call.
        """
        text = self.segmenter.extract_text(pdf_path)
        state = self._load_state(project_name)
        if not state.get("total_words"):
            total_words = len(text.split())
            self._persist_state(project_name, total_words=total_words)
        return text

    def ensure_questions_generated(self, project_name: str) -> int:
        """Generate questions for any processed chunks that are missing them.

        Scans ``digest.json`` for chunks with ``text_keywords`` set, then
        checks whether the corresponding paragraph in ``game_state.json``
        already has questions. Generates questions for any that don't.

        Returns the number of paragraphs whose questions were generated.

        This is called at app startup to backfill questions for projects
        whose digest completed before the question-generation feature
        was introduced, or after a crash during generation.

        The project is tracked as having an active question-generation
        job while this runs, so the game controller can return
        ``{"status": "waiting"}`` instead of premature congratulations.
        """
        if self.game_manager is None:
            return 0

        self._question_gen_active.add(project_name)
        try:
            chunks = self._load_chunks(project_name)
            if not chunks:
                return 0

            state = self.game_manager.load_state(project_name)
            generated = 0

            for i, chunk in enumerate(chunks):
                if chunk.get("text_keywords") is None:
                    continue
                if state is not None and i < len(state.paragraphs) and state.paragraphs[i].questions:
                    continue
                self._generate_chunk_questions(project_name, chunk["original_text"], i)
                generated += 1

            if generated:
                logger.info(
                    "Generated %d question(s) for %d paragraph(s) of %s",
                    generated, generated, project_name,
                )
            return generated
        finally:
            self._question_gen_active.discard(project_name)

    def generate_title(self, project_name: str) -> tuple[str, str]:
        """Generate a project title and detect the document language.

        Uses the LLM with ``title_system_prompt`` and ``title_user_prompt_tpl``
        from the IA config. Expects the LLM to return JSON with ``title`` and
        ``language`` keys. Skips if both title and language were already set.

        Returns ``(title, language)`` — either may be empty on failure.
        Non-fatal — the supervisor continues with chunk processing regardless.
        """
        state = self._load_state(project_name)
        if state.get("title") and state.get("language"):
            return state["title"], state["language"]

        pdf_path = self.project_pdf_path(project_name)
        if pdf_path is None:
            logger.warning("Cannot generate title: no PDF for %s", project_name)
            return "", ""

        text = self.segmenter.extract_text(pdf_path)
        words = text.split()
        if not words:
            logger.warning("Cannot generate title: empty text for %s", project_name)
            return "", ""

        first_words = " ".join(words[:100])
        settings = self.segmenter._get_ia_settings()
        model = settings["ollama_model"]
        system_prompt = settings.get(
            "title_system_prompt",
            "You are a helpful assistant that analyzes document content. "
            "Respond only with valid JSON, no extra text.",
        )
        user_prompt_tpl = settings.get(
            "title_user_prompt_tpl",
            "Based on the following text, generate a short title of 1 to 7 words "
            "that represents the project and detect the language of the text.\n"
            'Return ONLY valid JSON conforming to this schema:\n'
            '{{"title": "short descriptive title (may include emojis)", '
            '"language": "ISO 639-1 code (e.g., en, es, fr, de, pt, it)"}}\n\n'
            "{text}",
        )
        prompt = user_prompt_tpl.format(text=first_words)

        logger.info(
            "Title generation started | project=%s model=%s words=%d",
            project_name, model, len(first_words.split()),
        )
        try:
            raw = self.segmenter.llm.generate(
                model, prompt, system=system_prompt,
            )
        except Exception as exc:
            logger.warning(
                "Title generation failed for %s: %s: %s",
                project_name, type(exc).__name__, exc,
            )
            return "", ""

        result = raw.strip().strip('"').strip("'").strip()
        if result.startswith("```"):
            first_nl = result.find("\n")
            if first_nl != -1:
                result = result[first_nl + 1:]
            if result.endswith("```"):
                result = result[:-3].rstrip()
        result = result.strip()
        title = ""
        language = ""
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                title = (data.get("title") or "").strip()
                language = (data.get("language") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass

        if not title:
            title = result

        if title:
            self._persist_state(project_name, title=title, language=language)
            logger.info(
                "Title generation finished | project=%s title=%s language=%s",
                project_name, title, language,
            )
        else:
            logger.warning("Title generation returned empty for %s", project_name)
        return title, language

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
        chunks = self._load_chunks(project_name)
        if not chunks:
            # No chunks yet — pending (first extraction still needed)
            return True
        processed = int(state.get("chunks_processed", 0))
        total = len(chunks)
        if total == 0:
            return False
        return processed < total

    def _generate_chunk_questions(self, project_name: str, chunk_text: str, chunk_idx: int) -> None:
        """Generate questions for a chunk — programmatic first, then LLM.

        Two-phase approach:
          Phase 1 — save programmatic questions (Reading Check + Fill the Gap)
                     immediately so the user can start playing.
          Phase 2 — generate LLM questions (multiple_choice, fill_blank,
                     short_answer, true_false) and append them. Failures
                     are non-fatal — programmatic Qs are already saved.
        """
        if self.game_manager is None:
            return

        from app.models.game_state import QuestionRecord

        state = self.game_manager.load_state(project_name)
        if state is None:
            all_chunks = self._load_chunks(project_name)
            state = self.game_manager.init_game(project_name, len(all_chunks))

        max_id = 0
        for para in state.paragraphs:
            for q in para.questions:
                if q.id > max_id:
                    max_id = q.id

        questions: list[QuestionRecord] = []

        # ---- Phase 1: programmatic questions --------------------------------

        # 1. Reading Check
        max_id += 1
        questions.append(QuestionRecord(
            id=max_id,
            title="Reading Check",
            question_type="options_choice",
            question_text=chunk_text,
            options=["Ok, i read it", "not yet"],
            correct_answer=["Ok, i read it"],
            correct_to_master=1,
        ))

        # 2. Fill the Gap — one per keyword
        all_chunks = self._load_chunks(project_name)
        current_chunk = all_chunks[chunk_idx] if chunk_idx < len(all_chunks) else {}
        keywords = current_chunk.get("text_keywords") or []

        if keywords:
            all_kw_pool: list[str] = []
            seen: set[str] = set()
            for ch in all_chunks:
                for kw in ch.get("text_keywords") or []:
                    lower = kw.lower()
                    if lower not in seen:
                        seen.add(lower)
                        all_kw_pool.append(kw)

            sentences = [s.strip() for s in re.split(r'(?<=[.!?;])\s+', chunk_text.strip()) if s.strip()]
            if not sentences:
                sentences = [chunk_text.strip()]

            for kw in keywords:
                target_sentence = None
                for sent in sentences:
                    if re.search(re.escape(kw), sent, re.IGNORECASE):
                        target_sentence = sent
                        break
                if not target_sentence:
                    continue

                gap_text = re.sub(re.escape(kw), "________", target_sentence, flags=re.IGNORECASE)

                distractor_pool = [w for w in all_kw_pool if w.lower() != kw.lower()]
                if len(distractor_pool) >= 3:
                    distractors = random.sample(distractor_pool, 3)
                else:
                    distractors = list(distractor_pool)
                options = [kw] + distractors
                random.shuffle(options)

                max_id += 1
                questions.append(QuestionRecord(
                    id=max_id,
                    title="Fill the Gap",
                    question_type="fill_gap",
                    question_text=gap_text,
                    options=options,
                    correct_answer=[kw],
                    correct_to_master=0,
                ))

        # Save programmatic questions immediately — user can play now
        state.paragraphs[chunk_idx].questions = questions
        self.game_manager.save_state(project_name, state)
        logger.debug(
            "Phase 1 — saved %d programmatic question(s) for chunk %d of %s",
            len(questions), chunk_idx, project_name,
        )

        # ---- Phase 2: LLM-generated questions ------------------------------

        if self.question_generator is None or self.config_manager is None:
            return

        if not keywords:
            return

        try:
            cfg = self.config_manager.load()
            game_cfg = cfg.get("game", {})
            language = game_cfg.get("language", "es")
            qpp = game_cfg.get("questions_per_paragraph", 5)

            llm_questions = self.question_generator.generate(
                chunk_text=chunk_text,
                keywords=keywords,
                count=qpp,
                language=language,
            )

            tf_questions = self.question_generator.generate_true_false_questions(
                chunk_text=chunk_text,
                keywords=keywords,
                language=language,
            )
        except Exception as exc:
            logger.warning(
                "Phase 2 — LLM question generation failed for chunk %d of %s: %s",
                chunk_idx, project_name, exc,
            )
            return

        # Reload state to preserve any user progress made between Phase 1 and now
        state = self.game_manager.load_state(project_name)
        if state is None:
            return

        existing = list(state.paragraphs[chunk_idx].questions)
        max_id = max((q.id for p in state.paragraphs for q in p.questions), default=0)

        for q_dict in llm_questions + tf_questions:
            max_id += 1
            ca = q_dict.get("correct_answer", "")
            if isinstance(ca, str):
                ca = [ca] if ca else []
            existing.append(QuestionRecord(
                id=max_id,
                question_type=q_dict["type"],
                question_text=q_dict["question"],
                options=q_dict.get("options", []),
                correct_answer=ca,
            ))

        state.paragraphs[chunk_idx].questions = existing
        self.game_manager.save_state(project_name, state)
        logger.debug(
            "Phase 2 — appended %d LLM question(s) for chunk %d of %s",
            len(llm_questions) + len(tf_questions), chunk_idx, project_name,
        )

    def _resolve_page_number(self, word_idx: int, page_ranges: list[tuple[int, int, int]]) -> int:
        """Return the 1-indexed page number containing the given word index."""
        for page_num, start, end in page_ranges:
            if start <= word_idx < end:
                return page_num
        return page_ranges[-1][0] if page_ranges else 1

    def process_one_chunk(
        self,
        project_name: str,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> Optional[dict[str, Any]]:
        """Process the next unprocessed chunk; return progress info or ``None`` when done.

        On first call, extracts PDF text per-page, chunks it with page numbers,
        and stores chunks inside ``digest.json``. Then sends one chunk at a time
        to the LLM for keyword extraction.
        """
        state = self._load_state(project_name)
        if state.get("state") in _TERMINAL_STATES:
            return None

        self._persist_state(project_name, state="processing")

        chunks = self._load_chunks(project_name)

        # First time: extract text from PDF, chunk it, compute page numbers
        if not chunks:
            pdf_path = self.project_pdf_path(project_name)
            if pdf_path is None:
                self._persist_state(project_name, state="complete")
                return None

            pages_text = self.segmenter.extract_text_by_page(pdf_path)
            if not pages_text or all(not t.strip() for _, t in pages_text):
                self._persist_state(project_name, state="complete", total_words=0)
                return None

            page_ranges = self.segmenter._compute_page_word_ranges(pages_text)
            full_text = "\n".join(t for _, t in pages_text)
            words = full_text.split()
            if not words:
                self._persist_state(project_name, state="complete", total_words=0)
                return None

            chunk_tuples = self.segmenter.chunk_text(full_text)
            total_chunks = len(chunk_tuples)
            if total_chunks == 0:
                self._persist_state(project_name, state="complete", total_words=len(words))
                return None

            texts = [c[0] for c in chunk_tuples]
            page_numbers = [
                self._resolve_page_number(end - 1, page_ranges)
                for _, _, end in chunk_tuples
            ]
            new_chunks = self.segmenter._build_chunk_dicts(texts, page_numbers)
            self._save_chunks(project_name, new_chunks)
            self._persist_state(
                project_name,
                total_words=len(words),
                total_chunks=total_chunks,
                chunks_processed=0,
            )
            state = self._load_state(project_name)
            chunks = new_chunks

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

        # Update the chunk in digest.json
        chunks[processed]["text_keywords"] = keywords if keywords else None
        self._save_chunks(project_name, chunks)

        # Generate questions for this chunk so users can start playing ASAP
        self._generate_chunk_questions(project_name, chunk_text, processed)

        current_keywords = int(state.get("total_keywords", 0)) + (len(keywords) if keywords else 0)
        new_processed = processed + 1

        if new_processed >= total_chunks:
            # Deduplicate keywords across all chunks for the final count
            all_chunks = self._load_chunks(project_name)
            unique_kws: set[str] = set()
            for c in all_chunks:
                kws = c.get("text_keywords")
                if kws:
                    unique_kws.update(kws)
            unique_count = len(unique_kws)

            info = {
                "chunk": chunk_num,
                "total_chunks": total_chunks,
                "chunks_processed": new_processed,
                "total_keywords": unique_count,
                "state": "complete",
                "progress_pct": 100,
            }
            self._persist_state(
                project_name,
                state="complete",
                total_chunks=total_chunks,
                chunks_processed=new_processed,
                total_keywords=unique_count,
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
            state="processing",
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

    def is_question_generation_active(self, project_name: str) -> bool:
        return project_name in self._question_gen_active

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

        Called once per supervisor iteration. The PDF text is extracted
        on first call if chunks are not yet in ``digest.json``.
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
