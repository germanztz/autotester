"""Question engine — plans and generates questions sequentially via LLM."""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Optional

from app.models.game_state import GameManager, GameState, ParagraphState, QuestionRecord
from app.models.question import QuestionKind, _TITLES
from app.services.question_generator import QuestionGenerator
from app.utils.logging_setup import get_logger

logger = get_logger()


_DIGEST_POLL_SLEEP = 0.1


class QuestionEngine:
    """Orchestrates question planning and LLM generation.

    **Planning phase** (synchronous, no LLM):
        - Reads chunks from ``digest.json``
        - Creates ``game_state.json`` with all questions upfront
        - INFO (reading check, programmatic)    → ``status=generated``
        - FILL (fill-the-gap, programmatic)      → ``status=generated``
        - TRUE_FALSE (needs LLM)                 → ``status=pending``

    **Generation phase** (sequential LLM calls):
        - ``generate_next_pending()`` processes one pending TRUE_FALSE question
        - Updates ``game_state.json`` after each individual question (status→generated|error)
        - ``generate_all_questions()`` loops until no pending remain
    """

    def __init__(
        self,
        file_manager: Any,
        config_manager: Any,
        question_generator: QuestionGenerator,
        game_manager: GameManager,
    ) -> None:
        self.file_manager = file_manager
        self.config_manager = config_manager
        self.generator = question_generator
        self.game_manager = game_manager
        self._generation_active: set[str] = set()

    # ----- paths -----------------------------------------------------------

    def _digest_path(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name) / "digest.json"

    def _load_chunks(self, project_name: str) -> list[dict[str, Any]]:
        path = self._digest_path(project_name)
        if not path.exists():
            raise FileNotFoundError(f"digest.json not found for {project_name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
        if not chunks:
            raise FileNotFoundError(f"no chunks in digest.json for {project_name}")
        return chunks

    # ----- planning --------------------------------------------------------

    def plan_questions(self, project_name: str) -> dict[str, Any]:
        """Create ``game_state.json`` with all questions planned upfront.

        * INFO (Reading Check) — one per paragraph, programmatic, ``status=generated``
        * FILL (Fill the Gap) — one per keyword, programmatic, ``status=generated``
        * TRUE_FALSE — one per keyword, ``status=pending`` (LLM will fill later)

        Questions are ordered following ``_TITLES`` (INFO → FILL → TRUE_FALSE)
        within each paragraph.

        Returns a dict with:
            ``status``, ``total_paragraphs``, ``total_questions``, ``pending``.
        """
        chunks = self._load_chunks(project_name)
        num_paragraphs = len(chunks)

        state = self.game_manager.init_game(project_name, num_paragraphs)

        cfg = self.config_manager.load()
        game_cfg = cfg.get("game", {})
        ctm = game_cfg.get("correct_to_master", 3)

        qid = 0
        total_questions = 0
        pending_count = 0

        # Collect all keywords across all chunks for distractor pool
        all_kw_pool: list[str] = []
        seen_pool: set[str] = set()
        for ch in chunks:
            for kw in ch.get("text_keywords") or []:
                lower = kw.lower()
                if lower not in seen_pool:
                    seen_pool.add(lower)
                    all_kw_pool.append(kw)

        for para_idx, chunk in enumerate(chunks):
            chunk_text = chunk.get("original_text", "")
            keywords = chunk.get("text_keywords") or []
            sentences = [
                s.strip() for s in re.split(r'(?<=[.!?;])\s+', chunk_text.strip())
                if s.strip()
            ]
            if not sentences:
                sentences = [chunk_text.strip()]

            para_questions: list[QuestionRecord] = []

            # Iterate _TITLES in insertion order: INFO → FILL → TRUE_FALSE
            for q_kind in _TITLES:
                if q_kind == QuestionKind.INFO:
                    qid += 1
                    para_questions.append(QuestionRecord(
                        id=qid,
                        title=_TITLES[q_kind],
                        question_type=q_kind.value,
                        question_text=chunk_text,
                        options=["Ok, i read it", "not yet"],
                        correct_answer=["Ok, i read it"],
                        correct_to_master=1,
                        status="generated",
                        keyword="",
                        chunk_index=para_idx,
                    ))
                    total_questions += 1

                elif q_kind == QuestionKind.FILL:
                    for kw in keywords:
                        target_sentence = None
                        for sent in sentences:
                            if re.search(re.escape(kw), sent, re.IGNORECASE):
                                target_sentence = sent
                                break
                        if not target_sentence:
                            continue

                        gap_text = re.sub(
                            re.escape(kw), "________", target_sentence,
                            flags=re.IGNORECASE,
                        )

                        distractor_pool = [
                            w for w in all_kw_pool if w.lower() != kw.lower()
                        ]
                        if len(distractor_pool) >= 3:
                            distractors = random.sample(distractor_pool, 3)
                        else:
                            distractors = list(distractor_pool)
                        options = [kw] + distractors
                        random.shuffle(options)

                        qid += 1
                        para_questions.append(QuestionRecord(
                            id=qid,
                            title=_TITLES[q_kind],
                            question_type=q_kind.value,
                            question_text=gap_text,
                            options=options,
                            correct_answer=[kw],
                            correct_to_master=0,
                            status="generated",
                            keyword=kw,
                            chunk_index=para_idx,
                        ))
                        total_questions += 1

                elif q_kind == QuestionKind.TRUE_FALSE:
                    for idx_kw, kw in enumerate(keywords):
                        target_response = "true" if idx_kw % 2 == 0 else "false"
                        qid += 1
                        para_questions.append(QuestionRecord(
                            id=qid,
                            title=_TITLES[q_kind],
                            question_type=q_kind.value,
                            question_text="pending",
                            options=[],
                            correct_answer=[target_response],
                            correct_to_master=0,
                            status="pending",
                            keyword=kw,
                            chunk_index=para_idx,
                        ))
                        total_questions += 1
                        pending_count += 1

            state.paragraphs[para_idx].questions = para_questions

        self.game_manager.save_state(project_name, state)

        logger.info(
            "Planned %d questions (%d pending) for %s",
            total_questions, pending_count, project_name,
        )

        return {
            "status": "generating" if pending_count > 0 else "ready",
            "total_paragraphs": num_paragraphs,
            "total_questions": total_questions,
            "pending": pending_count,
        }

    # ----- single-question generation (sequential LLM call) ----------------

    def generate_next_pending(self, project_name: str) -> bool:
        """Process one pending TRUE_FALSE question via LLM.

        Updates ``game_state.json`` immediately with the result.

        Returns:
            True if more pending questions remain, False if all done.
        """
        state = self.game_manager.load_state(project_name)
        if state is None:
            return False

        pending = self.game_manager.find_next_pending(state)
        if pending is None:
            return False

        para_idx, q_idx, question = pending

        # Get the chunk text
        try:
            chunks = self._load_chunks(project_name)
        except FileNotFoundError:
            question.status = "error"
            self.game_manager.save_state(project_name, state)
            logger.warning(
                "question_gen | chunk=%d qid=%d keyword=%s type=%s result=ERROR (no digest)",
                question.chunk_index, question.id, question.keyword,
                question.question_type,
            )
            return True

        chunk = chunks[question.chunk_index] if question.chunk_index < len(chunks) else {}
        chunk_text = chunk.get("original_text", "")

        if not chunk_text:
            question.status = "error"
            self.game_manager.save_state(project_name, state)
            logger.warning(
                "question_gen | chunk=%d qid=%d keyword=%s type=%s result=ERROR (empty chunk)",
                question.chunk_index, question.id, question.keyword,
                question.question_type,
            )
            return True

        cfg = self.config_manager.load()
        game_cfg = cfg.get("game", {})
        language = game_cfg.get("language", "es")

        # Assign target_response — true for even, false for odd within this paragraph
        target_response = question.correct_answer[0] if question.correct_answer else "true"

        try:
            result = self.generator.generate_single_true_false(
                chunk_text=chunk_text,
                keyword=question.keyword,
                language=language,
                target_response=target_response,
            )
            question.question_text = result["question"]
            question.options = ["True", "False"]
            question.status = "generated"
            self.game_manager.save_state(project_name, state)
            logger.info(
                "question_gen | chunk=%d qid=%d keyword=%s type=%s result=OK",
                question.chunk_index, question.id, question.keyword,
                question.question_type,
            )
        except Exception as exc:
            question.status = "error"
            self.game_manager.save_state(project_name, state)
            logger.warning(
                "question_gen | chunk=%d qid=%d keyword=%s type=%s result=ERROR: %s",
                question.chunk_index, question.id, question.keyword,
                question.question_type, exc,
            )

        # Check if more pending remain
        state = self.game_manager.load_state(project_name)
        return self.game_manager.find_next_pending(state) is not None

    # ----- full generation (called as a JobRunner job) ---------------------

    def generate_all_questions(self, project_name: str) -> dict[str, Any]:
        """Sequentially process all pending questions, one LLM call at a time.

        Plans questions first if no ``game_state.json`` exists.
        This is intended to be submitted as a ``JobRunner`` job.
        """
        self._generation_active.add(project_name)
        try:
            state = self.game_manager.load_state(project_name)
            if state is None:
                self.plan_questions(project_name)

            while True:
                has_more = self.generate_next_pending(project_name)
                if not has_more:
                    break
                time.sleep(_DIGEST_POLL_SLEEP)

            state = self.game_manager.load_state(project_name)
            stats = self.game_manager.get_stats(state) if state else {}
            logger.info("question_gen | project=%s complete", project_name)
            return {"status": "ready", **stats}
        except Exception as exc:
            logger.error(
                "question_gen | project=%s failed: %s",
                project_name, exc,
            )
            return {"status": "error", "error": str(exc)}
        finally:
            self._generation_active.discard(project_name)

    # ----- status / start --------------------------------------------------

    def start_game(self, project_name: str) -> dict[str, Any]:
        """Start (or resume) a game plan for a project.

        1. If ``game_state.json`` does not exist, calls ``plan_questions()``.
           After planning, INFO (Reading Check) and FILL questions are already
           ``status=generated`` so the user can start playing immediately even
           while TRUE_FALSE questions are still being generated by the LLM.
        2. Returns the current status so the caller can decide to submit
           ``generate_all_questions`` to a ``JobRunner``.

        Returns:
            ``{"status": "generating", "pending": N, ...}`` if no generated
            questions exist yet, or ``{"status": "ready", ...}`` with stats
            if at least one generated question is available to play.
        """
        existing = self.game_manager.load_state(project_name)
        if existing is not None:
            pending = self.game_manager.find_next_pending(existing)
            if pending:
                # Generated questions may already exist (INFO / FILL) — play those
                has_generated = any(
                    q.status == "generated" for p in existing.paragraphs for q in p.questions
                )
                if has_generated:
                    stats = self.game_manager.get_stats(existing)
                    return {"status": "ready", "pending": self._count_pending(existing), **stats}
                return {
                    "status": "generating",
                    "pending": self._count_pending(existing),
                }
            stats = self.game_manager.get_stats(existing)
            return {"status": "ready", **stats}

        # No game state yet — plan
        try:
            plan_result = self.plan_questions(project_name)
            state = self.game_manager.load_state(project_name)
            stats = self.game_manager.get_stats(state) if state else {}
            if state and any(
                q.status == "generated" for p in state.paragraphs for q in p.questions
            ):
                return {"status": "ready", "pending": plan_result.get("pending", 0), **stats}
            return plan_result
        except FileNotFoundError as exc:
            logger.warning("Game start failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def get_game_status(self, project_name: str) -> dict[str, Any]:
        """Return current game status for a project."""
        state = self.game_manager.load_state(project_name)
        if state is None:
            return {"status": "not_started"}

        # If pending questions remain but generated questions exist (INFO / FILL
        # after planning), let the user play those while LLM generates the rest.
        if self.game_manager.find_next_pending(state) is not None:
            has_generated = any(
                q.status == "generated" for p in state.paragraphs for q in p.questions
            )
            if has_generated:
                stats = self.game_manager.get_stats(state)
                return {"status": "playing", "pending": self._count_pending(state), **stats}
            return {
                "status": "generating",
                "pending": self._count_pending(state),
                **self.game_manager.get_stats(state),
            }

        total = sum(
            1 for p in state.paragraphs for q in p.questions
            if q.status == "generated"
        )
        if total == 0:
            return {"status": "generating"}

        stats = self.game_manager.get_stats(state)

        # Check if the digest is still processing (more chunks than paragraphs,
        # or digest.json state is not "complete").
        digest_active = self._is_digest_active(project_name)
        if digest_active:
            return {"status": "playing", "digest_active": True, **stats}

        if self.game_manager.has_unprocessed_paragraphs(state):
            return {"status": "playing", "digest_active": True, **stats}

        return {"status": "playing", **stats}

    def _is_digest_active(self, project_name: str) -> bool:
        """Check if the digest is still processing or has more chunks planned."""
        import json
        from pathlib import Path
        digest_path = Path(self._digest_path(project_name))
        if not digest_path.exists():
            return False
        try:
            data = json.loads(digest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        dstate = data.get("state", "")
        if dstate in ("processing", "queued"):
            return True
        # Check if there are more chunks than game paragraphs
        chunks = data.get("chunks", [])
        if chunks:
            state = self.game_manager.load_state(project_name)
            if state is not None and len(chunks) > len(state.paragraphs):
                return True
        return False

    def is_generation_active(self, project_name: str) -> bool:
        return project_name in self._generation_active

    # ----- helpers ---------------------------------------------------------

    @staticmethod
    def _count_pending(state: GameState) -> int:
        return sum(
            1 for p in state.paragraphs for q in p.questions if q.status == "pending"
        )
