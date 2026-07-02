"""Game controller — quiz gameplay routes."""
from __future__ import annotations

import random

from flask import Blueprint, current_app, jsonify, request

from app.utils.logging_setup import get_logger

game_bp = Blueprint("game", __name__, url_prefix="/game")
logger = get_logger()


def _get_engine():
    return current_app.extensions["question_engine"]


@game_bp.route("/<project_name>/start", methods=["POST"])
def start(project_name: str):
    """Start (or resume) a game session for a project.

    If questions have not been planned yet, plans them.
    If pending questions remain, submits sequential generation to JobRunner.
    """
    engine = _get_engine()
    try:
        result = engine.start_game(project_name)
        if result.get("status") == "error":
            return jsonify({"error": result.get("error", "Unknown error")}), 404
        if result.get("pending", 0) > 0:
            job_runner = current_app.extensions.get("job_runner")
            if job_runner:
                job_runner.submit(engine.generate_all_questions, project_name)
        return jsonify(result), 200
    except FileNotFoundError as exc:
        logger.warning("Game start failed: %s", exc)
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error("Game start error for %s: %s", project_name, exc)
        return jsonify({"error": f"Failed to start game: {exc}"}), 500


@game_bp.route("/<project_name>/status", methods=["GET"])
def status(project_name: str):
    """Return current game status (progress, generation state)."""
    engine = _get_engine()
    try:
        result = engine.get_game_status(project_name)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("Game status error for %s: %s", project_name, exc)
        return jsonify({"error": str(exc)}), 500


@game_bp.route("/<project_name>/next", methods=["GET"])
def next_question(project_name: str):
    """Return the next question for the user.

    Only ``status == "generated"`` questions are eligible.
    """
    engine = _get_engine()
    state = engine.game_manager.load_state(project_name)
    if state is None:
        return jsonify({"error": "Game not started. Call /game/<name>/start first."}), 400

    total = sum(
        1 for p in state.paragraphs for q in p.questions if q.status == "generated"
    )
    if total == 0:
        return jsonify({"status": "generating", "message": "Questions are being generated."}), 202

    result = engine.game_manager.get_next_question(state)
    if result is None:
        stats = engine.game_manager.get_stats(state)
        if engine.game_manager.has_unprocessed_paragraphs(state):
            return jsonify({"status": "waiting", **stats}), 200
        if engine.is_generation_active(project_name):
            return jsonify({"status": "waiting", **stats}), 200
        if engine._is_digest_active(project_name):
            return jsonify({"status": "waiting", **stats}), 200
        return jsonify({"status": "complete", **stats}), 200

    para_idx, q_idx, question = result
    question_data = {
        "para_idx": para_idx,
        "q_idx": q_idx,
        "title": question.title,
        "type": question.question_type,
        "question": question.question_text,
        "progress_pct": engine.game_manager.calculate_progress(state),
    }
    if question.question_type in ("info", "fill", "true_false"):
        if question.question_type == "true_false":
            opts = ["True", "False"]
            random.shuffle(opts)
        else:
            opts = list(question.options)
            random.shuffle(opts)
        question_data["options"] = opts

    return jsonify(question_data), 200


@game_bp.route("/<project_name>/answer", methods=["POST"])
def answer(project_name: str):
    """Submit an answer and get feedback."""
    data = request.get_json(silent=True) or {}
    para_idx = data.get("para_idx")
    q_idx = data.get("q_idx")
    user_answer = (data.get("answer") or "").strip()

    if para_idx is None or q_idx is None or not user_answer:
        return jsonify({"error": "Missing para_idx, q_idx, or answer"}), 400

    engine = _get_engine()
    state = engine.game_manager.load_state(project_name)
    if state is None:
        return jsonify({"error": "Game not started."}), 400

    try:
        result = engine.game_manager.submit_answer(
            state, int(para_idx), int(q_idx), user_answer
        )
        return jsonify(result), 200
    except (IndexError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@game_bp.route("/<project_name>/history", methods=["GET"])
def history(project_name: str):
    """Return the last 10 answered questions for chat reconstruction."""
    engine = _get_engine()
    state = engine.game_manager.load_state(project_name)
    if state is None:
        return jsonify({"history": []}), 200

    entries = engine.game_manager.get_history(state, count=10)
    return jsonify({"history": entries}), 200


@game_bp.route("/<project_name>/reset", methods=["POST"])
def reset(project_name: str):
    """Reset game progress for a project."""
    engine = _get_engine()
    state = engine.game_manager.load_state(project_name)
    if state is None:
        return jsonify({"error": "Game not started."}), 400

    num_paragraphs = len(state.paragraphs)
    try:
        new_state = engine.game_manager.reset_game(project_name, num_paragraphs)
        stats = engine.game_manager.get_stats(new_state)
        logger.info("Game reset for %s", project_name)
        return jsonify({"status": "reset", **stats}), 200
    except Exception as exc:
        logger.error("Game reset error for %s: %s", project_name, exc)
        return jsonify({"error": str(exc)}), 500
