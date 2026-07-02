"""Tests for app.services.question_generator — QuestionGenerator."""
from __future__ import annotations

import json

import pytest

from app.services.question_generator import QuestionGenerator


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Drop-in for OllamaChatClient. Returns canned question JSON."""

    def __init__(self, fail: bool = False, invalid_json: bool = False, empty: bool = False):
        self.fail = fail
        self.invalid_json = invalid_json
        self.empty = empty
        self.call_count = 0
        self.calls: list[tuple[str, str, str | None]] = []

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.call_count += 1
        self.calls.append((model, prompt, system))
        if self.fail:
            from app.models.llm_client import OllamaUnavailable
            raise OllamaUnavailable("Ollama down")
        if self.empty:
            return ""
        if self.invalid_json:
            return "not json at all"
        return json.dumps({
            "type": "true_false",
            "question": "The text mentions the keyword in a specific context.",
            "correct_answer": "true",
        })


@pytest.fixture
def fake_llm() -> _FakeLLM:
    return _FakeLLM()


@pytest.fixture
def fake_config_manager():
    class _FakeCM:
        def load(self) -> dict:
            return {
                "game": {
                    "language": "es",
                    "questions_per_paragraph": 5,
                    "correct_to_master": 3,
                },
                "ia": {
                    "ollama_model": "ollama-model-from-ia",
                    "question_true_false_user_prompt_tpl": (
                        'Generate a true/false question in {language} '
                        'targeting keyword "{keyword}" with answer {target_response}. '
                        'Text: {text}'
                    ),
                },
            }

    return _FakeCM()


@pytest.fixture
def generator(fake_llm, fake_config_manager) -> QuestionGenerator:
    return QuestionGenerator(fake_llm, fake_config_manager)


class TestGenerateSingleTrueFalse:
    def test_returns_single_question(self, generator: QuestionGenerator):
        result = generator.generate_single_true_false(
            chunk_text="France is a country in Europe.",
            keyword="France",
            language="en",
        )
        assert result["type"] == "true_false"
        assert "question" in result
        assert result["correct_answer"] in ("true", "false")

    def test_uses_target_response(self, generator: QuestionGenerator):
        result = generator.generate_single_true_false(
            chunk_text="Sample text.",
            keyword="test",
            language="en",
            target_response="false",
        )
        assert result["correct_answer"] == "false"

    def test_uses_provided_model(self, generator: QuestionGenerator):
        llm = _FakeLLM()
        gen = QuestionGenerator(llm, generator.config_manager)
        gen.generate_single_true_false(
            chunk_text="Sample text.",
            keyword="test",
            language="en",
            model="custom-model",
        )
        assert llm.calls[0][0] == "custom-model"

    def test_raises_on_llm_failure(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(fail=True), generator.config_manager)
        with pytest.raises(RuntimeError, match="True/false question generation failed"):
            gen.generate_single_true_false(
                chunk_text="Sample text.",
                keyword="test",
                language="en",
            )

    def test_retries_on_failure(self, generator: QuestionGenerator):
        llm = _FakeLLM(fail=True)
        gen = QuestionGenerator(llm, generator.config_manager)
        with pytest.raises(RuntimeError):
            gen.generate_single_true_false(
                chunk_text="Sample text.",
                keyword="test",
                language="en",
            )
        assert llm.call_count == 3

    def test_formats_prompt_with_all_placeholders(self, generator: QuestionGenerator):
        llm = _FakeLLM()
        gen = QuestionGenerator(llm, generator.config_manager)
        gen.generate_single_true_false(
            chunk_text="Some text here.",
            keyword="mykeyword",
            language="fr",
            target_response="false",
        )
        prompt = llm.calls[0][1]
        assert "Some text here." in prompt
        assert "mykeyword" in prompt
        assert "false" in prompt
        assert "fr" in prompt


class TestGenerateTrueFalse:
    def test_returns_one_question_per_keyword(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(), generator.config_manager)
        questions = gen.generate_true_false_questions(
            chunk_text="France is a country in Europe.",
            keywords=["France", "Paris", "Europe"],
            language="en",
        )
        assert len(questions) == 3
        for q in questions:
            assert q["type"] == "true_false"
            assert "question" in q
            assert q["correct_answer"] in ("true", "false")

    def test_alternates_target_response(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(), generator.config_manager)
        questions = gen.generate_true_false_questions(
            chunk_text="Sample text.",
            keywords=["kw0", "kw1", "kw2", "kw3"],
            language="en",
        )
        assert questions[0]["correct_answer"] == "true"
        assert questions[1]["correct_answer"] == "false"
        assert questions[2]["correct_answer"] == "true"
        assert questions[3]["correct_answer"] == "false"

    def test_uses_provided_model(self, generator: QuestionGenerator):
        llm = _FakeLLM()
        gen = QuestionGenerator(llm, generator.config_manager)
        gen.generate_true_false_questions(
            chunk_text="Sample text.",
            keywords=["test"],
            language="en",
            model="custom-model",
        )
        assert llm.calls[0][0] == "custom-model"

    def test_raises_on_llm_failure(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(fail=True), generator.config_manager)
        with pytest.raises(RuntimeError, match="True/false question generation failed"):
            gen.generate_true_false_questions(
                chunk_text="Sample text.",
                keywords=["test"],
                language="en",
            )

    def test_retries_on_failure(self, generator: QuestionGenerator):
        llm = _FakeLLM(fail=True)
        gen = QuestionGenerator(llm, generator.config_manager)
        with pytest.raises(RuntimeError):
            gen.generate_true_false_questions(
                chunk_text="Sample text.",
                keywords=["test"],
                language="en",
            )
        assert llm.call_count == 3

    def test_empty_keywords_returns_empty_list(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(), generator.config_manager)
        questions = gen.generate_true_false_questions(
            chunk_text="Sample text.",
            keywords=[],
            language="en",
        )
        assert questions == []

    def test_formats_prompt_with_all_placeholders(self, generator: QuestionGenerator):
        llm = _FakeLLM()
        gen = QuestionGenerator(llm, generator.config_manager)
        gen.generate_true_false_questions(
            chunk_text="Some text here.",
            keywords=["mykeyword"],
            language="fr",
        )
        prompt = llm.calls[0][1]
        assert "Some text here." in prompt
        assert "mykeyword" in prompt
        assert "true" in prompt or "false" in prompt
        assert "fr" in prompt


class TestParseResponse:
    def test_strips_markdown_code_fence(self, generator: QuestionGenerator):
        raw = "```json\n" + json.dumps([
            {"type": "true_false", "question": "Test?", "correct_answer": "true"},
        ]) + "\n```"
        questions = generator._parse_response(raw, 1)
        assert questions is not None
        assert len(questions) == 1

    def test_returns_none_on_invalid_json(self, generator: QuestionGenerator):
        assert generator._parse_response("not json", 1) is None

    def test_returns_none_on_non_list(self, generator: QuestionGenerator):
        assert generator._parse_response('{"key": "val"}', 1) is None

    def test_filters_invalid_question_types(self, generator: QuestionGenerator):
        raw = json.dumps([
            {"type": "invalid_type", "question": "Test?", "correct_answer": "A"},
        ])
        questions = generator._parse_response(raw, 2)
        assert questions is None

    def test_filters_missing_correct_answer(self, generator: QuestionGenerator):
        raw = json.dumps([
            {"type": "true_false", "question": "Test?", "correct_answer": ""},
        ])
        questions = generator._parse_response(raw, 1)
        assert questions is None  # no valid questions
