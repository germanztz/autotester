"""Question engine — orchestrates question generation and game state."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from app.services.question_generator import QuestionGenerator
from app.models.game_state import GameManager
from app.utils.logging_setup import get_logger

logger = get_logger()


class QuestionEngine:
    """Orchestrates question generation and game lifecycle.

    Wires together file_manager (for chunks.json), QuestionGenerator,
    and GameManager.
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

    def _digest_path(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name) / "digest.json"

    def _load_chunks(self, project_name: str) -> list[dict[str, Any]]:
        """Load chunks from digest.json."""
        path = self._digest_path(project_name)
        if not path.exists():
            raise FileNotFoundError(f"digest.json not found for {project_name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
        if not chunks:
            raise FileNotFoundError(f"no chunks in digest.json for {project_name}")
        return chunks

    def start_game(self, project_name: str) -> dict[str, Any]:
        """Initialize game state and optionally generate questions synchronously.

        Returns game status with generation progress.
        """
        existing = self.game_manager.load_state(project_name)
        if existing is not None and any(
            p.questions for p in existing.paragraphs
        ):
            # Game already has questions — just return status
            stats = self.game_manager.get_stats(existing)
            return {"status": "ready", **stats}

        chunks = self._load_chunks(project_name)
        num_paragraphs = len(chunks)
        state = self.game_manager.init_game(project_name, num_paragraphs)

        cfg = self.config_manager.load()
        game_cfg = cfg.get("game", {})
        language = game_cfg.get("language", "es")
        qpp = game_cfg.get("questions_per_paragraph", 5)

        return {
            "status": "generating",
            "total_paragraphs": num_paragraphs,
            "generated": 0,
        }

    def generate_paragraph_questions(
        self, project_name: str, para_idx: int
    ) -> bool:
        """Generate and store questions for a single paragraph.

        Returns True if successful, False otherwise.
        """
        try:
            chunks = self._load_chunks(project_name)
            if para_idx >= len(chunks):
                logger.warning(
                    "Paragraph index %d out of range for %s",
                    para_idx, project_name,
                )
                return False

            chunk = chunks[para_idx]
            cfg = self.config_manager.load()
            game_cfg = cfg.get("game", {})
            language = game_cfg.get("language", "es")
            qpp = game_cfg.get("questions_per_paragraph", 5)

            questions = self.generator.generate(
                chunk_text=chunk["original_text"],
                keywords=chunk.get("text_keywords", []),
                count=qpp,
                language=language,
            )
            self.game_manager.store_questions(project_name, para_idx, questions)
            logger.info(
                "Generated %d questions for paragraph %d of %s",
                len(questions), para_idx, project_name,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to generate questions for paragraph %d of %s: %s",
                para_idx, project_name, exc,
            )
            return False

    def generate_all_questions(
        self, project_name: str, on_progress: Optional[callable] = None
    ) -> dict[str, Any]:
        """Generate questions for all paragraphs. Returns stats dict."""
        chunks = self._load_chunks(project_name)
        total = len(chunks)
        generated = 0
        failed = 0

        for idx in range(total):
            ok = self.generate_paragraph_questions(project_name, idx)
            if ok:
                generated += 1
            else:
                failed += 1
            if on_progress:
                on_progress({
                    "phase": "question_gen",
                    "current": idx + 1,
                    "total": total,
                    "generated": generated,
                    "failed": failed,
                })

        state = self.game_manager.load_state(project_name)
        stats = self.game_manager.get_stats(state) if state else {}

        return {
            "status": "ready",
            "total_paragraphs": total,
            "generated": generated,
            "failed": failed,
            **stats,
        }

    def get_game_status(self, project_name: str) -> dict[str, Any]:
        """Return current game status for a project."""
        state = self.game_manager.load_state(project_name)
        if state is None:
            return {"status": "not_started"}

        total_questions = sum(len(p.questions) for p in state.paragraphs)
        if total_questions == 0:
            return {"status": "generating"}

        stats = self.game_manager.get_stats(state)
        return {"status": "playing", **stats}
