"""Tests for app.services.question_engine — QuestionEngine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.game_state import GameManager, QuestionRecord
from app.services.question_engine import QuestionEngine
from app.services.question_generator import QuestionGenerator


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Returns canned true/false questions."""

    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.call_count += 1
        return json.dumps({
            "type": "true_false",
            "question": "Generated LLM question?",
            "correct_answer": "true",
        })


class _FakeConfigManager:
    def load(self) -> dict:
        return {
            "game": {
                "language": "es",
                "questions_per_paragraph": 3,
                "correct_to_master": 2,
            },
            "ia": {
                "ollama_model": "test-model",
                "question_true_false_user_prompt_tpl": (
                    'Generate a true/false question in {language} '
                    'targeting keyword "{keyword}" with answer {target_response}. '
                    'Text: {text}'
                ),
            },
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_file_manager(tmp_path: Path):
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
def fake_config() -> _FakeConfigManager:
    return _FakeConfigManager()


@pytest.fixture
def engine(fake_file_manager, fake_config) -> QuestionEngine:
    llm = _FakeLLM()
    qg = QuestionGenerator(llm, fake_config)
    gm = GameManager(fake_file_manager, fake_config)
    return QuestionEngine(fake_file_manager, fake_config, qg, gm)


def _write_chunks(projects_root: Path, project_name: str, num: int = 2):
    """Create digest.json with chunks for a project."""
    proj_dir = projects_root / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "original_text": f"keyword{i}_a is an important concept. keyword{i}_b is related to it. This paragraph has text for testing.",
            "text_keywords": [f"keyword{i}_a", f"keyword{i}_b"],
            "page_number": 1,
        }
        for i in range(num)
    ]
    digest = {"state": "complete", "chunks": chunks, "updated_at": 0.0}
    (proj_dir / "digest.json").write_text(json.dumps(digest), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlanQuestions:
    def test_plans_all_questions(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "planproj", 2)
        result = engine.plan_questions("planproj")
        assert result["status"] == "generating"
        assert result["total_paragraphs"] == 2
        assert result["total_questions"] > 0
        assert result["pending"] > 0

        state = engine.game_manager.load_state("planproj")
        assert state is not None
        assert len(state.paragraphs) == 2

    def test_planned_questions_have_correct_types(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "typesproj", 1)
        engine.plan_questions("typesproj")

        state = engine.game_manager.load_state("typesproj")
        assert state is not None
        questions = state.paragraphs[0].questions

        # INFO and FILL should be generated, TRUE_FALSE should be pending
        types = {q.question_type for q in questions}
        assert "info" in types
        assert "fill" in types
        assert "true_false" in types

        tf_qs = [q for q in questions if q.question_type == "true_false"]
        for q in tf_qs:
            assert q.status == "pending"

        info_qs = [q for q in questions if q.question_type == "info"]
        fill_qs = [q for q in questions if q.question_type == "fill"]
        for q in info_qs:
            assert q.status == "generated"
        for q in fill_qs:
            assert q.status == "generated"

    def test_question_order_follows_titles(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "orderproj", 1)
        engine.plan_questions("orderproj")

        state = engine.game_manager.load_state("orderproj")
        assert state is not None
        questions = state.paragraphs[0].questions

        # Order should follow _TITLES: INFO → FILL → TRUE_FALSE
        # First question should be INFO
        assert questions[0].question_type == "info"
        # Then FILL questions (one per keyword)
        fill_types = [q.question_type for q in questions if q.question_type == "fill"]
        true_false_types = [q.question_type for q in questions if q.question_type == "true_false"]
        # All fill before true_false
        if fill_types and true_false_types:
            last_fill = max(i for i, q in enumerate(questions) if q.question_type == "fill")
            first_tf = min(i for i, q in enumerate(questions) if q.question_type == "true_false")
            assert last_fill < first_tf


class TestGenerateNextPending:
    def test_generates_one_pending_question(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "nextproj", 1)
        engine.plan_questions("nextproj")

        state = engine.game_manager.load_state("nextproj")
        pending_before = sum(1 for p in state.paragraphs for q in p.questions if q.status == "pending")

        has_more = engine.generate_next_pending("nextproj")

        state = engine.game_manager.load_state("nextproj")
        pending_after = sum(1 for p in state.paragraphs for q in p.questions if q.status == "pending")

        assert pending_after == pending_before - 1
        generated = [q for p in state.paragraphs for q in p.questions if q.status == "generated" and q.question_type == "true_false"]
        assert len(generated) >= 1

    def test_returns_true_when_more_pending(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "moreproj", 2)
        engine.plan_questions("moreproj")

        has_more = engine.generate_next_pending("moreproj")
        assert has_more is True

    def test_returns_false_when_all_done(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "doneproj", 1)
        engine.plan_questions("doneproj")

        while True:
            has_more = engine.generate_next_pending("doneproj")
            if not has_more:
                break

        assert has_more is False


class TestGenerateAllQuestions:
    def test_generates_all_pending(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "allproj", 2)
        result = engine.generate_all_questions("allproj")
        assert result["status"] == "ready"

        state = engine.game_manager.load_state("allproj")
        assert state is not None
        pending = sum(1 for p in state.paragraphs for q in p.questions if q.status == "pending")
        assert pending == 0


class TestStartGame:
    def test_start_new_game(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "newproj", 3)
        result = engine.start_game("newproj")
        # After planning, INFO and FILL are already generated — return ready
        assert result["status"] == "ready"
        assert result["total_paragraphs"] == 3

    def test_start_existing_game_returns_ready(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "existing", 2)
        engine.plan_questions("existing")

        # Generate all pending
        engine.generate_all_questions("existing")

        result = engine.start_game("existing")
        assert result["status"] == "ready"


class TestGetGameStatus:
    def test_not_started(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "nostart", 1)
        status = engine.get_game_status("nostart")
        assert status["status"] == "not_started"

    def test_playing_with_pending(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "gentest", 1)
        engine.plan_questions("gentest")
        status = engine.get_game_status("gentest")
        # INFO and FILL are generated, so we can play even with pending TRUE_FALSE
        assert status["status"] == "playing"
        assert "pending" in status

    def test_playing(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "playtest", 1)
        engine.plan_questions("playtest")
        engine.generate_all_questions("playtest")
        status = engine.get_game_status("playtest")
        assert status["status"] == "playing"
        assert "progress_pct" in status
