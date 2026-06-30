"""Tests for app.services.digest_engine — LazyAIManager with semantic segmentation."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.services.digest_engine import DigestSummary, LazyAIManager


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Drop-in for OllamaChatClient. Counts calls and can be told to fail.

    Responds differently based on the ``system`` prompt so the same instance
    can serve both keyword-extraction and question-generation calls.
    """

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0
        self.calls: list[tuple[str, str, str | None]] = []

    def is_available(self) -> bool:
        return not self.fail

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.call_count += 1
        self.calls.append((model, prompt, system))
        if self.fail:
            from app.models.llm_client import OllamaUnavailable
            raise OllamaUnavailable("Ollama down")

        # Question generation (called by QuestionGenerator)
        if "question" in prompt:
            if "Generate a true/false question" in prompt or "true/false" in prompt:
                return json.dumps({
                    "type": "true_false",
                    "question": "The quick brown fox jumps over the lazy dog.",
                    "correct_answer": "true",
                })
            return json.dumps([
                {"type": "multiple_choice", "question": "LLM MC?", "options": ["A", "B", "C"], "correct_answer": "A"},
                {"type": "options_choice", "question": "LLM OC?", "correct_answer": "B"},
                {"type": "fill_blank", "question": "LLM fill ___", "correct_answer": "LLM"},
                {"type": "short_answer", "question": "LLM SA?", "correct_answer": "answer"},
            ])

        # Default — keyword extraction (called by SemanticSegmenter)
        words = prompt.split()
        keywords = [w.strip('",.!?;:') for w in words[1:4] if w.strip('",.!?;:')]
        return json.dumps({
            "text_keywords": keywords,
            "title": "Generated Title",
            "language": "en",
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pdf_with_text(text: str) -> bytes:
    """Build a single-page PDF with the given text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rect = fitz.Rect(50, 50, 560, 750)
    page.insert_textbox(rect, text, fontsize=8)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> _FakeLLM:
    return _FakeLLM()


@pytest.fixture
def segmenter_and_lazy(tmp_path: Path, fake_llm: _FakeLLM):
    """Build a SemanticSegmenter + LazyAIManager wired to a fake LLM.

    Uses ``tmp_path`` (not ``temp_workspace``) to avoid the autouse
    ``_shutdown_job_runner`` fixture creating a Flask app whose supervisor
    thread would scan the same projects directory and cause races.
    """
    import yaml

    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager
    from app.models.semantic_segmenter import SemanticSegmenter

    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    projects_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))

    cm = ConfigManager(config_path)
    fm = FileManager(projects_dir)
    seg = SemanticSegmenter(config_manager=cm, file_manager=fm, llm_client=fake_llm, request_timeout=5.0)
    lazy = LazyAIManager(segmenter=seg, file_manager=fm)
    return {"cm": cm, "fm": fm, "seg": seg, "lazy": lazy, "fake": fake_llm}


@pytest.fixture
def project_with_pdf(segmenter_and_lazy: dict):
    """Create a project with a PDF that has extractable text."""
    fm = segmenter_and_lazy["fm"]
    lazy = segmenter_and_lazy["lazy"]
    text = "hello " * 60 + "world " * 60 + "test " * 60
    pdf_bytes = _write_pdf_with_text(text)
    entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path, segmenter_and_lazy


@pytest.fixture
def segmenter_and_lazy_with_game(tmp_path: Path, fake_llm: _FakeLLM):
    """Like segmenter_and_lazy but also wires a GameManager."""
    import yaml

    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager
    from app.models.game_state import GameManager
    from app.models.semantic_segmenter import SemanticSegmenter

    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    projects_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))

    cm = ConfigManager(config_path)
    fm = FileManager(projects_dir)
    gm = GameManager(fm, cm)
    seg = SemanticSegmenter(config_manager=cm, file_manager=fm, llm_client=fake_llm, request_timeout=5.0)
    lazy = LazyAIManager(segmenter=seg, file_manager=fm, game_manager=gm)
    return {"cm": cm, "fm": fm, "gm": gm, "seg": seg, "lazy": lazy, "fake": fake_llm}


@pytest.fixture
def segmenter_and_lazy_with_full_game(tmp_path: Path, fake_llm: _FakeLLM):
    """Like segmenter_and_lazy_with_game but also wires a QuestionGenerator for LLM questions."""
    import yaml

    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager
    from app.models.game_state import GameManager
    from app.models.semantic_segmenter import SemanticSegmenter
    from app.services.question_generator import QuestionGenerator

    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    projects_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))

    cm = ConfigManager(config_path)
    fm = FileManager(projects_dir)
    gm = GameManager(fm, cm)
    seg = SemanticSegmenter(config_manager=cm, file_manager=fm, llm_client=fake_llm, request_timeout=5.0)
    qg = QuestionGenerator(llm_client=fake_llm, config_manager=cm)
    lazy = LazyAIManager(
        segmenter=seg,
        file_manager=fm,
        game_manager=gm,
        question_generator=qg,
        config_manager=cm,
    )
    return {"cm": cm, "fm": fm, "gm": gm, "seg": seg, "lazy": lazy, "qg": qg, "fake": fake_llm}


@pytest.fixture
def project_with_pdf_and_full_game(segmenter_and_lazy_with_full_game: dict):
    """Create a project with PDF + GameManager + QuestionGenerator wired."""
    fm = segmenter_and_lazy_with_full_game["fm"]
    lazy = segmenter_and_lazy_with_full_game["lazy"]
    text = "hello " * 60 + "world " * 60 + "test " * 60
    pdf_bytes = _write_pdf_with_text(text)
    entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path, segmenter_and_lazy_with_full_game


@pytest.fixture
def project_with_pdf_and_game(segmenter_and_lazy_with_game: dict):
    """Create a project with PDF + GameManager wired."""
    fm = segmenter_and_lazy_with_game["fm"]
    lazy = segmenter_and_lazy_with_game["lazy"]
    text = "hello " * 60 + "world " * 60 + "test " * 60
    pdf_bytes = _write_pdf_with_text(text)
    entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path, segmenter_and_lazy_with_game


# ---------------------------------------------------------------------------
# TestEnsureCache
# ---------------------------------------------------------------------------


class TestEnsureCache:
    def test_extracts_text_from_pdf(self, segmenter_and_lazy: dict):
        lazy = segmenter_and_lazy["lazy"]
        fm = segmenter_and_lazy["fm"]
        text = "alpha " * 40 + "beta " * 40
        pdf_bytes = _write_pdf_with_text(text)
        entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "cachedemo")
        pdf_path = fm.project_path(entry.name) / "doc.pdf"
        cached = lazy.ensure_cache(entry.name, pdf_path)
        assert "alpha" in cached
        assert "beta" in cached

    def test_idempotent(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, _ = project_with_pdf
        lazy = _get_lazy(segmenter_and_lazy)
        first = lazy.ensure_cache(entry.name, pdf_path)
        second = lazy.ensure_cache(entry.name, pdf_path)
        assert first == second


def _get_lazy(d):
    return d["lazy"]


# ---------------------------------------------------------------------------
# TestGenerateTitle
# ---------------------------------------------------------------------------


class TestGenerateTitle:
    def test_generates_title_and_language(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        lazy.ensure_cache(entry.name, pdf_path)
        title, language = lazy.generate_title(entry.name)
        assert title == "Generated Title"
        assert language == "en"
        persisted = lazy._load_state(entry.name)
        assert persisted.get("title") == title
        assert persisted.get("language") == language

    def test_skips_when_title_and_language_exist(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        fake = components["fake"]
        lazy.ensure_cache(entry.name, pdf_path)
        lazy._persist_state(entry.name, title="existing-title", language="fr")
        fake.call_count = 0
        title, language = lazy.generate_title(entry.name)
        assert title == "existing-title"
        assert language == "fr"
        assert fake.call_count == 0

    def test_returns_empty_when_no_text(self, segmenter_and_lazy: dict):
        lazy = segmenter_and_lazy["lazy"]
        fm = segmenter_and_lazy["fm"]
        # Upload a blank PDF (no extractable text)
        pdf_bytes = _write_pdf_with_text("")
        entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "emptyproj")
        title, language = lazy.generate_title(entry.name)
        assert title == ""
        assert language == ""

    def test_returns_empty_on_llm_failure(self, segmenter_and_lazy: dict):
        from tests.test_digest_engine import _FakeLLM
        lazy = segmenter_and_lazy["lazy"]
        fm = segmenter_and_lazy["fm"]
        failing_llm = _FakeLLM(fail=True)
        seg = segmenter_and_lazy["seg"]
        seg.llm = failing_llm
        text = "hello world " * 50
        pdf_bytes = _write_pdf_with_text(text)
        entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "failtitle")
        pdf_path = fm.project_path(entry.name) / "doc.pdf"
        lazy.ensure_cache(entry.name, pdf_path)
        title, language = lazy.generate_title(entry.name)
        assert title == ""
        assert language == ""


# ---------------------------------------------------------------------------
# TestProcessOneChunk
# ---------------------------------------------------------------------------


class TestProcessOneChunk:
    def test_processes_first_chunk(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        info = lazy.process_one_chunk(entry.name)
        assert info is not None
        assert info["chunk"] == 1
        assert info["state"] in ("processing", "complete")

    def test_persists_chunks_in_digest_json(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        digest_path = components["fm"].project_path(entry.name) / "digest.json"
        assert digest_path.exists()
        data = json.loads(digest_path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
        assert len(chunks) >= 1
        assert "original_text" in chunks[0]
        assert "page_number" in chunks[0]
        # First chunk should have text_keywords set (list or null)
        assert chunks[0]["text_keywords"] is not None

    def test_chunks_initially_have_null_keywords(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        # Process one chunk to trigger init
        lazy.process_one_chunk(entry.name)
        digest_path = components["fm"].project_path(entry.name) / "digest.json"
        data = json.loads(digest_path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
        assert chunks[0]["text_keywords"] is not None  # first was processed
        # Remaining chunks may exist and are null
        if len(chunks) > 1:
            for c in chunks[1:]:
                assert c["text_keywords"] is None

    def test_updates_digest_state(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        state = lazy.project_status(entry.name)
        assert state["chunks_processed"] >= 1
        assert state["total_keywords"] >= 1

    def test_returns_none_when_complete(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        while True:
            info = lazy.process_one_chunk(entry.name)
            if info is None:
                break
        state = lazy.project_status(entry.name)
        assert state["state"] == "complete"

    def test_resumes_from_partial_state(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        lazy.process_one_chunk(entry.name)
        info = lazy.process_one_chunk(entry.name)
        assert info is not None
        assert info["chunk"] >= 3


# ---------------------------------------------------------------------------
# TestGenerateChunkQuestions
# ---------------------------------------------------------------------------


class TestGenerateChunkQuestions:
    def test_creates_game_state_with_options_choice_question(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        assert len(state.paragraphs) > 0
        assert len(state.paragraphs[0].questions) == 1

        q = state.paragraphs[0].questions[0]
        assert q.question_type == "options_choice"
        assert q.title == "Reading Check"
        assert q.correct_answer == ["Ok, i read it"]
        assert q.options == ["Ok, i read it", "not yet"]
        assert q.correct_to_master == 1
        assert len(q.question_text) > 0

    def test_question_has_auto_incrementing_id(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        # Process two chunks
        lazy.process_one_chunk(entry.name)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        assert len(state.paragraphs[0].questions) == 1
        assert len(state.paragraphs[1].questions) == 1
        assert state.paragraphs[0].questions[0].id == 1
        assert state.paragraphs[1].questions[0].id == 2

    def test_questions_store_in_correct_paragraphs(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None

        # Paragraph 0 (chunk 0) has a question
        assert len(state.paragraphs[0].questions) == 1
        # Paragraph 1 (chunk 1, not processed) has no questions
        if len(state.paragraphs) > 1:
            assert len(state.paragraphs[1].questions) == 0

    def test_paragraph_0_is_unlocked(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        assert state.paragraphs[0].unlocked is True

    def test_noop_when_no_game_manager(self, project_with_pdf):
        """Should not crash when game_manager is None."""
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        info = lazy.process_one_chunk(entry.name)
        assert info is not None
        # No game_state.json should exist
        import json
        digest_path = components["fm"].project_path(entry.name) / "digest.json"
        data = json.loads(digest_path.read_text(encoding="utf-8"))
        assert "game_state" not in data


# ---------------------------------------------------------------------------
# TestFillTheGap
# ---------------------------------------------------------------------------


class TestFillTheGap:
    """Fill-the-gap questions generated alongside the Reading Check."""

    def test_one_question_per_keyword(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        chunk_text = "The quick brown fox jumps over the lazy dog near the river."
        chunks = [
            {
                "original_text": chunk_text,
                "page_number": 1,
                "text_keywords": ["fox", "dog", "lazy", "jumps", "quick"],
            }
        ]
        lazy._save_chunks(entry.name, chunks)
        lazy._generate_chunk_questions(entry.name, chunk_text, 0)

        state = gm.load_state(entry.name)
        assert state is not None

        questions = state.paragraphs[0].questions
        # 1 Reading Check + 5 fill_gap = 6
        assert len(questions) == 6

        assert questions[0].title == "Reading Check"
        assert questions[0].question_type == "options_choice"

        seen = set()
        for q in questions[1:]:
            assert q.title == "Fill the Gap"
            assert q.question_type == "fill_gap"
            assert q.correct_to_master == 0
            kw = q.correct_answer[0].lower()
            assert kw not in seen  # each keyword appears once
            seen.add(kw)
            assert kw in chunk_text.lower()
            assert "________" in q.question_text
            assert kw in [o.lower() for o in q.options]
            # All options are different
            assert len(set(o.lower() for o in q.options)) == len(q.options)

    def test_replaces_all_occurrences_case_insensitive(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        chunk_text = "The Fox saw another fox. The quick brown fox jumps over the lazy dog."
        chunks = [
            {
                "original_text": chunk_text,
                "page_number": 1,
                "text_keywords": ["fox", "dog"],
            }
        ]
        lazy._save_chunks(entry.name, chunks)
        lazy._generate_chunk_questions(entry.name, chunk_text, 0)

        state = gm.load_state(entry.name)
        questions = state.paragraphs[0].questions

        fox_qs = [
            q for q in questions
            if q.title == "Fill the Gap" and q.correct_answer[0].lower() == "fox"
        ]
        assert len(fox_qs) == 1
        assert fox_qs[0].question_text == "The ________ saw another ________."

    def test_no_fill_gap_when_no_keywords(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        chunk_text = "Some text without any extracted keywords."
        chunks = [{"original_text": chunk_text, "page_number": 1, "text_keywords": None}]
        lazy._save_chunks(entry.name, chunks)
        lazy._generate_chunk_questions(entry.name, chunk_text, 0)

        state = gm.load_state(entry.name)
        assert len(state.paragraphs[0].questions) == 1
        assert state.paragraphs[0].questions[0].title == "Reading Check"

    def test_skip_keyword_not_in_sentence(self, project_with_pdf_and_game):
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        chunk_text = "The quick brown fox jumps."
        chunks = [
            {
                "original_text": chunk_text,
                "page_number": 1,
                "text_keywords": ["fox", "nonexistent"],
            }
        ]
        lazy._save_chunks(entry.name, chunks)
        lazy._generate_chunk_questions(entry.name, chunk_text, 0)

        state = gm.load_state(entry.name)
        questions = state.paragraphs[0].questions
        # 1 Reading Check + 1 fill_gap (fox only, nonexistent skipped)
        assert len(questions) == 2
        assert questions[1].correct_answer[0] == "fox"


# ---------------------------------------------------------------------------
# TestEnsureQuestionsGenerated
# ---------------------------------------------------------------------------


class TestEnsureQuestionsGenerated:
    def test_backfills_missing_questions(self, project_with_pdf_and_game):
        """Digest completed before gen feature: ensure_questions_generated fills them."""
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        # Run full digest (no game_manager was wired during chunk processing)
        lazy.game_manager = None
        lazy.run_to_completion(entry.name)
        assert gm.load_state(entry.name) is None

        # Re-attach game_manager and backfill
        lazy.game_manager = gm
        count = lazy.ensure_questions_generated(entry.name)
        assert count > 0

        state = gm.load_state(entry.name)
        assert state is not None
        total_qs = sum(len(p.questions) for p in state.paragraphs)
        assert total_qs == count

    def test_skips_already_generated(self, project_with_pdf_and_game):
        """Calling twice should not create duplicates."""
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        # Process one chunk normally
        lazy.game_manager = gm
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        first_count = sum(len(p.questions) for p in state.paragraphs)

        # Second call should not add duplicates
        count = lazy.ensure_questions_generated(entry.name)
        assert count == 0

        state2 = gm.load_state(entry.name)
        second_count = sum(len(p.questions) for p in state2.paragraphs)
        assert second_count == first_count

    def test_noop_for_complete_state(self, project_with_pdf_and_game):
        """When all chunks have questions, returns 0."""
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        # Let digest generate questions naturally
        lazy.game_manager = gm
        lazy.run_to_completion(entry.name)

        count = lazy.ensure_questions_generated(entry.name)
        assert count == 0

    def test_noop_when_no_game_manager(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        count = lazy.ensure_questions_generated(entry.name)
        assert count == 0


# ---------------------------------------------------------------------------
# TestRunToCompletion
# ---------------------------------------------------------------------------


class TestRunToCompletion:
    def test_runs_all_chunks(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        summary = lazy.run_to_completion(entry.name)
        assert summary.state == "complete"
        assert summary.chunks > 0
        assert summary.keywords > 0

    def test_progress_callback_invoked(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        events = []
        lazy.run_to_completion(entry.name, on_progress=lambda e: events.append(e))
        chunk_events = [e for e in events if e.get("phase") == "chunk_done"]
        assert len(chunk_events) >= 1
        assert any(e.get("phase") == "done" for e in events)


# ---------------------------------------------------------------------------
# TestLLMQuestionGeneration — Phase 2 of _generate_chunk_questions
# ---------------------------------------------------------------------------


class TestLLMQuestionGeneration:
    """LLM-generated questions (multiple_choice, fill_blank, short_answer,
    true_false) are appended during Phase 2 of _generate_chunk_questions."""

    def test_appends_llm_questions_after_programmatic(self, project_with_pdf_and_full_game):
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None

        questions = state.paragraphs[0].questions
        # Phase 1: 1 Reading Check + optional fill_gap (depends on keywords matching)
        # Phase 2: 4 LLM (MC, OC, fill_blank, short_answer) + N true_false
        assert len(questions) > 2  # at least programmatic + some LLM
        types = {q.question_type for q in questions}
        assert "options_choice" in types     # Reading Check
        assert "multiple_choice" in types     # LLM-generated
        assert "true_false" in types          # LLM-generated

    def test_llm_questions_have_valid_types(self, project_with_pdf_and_full_game):
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        questions = state.paragraphs[0].questions
        valid = {"options_choice", "fill_gap", "multiple_choice",
                 "options_choice", "fill_blank", "short_answer", "true_false"}
        for q in questions:
            assert q.question_type in valid, f"Unknown type: {q.question_type}"
            assert q.question_text, f"Empty question for {q.question_type}"
            assert q.correct_answer, f"Empty correct_answer for {q.question_type}"

    def test_llm_questions_are_appended_not_replaced(self, project_with_pdf_and_full_game):
        """Phase 1 programmatic questions survive Phase 2."""
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        questions = state.paragraphs[0].questions
        # Reading Check always present from Phase 1
        reading_checks = [q for q in questions if q.title == "Reading Check"]
        assert len(reading_checks) == 1
        # LLM questions are appended, not replacing Phase 1
        llm_types = {"multiple_choice", "options_choice", "fill_blank", "short_answer", "true_false"}
        llm_qs = [q for q in questions if q.question_type in llm_types]
        assert len(llm_qs) >= 2

    def test_programmatic_questions_available_during_llm_gen(self, project_with_pdf_and_full_game):
        """Phase 1 is saved before Phase 2 starts (simulate by checking state
        between saves — here we just verify no crash when questions are
        answered between phases)."""
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        # All questions should be playable
        for q in state.paragraphs[0].questions:
            assert q.question_text

    def test_no_llm_questions_when_no_question_generator(self, project_with_pdf_and_game):
        """Without question_generator, only programmatic questions are created."""
        entry, pdf_path, components = project_with_pdf_and_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        questions = state.paragraphs[0].questions
        types = {q.question_type for q in questions}
        assert "multiple_choice" not in types
        assert "true_false" not in types
        assert "fill_blank" not in types

    def test_true_false_questions_per_keyword(self, project_with_pdf_and_full_game):
        """Each keyword generates one true_false question."""
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        tf = [q for q in state.paragraphs[0].questions if q.question_type == "true_false"]
        # The _FakeLLM generates keywords from the prompt words,
        # so at least one true_false should exist for chunks with keywords
        assert len(tf) >= 1
        for q in tf:
            assert q.correct_answer in (["true"], ["false"])

    def test_llm_failure_is_non_fatal(self, project_with_pdf_and_full_game):
        """If Phase 2 LLM generation fails, Phase 1 questions still persist."""
        from unittest.mock import patch

        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        with patch.object(lazy.question_generator, "generate", side_effect=RuntimeError("LLM down")):
            lazy.process_one_chunk(entry.name)

        state = gm.load_state(entry.name)
        assert state is not None
        questions = state.paragraphs[0].questions
        # Phase 1 questions should still be there
        assert any(q.title == "Reading Check" for q in questions)


# ---------------------------------------------------------------------------
# TestBackfillQuestionGeneration — ensure_questions_generated from background
# ---------------------------------------------------------------------------


class TestBackfillQuestionGeneration:
    """When ``ensure_questions_generated`` runs (from a background job at
    startup or during digest), it must generate both programmatic questions
    (Phase 1) and LLM-generated questions (Phase 2) for chunks that have
    ``text_keywords`` but no questions yet."""

    def test_backfill_generates_programmatic_and_llm(self, project_with_pdf_and_full_game):
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        # Run digest without game_manager so no questions are created.
        lazy.game_manager = None
        lazy.run_to_completion(entry.name)
        assert gm.load_state(entry.name) is None

        # Re-attach game_manager and backfill.
        lazy.game_manager = gm
        count = lazy.ensure_questions_generated(entry.name)
        assert count > 0

        state = gm.load_state(entry.name)
        assert state is not None
        total_qs = sum(len(p.questions) for p in state.paragraphs)
        assert total_qs > count  # each paragraph has multiple questions (procedural + LLM)

        # Verify both programmatic and LLM types appear.
        all_types: set[str] = set()
        for p in state.paragraphs:
            for q in p.questions:
                all_types.add(q.question_type)
        assert "options_choice" in all_types  # Reading Check (Phase 1)
        assert "multiple_choice" in all_types  # LLM-generated (Phase 2)
        assert "true_false" in all_types       # LLM-generated (Phase 2)

    def test_backfill_flag_tracking(self, project_with_pdf_and_full_game):
        """is_question_generation_active is True while the method runs."""
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        gm = components["gm"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)

        lazy.game_manager = None
        lazy.run_to_completion(entry.name)

        lazy.game_manager = gm
        assert not lazy.is_question_generation_active(entry.name)
        lazy.ensure_questions_generated(entry.name)
        assert not lazy.is_question_generation_active(entry.name)

    def test_backfill_noop_when_no_game_manager(self, project_with_pdf_and_full_game):
        """Should not crash when game_manager is None."""
        entry, pdf_path, components = project_with_pdf_and_full_game
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.game_manager = None
        lazy.run_to_completion(entry.name)
        count = lazy.ensure_questions_generated(entry.name)
        assert count == 0


# ---------------------------------------------------------------------------
# TestCancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_event_stops_loop(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        processed = 0
        for _ in range(10):
            if lazy.is_cancelled(entry.name):
                break
            if lazy.process_one_chunk(entry.name) is None:
                break
            processed += 1
            if processed == 1:
                lazy.cancel(entry.name)
        assert processed == 1


# ---------------------------------------------------------------------------
# TestProjectStatus
# ---------------------------------------------------------------------------


class TestProjectStatus:
    def test_new_project_is_queued(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, _, _ = project_with_pdf
        lazy = segmenter_and_lazy["lazy"]
        state = lazy.project_status(entry.name)
        assert state["state"] == "queued"

    def test_missing_project(self, segmenter_and_lazy: dict):
        lazy = segmenter_and_lazy["lazy"]
        state = lazy.project_status("ghost")
        assert state["state"] == "error"
        assert state["error"]


# ---------------------------------------------------------------------------
# TestDigestSummary
# ---------------------------------------------------------------------------


class TestDigestSummary:
    def test_to_dict(self):
        s = DigestSummary(
            project_name="p",
            state="complete",
            chunks=5,
            keywords=12,
            duration_seconds=3.14,
            total_words=1000,
        )
        d = s.to_dict()
        assert d["project_name"] == "p"
        assert d["chunks"] == 5
        assert d["keywords"] == 12
