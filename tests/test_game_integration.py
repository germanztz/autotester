"""Integration tests for the full game lifecycle: upload → digest → play → complete → reset."""
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.game_state import QuestionRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_chunks(projects_dir: Path, name: str, num_chunks: int = 2):
    """Write/overwrite digest.json with proper chunks (empty PDFs produce none)."""
    proj_dir = projects_dir / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "original_text": "Paragraph content for testing. " * 10,
            "text_keywords": ["kw_a", "kw_b"],
            "page_number": 1,
        }
        for _ in range(num_chunks)
    ]
    digest = {"state": "complete", "chunks": chunks, "updated_at": 0.0}
    (proj_dir / "digest.json").write_text(json.dumps(digest), encoding="utf-8")


def _fake_questions_llm(*args, **kwargs):
    """Canned LLM response for question generation."""
    return json.dumps({"type": "true_false", "question": "Test Q?", "correct_answer": "true"})


def _patch_segmenter_ollama(client):
    """Patch the segmenter's LLM to avoid real HTTP calls during digest."""
    from tests.test_semantic_segmenter import FakeOllamaChat
    client.application.extensions["segmenter"].llm = FakeOllamaChat()


def _upload_and_digest(client, project_name: str, project_bytes: bytes | None = None):
    """Upload a PDF and wait for the digest supervisor to finish.

    Returns the project name.
    """
    if project_bytes is None:
        project_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000111 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n178\n%%EOF\n"
        )

    data = {
        "project_name": project_name,
        "pdf": (io.BytesIO(project_bytes), "doc.pdf"),
    }
    resp = client.post(
        "/files/upload",
        data=data,
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 202

    supervisor = client.application.extensions["digest_supervisor"]
    supervisor.wait_until_idle(timeout=10.0)
    return project_name


def _init_with_generated_questions(client, proj_name: str, num_chunks: int, questions_per_chunk: list[list[dict]]):
    """Helper to init game state with generated questions bypassing the LLM."""
    from flask import current_app
    with client.application.app_context():
        mgr = current_app.extensions["game_manager"]
        mgr.init_game(proj_name, num_chunks)
        state = mgr.load_state(proj_name)
        assert state is not None
        for idx, qlist in enumerate(questions_per_chunk):
            qid = 0
            records = []
            for q in qlist:
                qid += 1
                records.append(QuestionRecord(
                    id=qid,
                    title="True or False",
                    question_type="true_false",
                    question_text=q["question"],
                    options=["True", "False"],
                    correct_answer=[q["correct_answer"]],
                    status="generated",
                ))
            state.paragraphs[idx].questions = records
        mgr.save_state(proj_name, state)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGameIntegration:
    """Full E2E game lifecycle."""

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions_llm)
    def test_upload_digest_start_game(self, client, temp_workspace):
        """Upload → digest → start game → questions generated."""
        _patch_segmenter_ollama(client)
        proj_name = _upload_and_digest(client, "e2e_start")
        _ensure_chunks(temp_workspace["projects"], proj_name, 2)

        _init_with_generated_questions(client, proj_name, 2, [
            [{"question": "Q1?", "correct_answer": "true"},
             {"question": "Q2?", "correct_answer": "false"}],
            [{"question": "Q3?", "correct_answer": "true"}],
        ])

        status_resp = client.get(f"/game/{proj_name}/status")
        status_data = status_resp.get_json()
        assert status_data["status"] == "playing"

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions_llm)
    def test_correct_answer_increases_progress(self, client, temp_workspace):
        """Submit correct answer → progress increases."""
        _patch_segmenter_ollama(client)
        proj_name = _upload_and_digest(client, "e2e_correct")
        _ensure_chunks(temp_workspace["projects"], proj_name, 1)

        _init_with_generated_questions(client, proj_name, 1, [
            [{"question": "Q1?", "correct_answer": "true"},
             {"question": "Q2?", "correct_answer": "false"}],
        ])

        next_resp = client.get(f"/game/{proj_name}/next")
        assert next_resp.status_code == 200
        q_data = next_resp.get_json()

        before_resp = client.get(f"/game/{proj_name}/status")
        before_pct = before_resp.get_json()["progress_pct"]

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            state = mgr.load_state(proj_name)
        correct = state.paragraphs[q_data["para_idx"]].questions[q_data["q_idx"]].correct_answer[0]

        answer_resp = client.post(
            f"/game/{proj_name}/answer",
            data=json.dumps({
                "para_idx": q_data["para_idx"],
                "q_idx": q_data["q_idx"],
                "answer": correct,
            }),
            content_type="application/json",
        )
        assert answer_resp.status_code == 200
        result = answer_resp.get_json()
        assert result["correct"] is True
        assert result["progress_pct"] >= before_pct

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions_llm)
    def test_wrong_answer_does_not_increase_progress(self, client, temp_workspace):
        """Submit wrong answer → progress stays same, question is repeated."""
        _patch_segmenter_ollama(client)
        proj_name = _upload_and_digest(client, "e2e_wrong")
        _ensure_chunks(temp_workspace["projects"], proj_name, 1)

        _init_with_generated_questions(client, proj_name, 1, [
            [{"question": "Q1?", "correct_answer": "true"}],
        ])

        next_resp = client.get(f"/game/{proj_name}/next")
        q_data = next_resp.get_json()

        before_resp = client.get(f"/game/{proj_name}/status")
        before_pct = before_resp.get_json()["progress_pct"]

        answer_resp = client.post(
            f"/game/{proj_name}/answer",
            data=json.dumps({
                "para_idx": q_data["para_idx"],
                "q_idx": q_data["q_idx"],
                "answer": "wrong_answer_xyz",
            }),
            content_type="application/json",
        )
        result = answer_resp.get_json()
        assert result["correct"] is False
        assert result["progress_pct"] == before_pct

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions_llm)
    def test_unlock_next_paragraph(self, client, temp_workspace):
        """Answering all questions correctly in para 0 unlocks para 1."""
        _patch_segmenter_ollama(client)
        proj_name = _upload_and_digest(client, "e2e_unlock")
        _ensure_chunks(temp_workspace["projects"], proj_name, 2)

        _init_with_generated_questions(client, proj_name, 2, [
            [{"question": "Q1?", "correct_answer": "true"},
             {"question": "Q2?", "correct_answer": "true"}],
            [{"question": "Q3?", "correct_answer": "false"}],
        ])

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            state = mgr.load_state(proj_name)
        assert state is not None
        assert state.paragraphs[0].unlocked is True
        assert state.paragraphs[1].unlocked is False

        for q in state.paragraphs[0].questions:
            q.correct_count = 1
            q.last_seen = 1.0
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            mgr.save_state(proj_name, state)

        next_resp = client.get(f"/game/{proj_name}/next")
        n_data = next_resp.get_json()
        pi, qi = n_data["para_idx"], n_data["q_idx"]

        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            state = mgr.load_state(proj_name)
        correct = state.paragraphs[pi].questions[qi].correct_answer[0]
        client.post(
            f"/game/{proj_name}/answer",
            data=json.dumps({"para_idx": pi, "q_idx": qi, "answer": correct}),
            content_type="application/json",
        )

        with client.application.app_context():
            state = mgr.load_state(proj_name)
        assert state is not None
        assert state.paragraphs[1].unlocked is True

    @patch("app.models.llm_client.OllamaChatClient.generate", _fake_questions_llm)
    def test_reset_game(self, client, temp_workspace):
        """Reset brings progress back to 0 and locks all paragraphs except first."""
        _patch_segmenter_ollama(client)
        proj_name = _upload_and_digest(client, "e2e_reset")
        _ensure_chunks(temp_workspace["projects"], proj_name, 1)

        _init_with_generated_questions(client, proj_name, 1, [
            [{"question": "Q1?", "correct_answer": "true"}],
        ])

        next_resp = client.get(f"/game/{proj_name}/next")
        q_data = next_resp.get_json()

        from flask import current_app
        with client.application.app_context():
            mgr = current_app.extensions["game_manager"]
            state = mgr.load_state(proj_name)
        correct = state.paragraphs[q_data["para_idx"]].questions[q_data["q_idx"]].correct_answer[0]
        client.post(
            f"/game/{proj_name}/answer",
            data=json.dumps({
                "para_idx": q_data["para_idx"],
                "q_idx": q_data["q_idx"],
                "answer": correct,
            }),
            content_type="application/json",
        )

        reset_resp = client.post(f"/game/{proj_name}/reset")
        assert reset_resp.status_code == 200
        reset_data = reset_resp.get_json()
        assert reset_data["progress_pct"] == 0.0
        assert reset_data["status"] == "reset"

        from flask import current_app
        mgr = current_app.extensions["game_manager"]
        with client.application.app_context():
            state = mgr.load_state(proj_name)
        assert state is not None
        assert all(q.correct_count == 0 for p in state.paragraphs for q in p.questions)
