"""Game state model — progress tracking, paragraph unlocking, spaced repetition."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from app.utils.logging_setup import get_logger

logger = get_logger()


@dataclass
class QuestionRecord:
    """A single question with its progress toward mastery."""

    question_type: str  # options_choice | fill_gap | true_false
    question_text: str
    id: int = 0
    title: str = ""
    options: list[str] = field(default_factory=list)
    correct_answer: list[str] = field(default_factory=list)
    correct_count: int = 0
    wrong_count: int = 0
    last_seen: float = 0.0
    last_answer: str = ""
    last_answer_correct: bool = False
    correct_to_master: int = 0  # 0 = use global default from config

    def is_mastered(self, default_correct_to_master: int) -> bool:
        threshold = self.correct_to_master if self.correct_to_master > 0 else default_correct_to_master
        return self.correct_count >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "question_type": self.question_type,
            "question_text": self.question_text,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "last_seen": self.last_seen,
            "last_answer": self.last_answer,
            "last_answer_correct": self.last_answer_correct,
            "correct_to_master": self.correct_to_master,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionRecord:
        ca = data.get("correct_answer", "")
        if isinstance(ca, str):
            ca = [ca] if ca else []
        return cls(
            id=data.get("id", 0),
            title=data.get("title", ""),
            question_type=data["question_type"],
            question_text=data["question_text"],
            options=data.get("options", []),
            correct_answer=ca,
            correct_count=data.get("correct_count", 0),
            wrong_count=data.get("wrong_count", 0),
            last_seen=data.get("last_seen", 0.0),
            last_answer=data.get("last_answer", ""),
            last_answer_correct=data.get("last_answer_correct", False),
            correct_to_master=data.get("correct_to_master", 0),
        )


@dataclass
class ParagraphState:
    """State of one paragraph (chunk) in the game."""

    index: int
    unlocked: bool = False
    questions: list[QuestionRecord] = field(default_factory=list)

    def all_answered_correctly_at_least_once(self) -> bool:
        if not self.questions:
            return False
        return all(q.correct_count >= 1 for q in self.questions)

    def mastered_count(self, correct_to_master: int) -> int:
        return sum(1 for q in self.questions if q.is_mastered(correct_to_master))

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "unlocked": self.unlocked,
            "questions": [q.to_dict() for q in self.questions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParagraphState:
        return cls(
            index=data["index"],
            unlocked=data.get("unlocked", False),
            questions=[QuestionRecord.from_dict(q) for q in data.get("questions", [])],
        )


@dataclass
class GameState:
    """Complete game state for a project."""

    project_name: str
    paragraphs: list[ParagraphState] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameState:
        return cls(
            project_name=data["project_name"],
            paragraphs=[ParagraphState.from_dict(p) for p in data.get("paragraphs", [])],
            updated_at=data.get("updated_at", 0.0),
        )


class GameManager:
    """Manages game state persistence and game logic."""

    def __init__(self, file_manager: Any, config_manager: Any) -> None:
        self.file_manager = file_manager
        self.config_manager = config_manager

    def _state_path(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name) / "game_state.json"

    def _get_game_config(self) -> dict[str, Any]:
        return self.config_manager.load().get("game", {})

    def load_state(self, project_name: str) -> Optional[GameState]:
        """Load game state from disk. Returns None if not found."""
        path = self._state_path(project_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GameState.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load game state for %s: %s", project_name, exc)
            return None

    def save_state(self, project_name: str, state: GameState) -> None:
        """Persist game state atomically."""
        state.updated_at = time.time()
        path = self._state_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    def calculate_progress(self, state: GameState) -> float:
        """Calculate progress as (total_correct / total_possible) * 100."""
        cfg = self._get_game_config()
        ctm = cfg.get("correct_to_master", 3)
        total_questions = sum(len(p.questions) for p in state.paragraphs)
        if total_questions == 0:
            return 0.0
        total_possible = total_questions * ctm
        total_correct = sum(
            q.correct_count for p in state.paragraphs for q in p.questions
        )
        return min(100.0, round((total_correct / total_possible) * 100, 1))

    def get_stats(self, state: GameState) -> dict[str, Any]:
        """Return progress statistics."""
        cfg = self._get_game_config()
        ctm = cfg.get("correct_to_master", 3)
        total_questions = sum(len(p.questions) for p in state.paragraphs)
        total_possible = total_questions * ctm if total_questions > 0 else 1
        total_correct = sum(
            q.correct_count for p in state.paragraphs for q in p.questions
        )
        total_wrong = sum(
            q.wrong_count for p in state.paragraphs for q in p.questions
        )
        mastered = sum(
            q.is_mastered(ctm) for p in state.paragraphs for q in p.questions
        )
        return {
            "progress_pct": self.calculate_progress(state),
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "total_possible": total_possible,
            "total_questions": total_questions,
            "mastered_questions": mastered,
            "total_paragraphs": len(state.paragraphs),
            "unlocked_paragraphs": sum(1 for p in state.paragraphs if p.unlocked),
        }

    def has_unprocessed_paragraphs(self, state: GameState) -> bool:
        """Return True if any locked paragraphs have no questions (digest not finished).

        This prevents the frontend from showing a premature 'Congratulations' when
        the digest hasn't processed all chunks yet.
        """
        return any(
            not para.unlocked and not para.questions
            for para in state.paragraphs
        )

    def get_next_question(self, state: GameState) -> Optional[tuple[int, int, QuestionRecord]]:
        """Select the next question using spaced repetition logic.

        Returns (paragraph_index, question_index, question) or None if all mastered.
        Priority:
        1. Questions never seen (correct_count = 0, wrong_count = 0)
        2. Questions with wrong_count > correct_count
        3. Questions seen least recently
        Only from unlocked paragraphs.
        """
        cfg = self._get_game_config()
        ctm = cfg.get("correct_to_master", 3)
        now = time.time()

        candidates: list[tuple[float, int, int, QuestionRecord]] = []
        for pi, para in enumerate(state.paragraphs):
            if not para.unlocked:
                continue
            for qi, q in enumerate(para.questions):
                if q.is_mastered(ctm):
                    continue
                # Score: lower = higher priority
                if q.correct_count == 0 and q.wrong_count == 0:
                    score = 0.0  # unseen — highest priority
                elif q.wrong_count > q.correct_count:
                    score = 1.0  # struggling
                else:
                    score = 2.0  # in progress
                # Tie-break by time since last seen (older first)
                time_bonus = (now - q.last_seen) / 60.0 if q.last_seen > 0 else 999
                candidates.append((score - time_bonus * 0.001, pi, qi, q))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        _, pi, qi, q = candidates[0]
        return pi, qi, q

    def submit_answer(
        self, state: GameState, para_idx: int, q_idx: int, answer: str
    ) -> dict[str, Any]:
        """Check an answer, update state, return feedback."""
        para = state.paragraphs[para_idx]
        q = para.questions[q_idx]

        before_completed = para.all_answered_correctly_at_least_once()

        is_correct = any(
            ca.strip().lower() == answer.strip().lower()
            for ca in q.correct_answer
        )
        q.last_answer = answer.strip()
        q.last_answer_correct = is_correct
        if is_correct:
            q.correct_count += 1
        else:
            q.wrong_count += 1
        q.last_seen = time.time()

        cfg = self._get_game_config()
        ctm = cfg.get("correct_to_master", 3)
        threshold = q.correct_to_master if q.correct_to_master > 0 else ctm
        just_mastered = q.correct_count == threshold

        para_just_completed = not before_completed and para.all_answered_correctly_at_least_once()
        next_para_unlocked = False

        # Check if this paragraph can now be unlocked
        if para.unlocked and para_idx + 1 < len(state.paragraphs):
            next_para = state.paragraphs[para_idx + 1]
            if not next_para.unlocked and para.all_answered_correctly_at_least_once():
                next_para.unlocked = True
                next_para_unlocked = True
                logger.info(
                    "Paragraph %d unlocked for %s", para_idx + 1, state.project_name
                )

        self.save_state(state.project_name, state)

        return {
            "correct": is_correct,
            "correct_answer": q.correct_answer,
            "correct_count": q.correct_count,
            "wrong_count": q.wrong_count,
            "just_mastered": just_mastered,
            "is_mastered": q.is_mastered(ctm),
            "mastery_threshold": threshold,
            "para_idx": para_idx,
            "q_idx": q_idx,
            "para_just_completed": para_just_completed,
            "next_para_unlocked": next_para_unlocked,
            "progress_pct": self.calculate_progress(state),
        }

    def get_history(self, state: GameState, count: int = 10) -> list[dict[str, Any]]:
        """Return the last `count` answered questions sorted chronologically.

        Each entry contains the question text, the user's last answer,
        whether it was correct, and the correct answer.
        """
        answered = [
            (pi, qi, q)
            for pi, p in enumerate(state.paragraphs)
            for qi, q in enumerate(p.questions)
            if q.last_answer
        ]
        answered.sort(key=lambda x: x[2].last_seen, reverse=True)
        entries = answered[:count]
        entries.reverse()
        return [
            {
                "title": q.title,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": q.options,
                "last_answer": q.last_answer,
                "last_answer_correct": q.last_answer_correct,
                "correct_answer": q.correct_answer,
                "para_idx": pi,
                "q_idx": qi,
            }
            for pi, qi, q in entries
        ]

    def init_game(self, project_name: str, num_paragraphs: int) -> GameState:
        """Create a fresh game state with all paragraphs locked except the first."""
        cfg = self._get_game_config()
        paragraphs = [
            ParagraphState(index=i, unlocked=(i == 0))
            for i in range(num_paragraphs)
        ]
        state = GameState(project_name=project_name, paragraphs=paragraphs)
        self.save_state(project_name, state)
        return state

    def store_questions(
        self,
        project_name: str,
        para_idx: int,
        questions: list[dict[str, Any]],
    ) -> None:
        """Store generated questions for a paragraph and persist."""
        state = self.load_state(project_name)
        if state is None:
            return
        para = state.paragraphs[para_idx]
        para.questions = [
            QuestionRecord(
                question_type=q["type"],
                question_text=q["question"],
                options=q.get("options", []),
                correct_answer=(
                    q["correct_answer"]
                    if isinstance(q["correct_answer"], list)
                    else [q["correct_answer"]] if q["correct_answer"] else []
                ),
            )
            for q in questions
        ]
        self.save_state(project_name, state)

    def reset_game(self, project_name: str, num_paragraphs: int) -> GameState:
        """Reset game progress, keeping questions but zeroing counts."""
        state = self.load_state(project_name)
        if state is None:
            return self.init_game(project_name, num_paragraphs)
        for para in state.paragraphs:
            para.unlocked = (para.index == 0)
            for q in para.questions:
                q.correct_count = 0
                q.wrong_count = 0
                q.last_seen = 0.0
        self.save_state(project_name, state)
        return state
