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

    def __init__(self, fail: bool = False, invalid_json: bool = False, empty: bool = False, mode: str = "mixed"):
        self.fail = fail
        self.invalid_json = invalid_json
        self.empty = empty
        self.mode = mode
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
        if self.mode == "true_false":
            # Return a single true_false object (not wrapped in array)
            return json.dumps({
                "type": "true_false",
                "question": "The text mentions the keyword in a specific context.",
                "correct_answer": "true",
            })
        return json.dumps([
            {
                "type": "multiple_choice",
                "question": "What is the capital of France?",
                "options": ["Paris", "London", "Berlin", "Madrid"],
                "correct_answer": "Paris",
            },
            {
                "type": "options_choice",
                "question": "Paris is the capital of France.",
                "correct_answer": "true",
            },
            {
                "type": "fill_blank",
                "question": "The capital of France is ___.",  # noqa: P103
                "correct_answer": "Paris",
            },
            {
                "type": "short_answer",
                "question": "Capital of France?",
                "correct_answer": "Paris",
            },
        ])


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
                    "model": "qwen3.5:latest",
                },
                "ia": {
                    "ollama_model": "qwen3.5:latest",
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_returns_questions(self, generator: QuestionGenerator):
        questions = generator.generate(
            chunk_text="France is a country in Europe. Its capital is Paris.",
            keywords=["France", "Paris", "Europe"],
            count=4,
            language="en",
        )
        assert len(questions) == 4
        assert questions[0]["type"] == "multiple_choice"
        assert questions[1]["type"] == "options_choice"
        assert questions[2]["type"] == "fill_blank"
        assert questions[3]["type"] == "short_answer"

    def test_all_questions_have_required_fields(self, generator: QuestionGenerator):
        questions = generator.generate(
            chunk_text="Sample text for testing.",
            keywords=["test"],
            count=4,
            language="en",
        )
        for q in questions:
            assert "type" in q
            assert "question" in q
            assert "correct_answer" in q

    def test_multiple_choice_has_options(self, generator: QuestionGenerator):
        questions = generator.generate(
            chunk_text="Sample text.",
            keywords=["test"],
            count=4,
            language="en",
        )
        mc = [q for q in questions if q["type"] == "multiple_choice"]
        if mc:
            assert "options" in mc[0]
            assert len(mc[0]["options"]) >= 2

    def test_uses_provided_model(self, generator: QuestionGenerator, fake_llm: _FakeLLM):
        generator.generate(
            chunk_text="Sample text.",
            keywords=["test"],
            count=2,
            language="en",
            model="custom-model",
        )
        assert fake_llm.calls[0][0] == "custom-model"

    def test_falls_back_to_config_model(self, generator: QuestionGenerator, fake_llm: _FakeLLM):
        generator.generate(
            chunk_text="Sample text.",
            keywords=["test"],
            count=2,
            language="en",
        )
        assert fake_llm.calls[0][0] == "qwen3.5:latest"

    def test_raises_on_llm_failure(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(fail=True), generator.config_manager)
        with pytest.raises(RuntimeError, match="Question generation failed"):
            gen.generate(
                chunk_text="Sample text.",
                keywords=["test"],
                count=2,
                language="en",
            )

    def test_raises_on_invalid_json(self, generator: QuestionGenerator):
        gen = QuestionGenerator(_FakeLLM(invalid_json=True), generator.config_manager)
        with pytest.raises(RuntimeError, match="Question generation failed"):
            gen.generate(
                chunk_text="Sample text.",
                keywords=["test"],
                count=2,
                language="en",
            )

    def test_retries_on_failure(self, generator: QuestionGenerator):
        fake = _FakeLLM(fail=True)
        gen = QuestionGenerator(fake, generator.config_manager)
        with pytest.raises(RuntimeError):
            gen.generate(
                chunk_text="Sample text.",
                keywords=["test"],
                count=2,
                language="en",
            )
        assert fake.call_count == 3  # max retries


class TestGenerateTrueFalse:
    def test_returns_one_question_per_keyword(self, generator: QuestionGenerator):
        llm = _FakeLLM(mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
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
        llm = _FakeLLM(mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
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
        llm = _FakeLLM(mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
        gen.generate_true_false_questions(
            chunk_text="Sample text.",
            keywords=["test"],
            language="en",
            model="custom-model",
        )
        assert llm.calls[0][0] == "custom-model"

    def test_raises_on_llm_failure(self, generator: QuestionGenerator):
        llm = _FakeLLM(fail=True, mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
        with pytest.raises(RuntimeError, match="True/false question generation failed"):
            gen.generate_true_false_questions(
                chunk_text="Sample text.",
                keywords=["test"],
                language="en",
            )

    def test_retries_on_failure(self, generator: QuestionGenerator):
        llm = _FakeLLM(fail=True, mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
        with pytest.raises(RuntimeError):
            gen.generate_true_false_questions(
                chunk_text="Sample text.",
                keywords=["test"],
                language="en",
            )
        assert llm.call_count == 3

    def test_empty_keywords_returns_empty_list(self, generator: QuestionGenerator):
        llm = _FakeLLM(mode="true_false")
        gen = QuestionGenerator(llm, generator.config_manager)
        questions = gen.generate_true_false_questions(
            chunk_text="Sample text.",
            keywords=[],
            language="en",
        )
        assert questions == []

    def test_formats_prompt_with_all_placeholders(self, generator: QuestionGenerator):
        llm = _FakeLLM(mode="true_false")
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
            {"type": "options_choice", "question": "Test?", "correct_answer": "true"},
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
            {"type": "options_choice", "question": "Valid?", "correct_answer": "true"},
        ])
        questions = generator._parse_response(raw, 2)
        assert questions is not None
        assert len(questions) == 1

    def test_filters_missing_correct_answer(self, generator: QuestionGenerator):
        raw = json.dumps([
            {"type": "options_choice", "question": "Test?", "correct_answer": ""},
        ])
        questions = generator._parse_response(raw, 1)
        assert questions is None  # no valid questions


class TestGenerateIntegration:
    def test_with_already_mastered_theme(self, generator: QuestionGenerator):
        """Verify end-to-end with a realistic chunk."""
        text = (
            "Platón fundó la Academia en Atenas alrededor del año 387 a. C. "
            "Esta institución es considerada la primera universidad de la historia "
            "occidental. Allí se enseñaban matemáticas, astronomía, filosofía y política."
        )
        keywords = ["Platón", "Academia", "Atenas", "filosofía", "universidad"]
        questions = generator.generate(
            chunk_text=text,
            keywords=keywords,
            count=5,
            language="es",
        )
        assert 1 <= len(questions) <= 5
        types_found = {q["type"] for q in questions}
        valid = {"multiple_choice", "options_choice", "fill_blank", "short_answer"}
        assert types_found.issubset(valid)
