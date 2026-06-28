"""Question generator — uses LLM to create quiz questions from text chunks."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.utils.logging_setup import get_logger

logger = get_logger()

_QUESTION_SYSTEM_PROMPT = (
    "You are a quiz generator that creates questions to help someone memorize "
    "document content. Respond only with valid JSON, no extra text."
)

_QUESTION_USER_PROMPT_TPL = (
    "Based on the following text and its keywords, create {count} questions "
    "in {language} to help memorize the content. "
    "Use a mix of question types:\n"
    '- "multiple_choice": question with 4 options, one correct\n'
    '- "true_false": statement to verify\n'
    '- "fill_blank": sentence with a missing word (use ___ for the blank)\n'
    '- "short_answer": question answerable in 1-3 words\n\n'
    "Keywords: {keywords}\n\n"
    "Text:\n{text}\n\n"
    "Return a JSON array of objects. Each object must have:\n"
    '- "type": one of "multiple_choice", "true_false", "fill_blank", "short_answer"\n'
    '- "question": the question text\n'
    '- "options": ["A", "B", "C", "D"]  (only for multiple_choice)\n'
    '- "correct_answer": the correct answer\n'
)

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0


class QuestionGenerator:
    """Generate quiz questions from text chunks using an LLM."""

    def __init__(self, llm_client: Any, config_manager: Any) -> None:
        self.llm = llm_client
        self.config_manager = config_manager

    def generate(
        self,
        chunk_text: str,
        keywords: list[str],
        count: int = 5,
        language: str = "es",
        model: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Generate quiz questions from a text chunk.

        Args:
            chunk_text: The paragraph text.
            keywords: Extracted keywords for this chunk.
            count: Number of questions to generate.
            language: Language code for questions (e.g., "es", "en").
            model: Ollama model name. Falls back to game config, then IA config.

        Returns:
            List of question dicts with keys: type, question, options?, correct_answer.

        Raises:
            RuntimeError: If the LLM fails after all retries or returns invalid JSON.
        """
        if not model:
            cfg = self.config_manager.load()
            game_cfg = cfg.get("game", {})
            ia_cfg = cfg.get("ia", {})
            model = game_cfg.get("model") or ia_cfg.get("ollama_model", "qwen3.5:latest")

        prompt = _QUESTION_USER_PROMPT_TPL.format(
            count=count,
            language=language,
            keywords=", ".join(keywords),
            text=chunk_text,
        )

        last_error: Optional[str] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = self.llm.generate(
                    model,
                    prompt,
                    system=_QUESTION_SYSTEM_PROMPT,
                    format_json=False,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Question generation attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, last_error,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY_SECONDS * attempt)
                continue

            questions = self._parse_response(raw, count)
            if questions is not None:
                logger.info(
                    "Generated %d questions | model=%s language=%s",
                    len(questions), model, language,
                )
                return questions

            last_error = "Invalid JSON response from LLM"
            logger.warning(
                "Question generation attempt %d/%d: %s",
                attempt, _MAX_RETRIES, last_error,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)

        raise RuntimeError(
            f"Question generation failed after {_MAX_RETRIES} attempts: {last_error}"
        )

    def _parse_response(
        self, raw: str, expected_count: int
    ) -> Optional[list[dict[str, Any]]]:
        """Parse and validate the LLM JSON response.

        Returns a list of question dicts, or None if parsing fails.
        """
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, list):
            return None

        valid_types = {"multiple_choice", "true_false", "fill_blank", "short_answer"}
        questions: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            q_type = item.get("type", "")
            if q_type not in valid_types:
                continue
            question_text = (item.get("question") or "").strip()
            if not question_text:
                continue
            correct_answer = (item.get("correct_answer") or "").strip()
            if not correct_answer:
                continue
            entry: dict[str, Any] = {
                "type": q_type,
                "question": question_text,
                "correct_answer": correct_answer,
            }
            if q_type == "multiple_choice":
                options = item.get("options", [])
                if isinstance(options, list) and len(options) >= 2:
                    entry["options"] = options
                else:
                    continue  # skip invalid multiple choice
            questions.append(entry)

        return questions if questions else None
