"""Question generator — uses LLM to create quiz questions from text chunks."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.models.config_manager import (
    _DEFAULT_SYSTEM_PROMPT,
    _DEFAULT_QUESTION_MIXED_USER_PROMPT_TPL,
    _DEFAULT_QUESTION_TRUE_FALSE_USER_PROMPT_TPL,
)
from app.utils.logging_setup import get_logger

logger = get_logger()

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
            ia_cfg = cfg.get("ia", {})
            model = ia_cfg.get("ollama_model", None)

        cfg = self.config_manager.load()
        tpl = cfg.get("ia", {}).get(
            "question_mixed_user_prompt_tpl",
            _DEFAULT_QUESTION_MIXED_USER_PROMPT_TPL,
        )
        prompt = tpl.format(
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
                    system=_DEFAULT_SYSTEM_PROMPT,
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

    def generate_true_false_questions(
        self,
        chunk_text: str,
        keywords: list[str],
        language: str = "es",
        model: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Generate one true/false question per keyword.

        Each keyword is assigned a target_response (true/false) alternating
        by index parity so not all correct answers are the same.  One LLM
        call is made per keyword using the configurable prompt template.

        Args:
            chunk_text: The paragraph text.
            keywords: Extracted keywords for this chunk.
            language: Language code for questions (e.g., "es", "en").
            model: Ollama model name. Falls back to game config, then IA config.

        Returns:
            List of question dicts with keys: type, question, correct_answer.

        Raises:
            RuntimeError: If the LLM fails after all retries or returns invalid JSON.
        """
        if not model:
            cfg = self.config_manager.load()
            ia_cfg = cfg.get("ia", {})
            model = ia_cfg.get("ollama_model", None)

        cfg = self.config_manager.load()
        tpl = cfg.get("ia", {}).get(
            "question_true_false_user_prompt_tpl",
            _DEFAULT_QUESTION_TRUE_FALSE_USER_PROMPT_TPL,
        )

        questions: list[dict[str, Any]] = []
        for idx, keyword in enumerate(keywords):
            target_response = "true" if idx % 2 == 0 else "false"
            prompt = tpl.format(
                text=chunk_text,
                keyword=keyword,
                target_response=target_response,
                language=language,
            )

            last_error: Optional[str] = None
            parsed: Optional[list[dict[str, Any]]] = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    raw = self.llm.generate(
                        model,
                        prompt,
                        system=_DEFAULT_SYSTEM_PROMPT,
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "True/false generation kw=%r attempt %d/%d failed: %s",
                        keyword, attempt, _MAX_RETRIES, last_error,
                    )
                    if attempt < _MAX_RETRIES:
                        time.sleep(_RETRY_DELAY_SECONDS * attempt)
                    continue

                # Wrap single-LLM response in an array so _parse_response works.
                wrapped = f"[{raw.strip()}]"
                parsed = self._parse_response(wrapped, 1)
                if parsed is not None:
                    break

                last_error = "Invalid JSON response from LLM"
                logger.warning(
                    "True/false generation kw=%r attempt %d/%d: %s",
                    keyword, attempt, _MAX_RETRIES, last_error,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY_SECONDS * attempt)

            if parsed is None:
                raise RuntimeError(
                    f"True/false question generation failed for keyword {keyword!r} "
                    f"after {_MAX_RETRIES} attempts: {last_error}"
                )

            q = parsed[0]
            # Override correct_answer to match the assigned target_response
            # in case the LLM got it wrong.
            q["correct_answer"] = target_response
            questions.append(q)

        logger.info(
            "Generated %d true/false questions | model=%s language=%s",
            len(questions), model, language,
        )
        return questions

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

        valid_types = {"multiple_choice", "true_false", "options_choice", "fill_blank", "short_answer"}
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
