"""Tests for app.models.game_state — GameManager, GameState, progress logic."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.models.game_state import (
    GameManager,
    GameState,
    ParagraphState,
    QuestionRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def game_config() -> dict:
    return {
        "language": "es",
        "questions_per_paragraph": 3,
        "correct_to_master": 2,
    }


@pytest.fixture
def fake_file_manager(tmp_path: Path, game_config: dict):
    """A lightweight FileManager-like object for testing."""

    class _FakeFM:
        def __init__(self, root: Path):
            self.root = root
            self.root.mkdir(parents=True, exist_ok=True)

        def project_path(self, name: str) -> Path:
            p = self.root / name
            p.mkdir(parents=True, exist_ok=True)
            return p

    return _FakeFM(tmp_path / "projects")


@pytest.fixture
def fake_config_manager(game_config: dict):
    class _FakeCM:
        def load(self) -> dict:
            return {"game": game_config}

    return _FakeCM()


@pytest.fixture
def manager(fake_file_manager, fake_config_manager) -> GameManager:
    return GameManager(fake_file_manager, fake_config_manager)


@pytest.fixture
def sample_state() -> GameState:
    """A game state with 2 paragraphs, 3 questions each, first para unlocked."""
    return GameState(
        project_name="testproj",
        paragraphs=[
            ParagraphState(
                index=0,
                unlocked=True,
                questions=[
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q1?",
                        options=["A", "B", "C"],
                        correct_answer=["A"],
                    ),
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q2?",
                        correct_answer=["true"],
                    ),
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q3 ___",
                        correct_answer=["answer"],
                    ),
                ],
            ),
            ParagraphState(
                index=1,
                unlocked=False,
                questions=[
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q4?",
                        correct_answer=["response"],
                    ),
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q5?",
                        options=["X", "Y", "Z"],
                        correct_answer=["Y"],
                    ),
                    QuestionRecord(
                        question_type="true_false",
                        question_text="Q6?",
                        correct_answer=["false"],
                    ),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# TestQuestionRecord
# ---------------------------------------------------------------------------


class TestQuestionRecord:
    def test_is_mastered(self):
        q = QuestionRecord(
            question_type="true_false",
            question_text="test?",
            correct_answer=["A"],
            correct_count=3,
        )
        assert q.is_mastered(3)
        assert not q.is_mastered(4)

    def test_round_trip_dict(self):
        q = QuestionRecord(
            question_type="true_false",
            question_text="Is this true?",
            correct_answer=["true"],
            correct_count=2,
            wrong_count=1,
            last_seen=100.0,
        )
        d = q.to_dict()
        q2 = QuestionRecord.from_dict(d)
        assert q2.question_type == q.question_type
        assert q2.correct_count == q.correct_count
        assert q2.wrong_count == q.wrong_count

    def test_to_dict_includes_id_and_title(self):
        q = QuestionRecord(
            id=42,
            title="Reading Check",
            question_type="true_false",
            question_text="Did you read?",
            correct_answer=["true"],
        )
        d = q.to_dict()
        assert d["id"] == 42
        assert d["title"] == "Reading Check"

    def test_from_dict_includes_id_and_title(self):
        data = {
            "id": 7,
            "title": "Comprehension",
            "question_type": "true_false",
            "question_text": "Read the text?",
            "correct_answer": "true",
        }
        q = QuestionRecord.from_dict(data)
        assert q.id == 7
        assert q.title == "Comprehension"

    def test_from_dict_missing_id_title_defaults(self):
        data = {
            "question_type": "true_false",
            "question_text": "test?",
            "correct_answer": "true",
        }
        q = QuestionRecord.from_dict(data)
        assert q.id == 0
        assert q.title == ""


# ---------------------------------------------------------------------------
# TestParagraphState
# ---------------------------------------------------------------------------


class TestParagraphState:
    def test_all_answered_correctly_once(self):
        para = ParagraphState(
            index=0,
            unlocked=True,
            questions=[
                QuestionRecord(
                    question_type="mc", question_text="q1", correct_answer=["A"],
                    correct_count=1,
                ),
                QuestionRecord(
                    question_type="mc", question_text="q2", correct_answer="B",
                    correct_count=2,
                ),
            ],
        )
        assert para.all_answered_correctly_at_least_once()

    def test_not_all_answered_when_some_zero(self):
        para = ParagraphState(
            index=0,
            unlocked=True,
            questions=[
                QuestionRecord(
                    question_type="mc", question_text="q1", correct_answer=["A"],
                    correct_count=1,
                ),
                QuestionRecord(
                    question_type="mc", question_text="q2", correct_answer="B",
                    correct_count=0,
                ),
            ],
        )
        assert not para.all_answered_correctly_at_least_once()

    def test_mastered_count(self):
        para = ParagraphState(
            index=0,
            unlocked=True,
            questions=[
                QuestionRecord(
                    question_type="mc", question_text="q1", correct_answer=["A"],
                    correct_count=3,
                ),
                QuestionRecord(
                    question_type="mc", question_text="q2", correct_answer="B",
                    correct_count=1,
                ),
                QuestionRecord(
                    question_type="mc", question_text="q3", correct_answer="C",
                    correct_count=3,
                ),
            ],
        )
        assert para.mastered_count(3) == 2


# ---------------------------------------------------------------------------
# TestGameManager
# ---------------------------------------------------------------------------


class TestGameManagerInit:
    def test_init_game_creates_state(self, manager: GameManager):
        state = manager.init_game("testproj", 3)
        assert state.project_name == "testproj"
        assert len(state.paragraphs) == 3
        assert state.paragraphs[0].unlocked is True
        assert state.paragraphs[1].unlocked is False
        assert state.paragraphs[2].unlocked is False

    def test_save_and_load_round_trip(self, manager: GameManager):
        state = manager.init_game("roundtrip", 2)
        loaded = manager.load_state("roundtrip")
        assert loaded is not None
        assert loaded.project_name == "roundtrip"
        assert len(loaded.paragraphs) == 2

    def test_load_missing_returns_none(self, manager: GameManager):
        assert manager.load_state("ghost") is None


class TestGameProgress:
    def test_progress_starts_at_zero(self, manager: GameManager, sample_state: GameState):
        pct = manager.calculate_progress(sample_state)
        assert pct == 0.0

    def test_partial_progress(self, manager: GameManager, sample_state: GameState):
        # 2 paragraphs × 3 questions × 2 correct_to_master = 12 total possible
        # Answer 3 correctly → 3/12 = 25%
        sample_state.paragraphs[0].questions[0].correct_count = 2
        sample_state.paragraphs[0].questions[1].correct_count = 1
        pct = manager.calculate_progress(sample_state)
        assert pct == 25.0

    def test_full_progress(self, manager: GameManager, sample_state: GameState):
        for para in sample_state.paragraphs:
            for q in para.questions:
                q.correct_count = 2
        pct = manager.calculate_progress(sample_state)
        assert pct == 100.0

    def test_get_stats(self, manager: GameManager, sample_state: GameState):
        sample_state.paragraphs[0].questions[0].correct_count = 2
        stats = manager.get_stats(sample_state)
        assert stats["total_correct"] == 2
        assert stats["total_questions"] == 6
        assert stats["mastered_questions"] == 1
        assert stats["unlocked_paragraphs"] == 1


class TestGetNextQuestion:
    def test_returns_first_unseen(self, manager: GameManager, sample_state: GameState):
        result = manager.get_next_question(sample_state)
        assert result is not None
        pi, qi, q = result
        assert pi == 0
        assert q.correct_count == 0

    def test_returns_none_when_all_mastered(self, manager: GameManager, sample_state: GameState):
        for para in sample_state.paragraphs:
            para.unlocked = True
            for q in para.questions:
                q.correct_count = 2
        assert manager.get_next_question(sample_state) is None

    def test_prioritizes_locked_paragraphs_excluded(self, manager: GameManager, sample_state: GameState):
        # First para questions mastered, second not unlocked → should return None
        # (no unlocked paragraphs with non-mastered questions)
        for q in sample_state.paragraphs[0].questions:
            q.correct_count = 2
        result = manager.get_next_question(sample_state)
        assert result is None


class TestHasUnprocessedParagraphs:
    def test_true_when_locked_paragraphs_empty(self, manager: GameManager):
        state = GameState(
            project_name="test",
            paragraphs=[
                ParagraphState(index=0, unlocked=True, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q?", correct_answer=["true"]),
                ]),
                ParagraphState(index=1, unlocked=False, questions=[]),
            ],
        )
        assert manager.has_unprocessed_paragraphs(state) is True

    def test_false_when_all_paragraphs_have_questions(self, manager: GameManager):
        state = GameState(
            project_name="test",
            paragraphs=[
                ParagraphState(index=0, unlocked=True, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q?", correct_answer=["true"]),
                ]),
                ParagraphState(index=1, unlocked=False, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q2?", correct_answer=["false"]),
                ]),
            ],
        )
        assert manager.has_unprocessed_paragraphs(state) is False

    def test_false_when_all_locked_but_with_questions(self, manager: GameManager):
        state = GameState(
            project_name="test",
            paragraphs=[
                ParagraphState(index=0, unlocked=False, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q?", correct_answer=["true"]),
                ]),
                ParagraphState(index=1, unlocked=False, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q2?", correct_answer=["false"]),
                ]),
            ],
        )
        assert manager.has_unprocessed_paragraphs(state) is False

    def test_false_when_all_unlocked_and_answered(self, manager: GameManager):
        state = GameState(
            project_name="test",
            paragraphs=[
                ParagraphState(index=0, unlocked=True, questions=[
                    QuestionRecord(question_type="true_false", question_text="Q?", correct_answer=["true"]),
                ]),
                ParagraphState(index=1, unlocked=True, questions=[]),
            ],
        )
        # All unlocked, no locked empty paragraphs → should be False
        assert manager.has_unprocessed_paragraphs(state) is False


class TestSubmitAnswer:
    def test_correct_answer_updates_counts(self, manager: GameManager, sample_state: GameState):
        result = manager.submit_answer(sample_state, 0, 0, "A")
        assert result["correct"] is True
        assert result["correct_count"] == 1
        assert result["wrong_count"] == 0
        assert sample_state.paragraphs[0].questions[0].correct_count == 1

    def test_wrong_answer_updates_counts(self, manager: GameManager, sample_state: GameState):
        result = manager.submit_answer(sample_state, 0, 0, "B")
        assert result["correct"] is False
        assert result["correct_count"] == 0
        assert result["wrong_count"] == 1

    def test_just_mastered(self, manager: GameManager, sample_state: GameState):
        sample_state.paragraphs[0].questions[0].correct_count = 1
        result = manager.submit_answer(sample_state, 0, 0, "A")
        assert result["just_mastered"] is True
        assert result["is_mastered"] is True

    def test_case_insensitive_answer(self, manager: GameManager, sample_state: GameState):
        result = manager.submit_answer(sample_state, 0, 0, "a")
        assert result["correct"] is True

    def test_unlock_next_paragraph(self, manager: GameManager, sample_state: GameState):
        # Answer all questions in para 0 correctly once → para 1 should unlock
        sample_state.paragraphs[0].questions[0].correct_count = 1
        sample_state.paragraphs[0].questions[1].correct_count = 1
        # Answer Q3 correctly to trigger unlock check
        result = manager.submit_answer(sample_state, 0, 2, "answer")
        assert result["correct"] is True
        assert sample_state.paragraphs[1].unlocked is True


class TestStoreQuestions:
    def test_store_questions(self, manager: GameManager):
        manager.init_game("storetest", 2)
        questions = [
            {"type": "true_false", "question": "Test?", "correct_answer": ["true"]},
            {"type": "true_false", "question": "Is it?", "correct_answer": ["true"]},
        ]
        manager.store_questions("storetest", 0, questions)
        state = manager.load_state("storetest")
        assert state is not None
        assert len(state.paragraphs[0].questions) == 2
        assert state.paragraphs[0].questions[0].question_type == "true_false"
        assert state.paragraphs[0].questions[1].correct_answer == ["true"]


class TestResetGame:
    def test_reset_clears_counts(self, manager: GameManager):
        state = manager.init_game("resetme", 2)
        manager.store_questions("resetme", 0, [
            {"type": "mc", "question": "Q?", "correct_answer": "A"},
        ])
        manager.store_questions("resetme", 1, [
            {"type": "mc", "question": "Q2?", "correct_answer": "B"},
        ])

        # Add some progress
        loaded = manager.load_state("resetme")
        assert loaded is not None
        manager.submit_answer(loaded, 0, 0, "A")
        loaded.paragraphs[1].unlocked = True
        manager.submit_answer(loaded, 1, 0, "B")

        # Reset
        state2 = manager.reset_game("resetme", 2)
        assert state2.paragraphs[0].unlocked is True
        assert state2.paragraphs[1].unlocked is False  # locked again
        assert state2.paragraphs[0].questions[0].correct_count == 0
        assert state2.paragraphs[1].questions[0].correct_count == 0


class TestPersistState:
    def test_save_creates_file(self, manager: GameManager, fake_file_manager):
        manager.init_game("persist", 1)
        path = fake_file_manager.project_path("persist") / "game_state.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["project_name"] == "persist"
        assert len(data["paragraphs"]) == 1

    def test_load_empty_file_returns_none(self, manager: GameManager, fake_file_manager):
        path = fake_file_manager.project_path("emptyproj") / "game_state.json"
        path.write_text("", encoding="utf-8")
        state = manager.load_state("emptyproj")
        assert state is None
