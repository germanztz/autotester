"""Tests for app.services.question_engine — QuestionEngine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.game_state import GameManager
from app.services.question_engine import QuestionEngine
from app.services.question_generator import QuestionGenerator


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Returns canned questions."""

    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.call_count += 1
        return json.dumps([
            {"type": "multiple_choice", "question": "Q1?", "options": ["A", "B", "C"], "correct_answer": "A"},
            {"type": "options_choice", "question": "Q2?", "correct_answer": "true"},
            {"type": "fill_blank", "question": "Q3 ___", "correct_answer": "word"},
            {"type": "short_answer", "question": "Q4?", "correct_answer": "ans"},
        ])


class _FakeConfigManager:
    def load(self) -> dict:
        return {
            "game": {
                "language": "es",
                "questions_per_paragraph": 3,
                "correct_to_master": 2,
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
            "original_text": f"This is paragraph {i} with some text content for testing purposes.",
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


class TestStartGame:
    def test_start_new_game(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "newproj", 3)
        result = engine.start_game("newproj")
        assert result["status"] in ("generating", "ready")
        assert result["total_paragraphs"] == 3

    def test_start_existing_game(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "existing", 2)
        engine.start_game("existing")
        engine.generate_paragraph_questions("existing", 0)
        result = engine.start_game("existing")
        assert result["status"] == "ready"


class TestGenerateParagraphQuestions:
    def test_generates_and_stores(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "genproj", 2)
        engine.start_game("genproj")
        ok = engine.generate_paragraph_questions("genproj", 0)
        assert ok is True

        state = engine.game_manager.load_state("genproj")
        assert state is not None
        assert len(state.paragraphs[0].questions) > 0

    def test_out_of_range(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "nopara", 1)
        engine.start_game("nopara")
        ok = engine.generate_paragraph_questions("nopara", 99)
        assert ok is False


class TestGenerateAllQuestions:
    def test_generates_all(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "allproj", 3)
        engine.start_game("allproj")
        result = engine.generate_all_questions("allproj")
        assert result["status"] == "ready"
        assert result["generated"] == 3
        assert result["total_paragraphs"] == 3

    def test_progress_callback(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "cbproj", 2)
        engine.start_game("cbproj")
        events = []
        engine.generate_all_questions("cbproj", on_progress=lambda e: events.append(e))
        assert len(events) == 2
        assert events[0]["phase"] == "question_gen"
        assert events[0]["current"] == 1


class TestGetGameStatus:
    def test_not_started(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "nostart", 1)
        status = engine.get_game_status("nostart")
        assert status["status"] == "not_started"

    def test_generating(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "gentest", 1)
        engine.start_game("gentest")
        status = engine.get_game_status("gentest")
        assert status["status"] in ("generating", "ready")

    def test_playing(self, engine: QuestionEngine, fake_file_manager):
        _write_chunks(fake_file_manager.root, "playtest", 1)
        engine.start_game("playtest")
        engine.generate_paragraph_questions("playtest", 0)
        status = engine.get_game_status("playtest")
        assert status["status"] == "playing"
        assert "progress_pct" in status
