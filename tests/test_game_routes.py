"""Tests for the game controller endpoints (app/controllers/game_controller.py)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.game_state import GameState, ParagraphState, QuestionRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_project_with_chunks(projects_dir: Path, name: str, num_chunks: int = 2):
    """Create a project directory with digest.json (simulating a digested project)."""
    proj = projects_dir / name
    proj.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "original_text": "Paragraph content for testing. " * 10,
            "text_keywords": ["kw_a", "kw_b"],
            "page_number": 1,
        }
        for i in range(num_chunks)
    ]
    digest = {"state": "complete", "chunks": chunks, "updated_at": 0.0}
    (proj / "digest.json").write_text(json.dumps(digest), encoding="utf-8")
    return proj


def _make_project_with_generated_question(projects_dir: Path, name: str):
    """Create a project with a single generated question in game_state."""
    proj = _make_project_with_chunks(projects_dir, name, 1)
    game_state = {
        "project_name": name,
        "paragraphs": [
            {
                "index": 0,
                "unlocked": True,
                "questions": [
                    QuestionRecord(
                        id=1,
                        title="True or False",
                        question_type="true_false",
                        question_text="Test Q?",
                        options=["True", "False"],
                        correct_answer=["true"],
                        status="generated",
                    ).to_dict(),
                ],
            },
        ],
        "updated_at": 0.0,
    }
    (proj / "game_state.json").write_text(
        json.dumps(game_state), encoding="utf-8",
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStartGame:
    def test_start_new_game_returns_status(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "newproj", 2)
        resp = client.post("/game/newproj/start")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["status"] in ("generating", "ready")

    def test_start_missing_project_returns_404(self, client):
        resp = client.post("/game/ghost/start")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data is not None
        assert "error" in data


class TestGameStatus:
    def test_not_started(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "nostart", 1)
        resp = client.get("/game/nostart/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["status"] == "not_started"

    def test_after_start(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "started", 1)
        client.post("/game/started/start")
        resp = client.get("/game/started/status")
        assert resp.status_code == 200


class TestNextQuestion:
    def test_requires_start(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "nostart2", 1)
        resp = client.get("/game/nostart2/next")
        assert resp.status_code == 400
        assert "not started" in resp.get_json()["error"].lower()

    def test_returns_question_after_generation(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "quizproj", 1)

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            mgr.init_game("quizproj", 1)
            state = mgr.load_state("quizproj")
            assert state is not None
            state.paragraphs[0].questions = [
                QuestionRecord(
                    id=1,
                    title="True or False",
                    question_type="true_false",
                    question_text="Test Q?",
                    options=["True", "False"],
                    correct_answer=["true"],
                    status="generated",
                ),
            ]
            mgr.save_state("quizproj", state)

        resp = client.get("/game/quizproj/next")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "question" in data
        assert "type" in data
        assert "para_idx" in data


class TestAnswer:
    def test_submit_correct_answer(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "ansproj", 1)

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            mgr.init_game("ansproj", 1)
            state = mgr.load_state("ansproj")
            assert state is not None
            state.paragraphs[0].questions = [
                QuestionRecord(
                    id=1,
                    title="True or False",
                    question_type="true_false",
                    question_text="Test Q?",
                    options=["True", "False"],
                    correct_answer=["true"],
                    status="generated",
                ),
            ]
            mgr.save_state("ansproj", state)

        next_resp = client.get("/game/ansproj/next")
        next_data = next_resp.get_json()

        resp = client.post(
            "/game/ansproj/answer",
            data=json.dumps({
                "para_idx": next_data["para_idx"],
                "q_idx": next_data["q_idx"],
                "answer": "true",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        result = resp.get_json()
        assert result is not None
        assert "correct" in result
        assert "progress_pct" in result

    def test_missing_params(self, client, temp_workspace: dict):
        resp = client.post(
            "/game/dummy/answer",
            data=json.dumps({"para_idx": 0}),
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestReset:
    def test_reset_game(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "resetproj", 1)

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            mgr.init_game("resetproj", 1)
            state = mgr.load_state("resetproj")
            assert state is not None
            state.paragraphs[0].questions = [
                QuestionRecord(
                    id=1,
                    title="True or False",
                    question_type="true_false",
                    question_text="Q1?",
                    correct_answer=["true"],
                    status="generated",
                ),
            ]
            mgr.save_state("resetproj", state)

        resp = client.post("/game/resetproj/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["status"] == "reset"
        assert data["progress_pct"] == 0.0

    def test_reset_not_started(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "noreset", 1)
        resp = client.post("/game/noreset/reset")
        assert resp.status_code == 400


class TestHistory:
    def test_history_returns_answered_questions(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "histproj", 1)

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            mgr.init_game("histproj", 1)
            state = mgr.load_state("histproj")
            assert state is not None
            state.paragraphs[0].questions = [
                QuestionRecord(
                    id=1,
                    title="True or False",
                    question_type="true_false",
                    question_text="Test Q?",
                    options=["True", "False"],
                    correct_answer=["true"],
                    status="generated",
                ),
            ]
            mgr.save_state("histproj", state)

        next_resp = client.get("/game/histproj/next")
        next_data = next_resp.get_json()

        client.post(
            "/game/histproj/answer",
            data=json.dumps({
                "para_idx": next_data["para_idx"],
                "q_idx": next_data["q_idx"],
                "answer": "true",
            }),
            content_type="application/json",
        )

        resp = client.get("/game/histproj/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "history" in data
        assert len(data["history"]) == 1
        entry = data["history"][0]
        assert entry["question_text"] == "Test Q?"
        assert entry["last_answer"] == "true"
        assert entry["last_answer_correct"] is True
        assert entry["correct_answer"] == ["true"]

    def test_history_empty_when_no_game(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "nohist", 1)
        resp = client.get("/game/nohist/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["history"] == []


class TestWaitingState:
    """When all questions are answered but the digest is still processing,
    ``/game/next`` should return ``{"status": "waiting"}`` so the frontend
    shows a "Thinking…" bubble instead of premature congratulations."""

    def _make_game_state(self, projects_dir, name):
        proj = projects_dir / name
        proj.mkdir(parents=True, exist_ok=True)

        digest = {
            "state": "processing",
            "chunks": [
                {"original_text": "Content.", "text_keywords": ["kw"], "page_number": 1},
            ],
            "chunks_processed": 1,
            "total_chunks": 3,
            "updated_at": 0.0,
        }
        (proj / "digest.json").write_text(json.dumps(digest), encoding="utf-8")

        game_state = {
            "project_name": name,
            "paragraphs": [
                {
                    "index": 0,
                    "unlocked": True,
                    "questions": [
                        QuestionRecord(
                            id=1,
                            title="Reading Check",
                            question_type="info",
                            question_text="Content.",
                            options=["Ok, i read it", "not yet"],
                            correct_answer=["Ok, i read it"],
                            correct_count=3,
                            correct_to_master=1,
                            status="generated",
                        ).to_dict(),
                    ],
                },
            ],
            "updated_at": 100.0,
        }
        (proj / "game_state.json").write_text(
            json.dumps(game_state), encoding="utf-8",
        )

    def test_returns_waiting_when_digest_processing(self, client, temp_workspace: dict):
        self._make_game_state(temp_workspace["projects"], "waitproj")
        resp = client.get("/game/waitproj/next")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["status"] == "waiting"

    def test_not_complete_when_digest_processing(self, client, temp_workspace: dict):
        self._make_game_state(temp_workspace["projects"], "waitproj2")
        resp = client.get("/game/waitproj2/next")
        data = resp.get_json()
        assert data["status"] != "complete"

    def test_returns_waiting_when_question_gen_active(self, client, temp_workspace: dict, app):
        self._make_game_state(temp_workspace["projects"], "bgwait")
        engine = app.extensions["question_engine"]
        engine._generation_active.add("bgwait")
        try:
            resp = client.get("/game/bgwait/next")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data is not None
            assert data["status"] == "waiting"
        finally:
            engine._generation_active.discard("bgwait")
