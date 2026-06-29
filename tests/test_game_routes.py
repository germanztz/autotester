"""Tests for the game controller endpoints (app/controllers/game_controller.py)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


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


def _fake_questions(*args, **kwargs):
    """Replace LLM.generate() with a canned response."""
    return json.dumps([
        {"type": "multiple_choice", "question": "Test Q?", "options": ["A", "B", "C"], "correct_answer": "A"},
        {"type": "true_false", "question": "Is it?", "correct_answer": "true"},
        {"type": "fill_blank", "question": "Fill ___", "correct_answer": "blank"},
        {"type": "short_answer", "question": "Short?", "correct_answer": "answer"},
    ])


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

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions)
    def test_returns_question_after_generation(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "quizproj", 1)
        client.post("/game/quizproj/start")

        from flask import current_app
        with client.application.app_context():
            engine = current_app.extensions["question_engine"]
            engine.generate_paragraph_questions("quizproj", 0)

        resp = client.get("/game/quizproj/next")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "question" in data
        assert "type" in data
        assert "para_idx" in data


class TestAnswer:
    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions)
    def test_submit_correct_answer(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "ansproj", 1)
        client.post("/game/ansproj/start")

        from flask import current_app
        with client.application.app_context():
            engine = current_app.extensions["question_engine"]
            engine.generate_paragraph_questions("ansproj", 0)

        next_resp = client.get("/game/ansproj/next")
        next_data = next_resp.get_json()

        resp = client.post(
            "/game/ansproj/answer",
            data=json.dumps({
                "para_idx": next_data["para_idx"],
                "q_idx": next_data["q_idx"],
                "answer": "A",
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
    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions)
    def test_reset_game(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "resetproj", 1)
        client.post("/game/resetproj/start")

        from flask import current_app
        with client.application.app_context():
            engine = current_app.extensions["question_engine"]
            engine.generate_paragraph_questions("resetproj", 0)

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
    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions)
    def test_history_returns_answered_questions(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "histproj", 1)
        client.post("/game/histproj/start")

        from flask import current_app
        with client.application.app_context():
            engine = current_app.extensions["question_engine"]
            engine.generate_paragraph_questions("histproj", 0)

        next_resp = client.get("/game/histproj/next")
        next_data = next_resp.get_json()

        client.post(
            "/game/histproj/answer",
            data=json.dumps({
                "para_idx": next_data["para_idx"],
                "q_idx": next_data["q_idx"],
                "answer": "A",
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
        assert entry["last_answer"] == "A"
        assert entry["last_answer_correct"] is True
        assert entry["correct_answer"] == "A"

    def test_history_empty_when_no_game(self, client, temp_workspace: dict):
        _make_project_with_chunks(temp_workspace["projects"], "nohist", 1)
        resp = client.get("/game/nohist/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert data["history"] == []
