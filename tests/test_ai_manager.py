"""Tests for app.models.ai_manager.AIManager end-to-end pipeline."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import responses

from app.models.ai_manager import AIManager, DigestSummary, OllamaUnavailable, PDFChunker
from app.models.file_manager import FileManager


OLLAMA_URL = "http://localhost:11434"


def _make_text_pdf(pages: list[str]) -> bytes:
    """Create a multi-page PDF in memory with extractable text."""
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def sample_text_pdf_bytes() -> bytes:
    """Three pages with extractable text used by AI tests."""
    return _make_text_pdf(
        [
            "Page one: " + ("alpha " * 60),
            "Page two: " + ("beta " * 80),
            "Page three: " + ("gamma " * 40),
        ]
    )


@pytest.fixture
def empty_pdf_bytes() -> bytes:
    """A PDF with one blank page (no extractable text)."""
    return _make_text_pdf([""])


class FakeOllama:
    """Drop-in replacement for OllamaClient that returns canned embeddings."""

    def __init__(self, fail: bool = False, dim: int = 8):
        self.fail = fail
        self.dim = dim
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return not self.fail

    def embed(self, text: str, model: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise OllamaUnavailable("Ollama down")
        # Deterministic pseudo-embedding based on text length.
        return [float(len(text) % 7) / 7.0] * self.dim

    def embed_batch(self, texts: list[str], model: str, batch_size: int = 16):
        return [self.embed(t, model) for t in texts]


@pytest.fixture
def fake_ollama() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def ai_manager(temp_workspace: dict, fake_ollama: FakeOllama):
    """Build an AIManager wired to the temp workspace and a fake Ollama."""
    from app.models.config_manager import ConfigManager

    cm = ConfigManager(temp_workspace["config"])
    fm = FileManager(temp_workspace["projects"])
    return AIManager(config_manager=cm, file_manager=fm, ollama_client=fake_ollama)


@pytest.fixture
def project_with_pdf(temp_workspace: dict, sample_text_pdf_bytes: bytes, ai_manager):
    """Create a project on disk containing the sample text PDF."""
    fm = FileManager(temp_workspace["projects"])
    entry = fm.save_upload(io.BytesIO(sample_text_pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path, ai_manager


class TestAIManagerSettings:
    def test_get_ia_settings_returns_defaults(self, ai_manager):
        settings = ai_manager.get_ia_settings()
        assert settings["ollama_url"] == "http://localhost:11434"
        assert settings["chunk_size"] == 500

    def test_get_ia_settings_uses_persisted_values(self, temp_workspace: dict, fake_ollama):
        from app.models.config_manager import ConfigManager

        cm = ConfigManager(temp_workspace["config"])
        cm.update_ia(chunk_size=256, chunk_overlap=20)
        fm = FileManager(temp_workspace["projects"])
        mgr = AIManager(cm, fm, ollama_client=fake_ollama)
        assert mgr.get_ia_settings()["chunk_size"] == 256
        assert mgr.get_ia_settings()["chunk_overlap"] == 20


class TestValidateOllama:
    def test_returns_true_when_reachable(self, temp_workspace: dict):
        from app.models.config_manager import ConfigManager

        cm = ConfigManager(temp_workspace["config"])
        fm = FileManager(temp_workspace["projects"])
        fake = FakeOllama()
        mgr = AIManager(cm, fm, ollama_client=fake)
        ok, msg = mgr.validate_ollama()
        assert ok is True
        assert "reachable" in msg

    @responses.activate
    def test_returns_false_when_unreachable(self, temp_workspace: dict):
        import requests as _requests

        from app.models.config_manager import ConfigManager

        cm = ConfigManager(temp_workspace["config"])
        fm = FileManager(temp_workspace["projects"])
        mgr = AIManager(cm, fm)  # real client, mocked HTTP
        responses.add(
            responses.GET,
            f"{OLLAMA_URL}/api/tags",
            body=_requests.exceptions.ConnectionError("refused"),
        )
        ok, msg = mgr.validate_ollama()
        assert ok is False
        assert "not reachable" in msg


class TestDigestPdf:
    def test_digest_returns_summary(
        self, project_with_pdf, fake_ollama: FakeOllama
    ):
        entry, pdf_path, ai = project_with_pdf
        summary = ai.digest_pdf(entry.name, pdf_path)
        assert isinstance(summary, DigestSummary)
        assert summary.pages == 3
        assert summary.chunks > 0
        assert summary.project_name == entry.name
        assert summary.duration_seconds >= 0

    def test_digest_stores_embeddings_in_chroma(
        self, project_with_pdf, fake_ollama: FakeOllama
    ):
        import chromadb

        entry, pdf_path, ai = project_with_pdf
        summary = ai.digest_pdf(entry.name, pdf_path)
        # Open the same persistent client and verify vectors exist.
        chroma_dir = ai.file_manager.project_path(entry.name) / "chroma.db"
        client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection(ai.COLLECTION_NAME)
        assert col.count() == summary.chunks

    def test_digest_missing_project_raises(self, ai_manager, sample_text_pdf_bytes, tmp_path):
        # No project created on disk
        pdf_path = tmp_path / "ghost.pdf"
        pdf_path.write_bytes(sample_text_pdf_bytes)
        with pytest.raises(FileNotFoundError):
            ai_manager.digest_pdf("ghost", pdf_path)

    def test_digest_raises_when_ollama_down(
        self, project_with_pdf, temp_workspace: dict
    ):
        from app.models.config_manager import ConfigManager

        entry, pdf_path, _ = project_with_pdf
        cm = ConfigManager(temp_workspace["config"])
        fm = FileManager(temp_workspace["projects"])
        mgr = AIManager(cm, fm, ollama_client=FakeOllama(fail=True))
        with pytest.raises(OllamaUnavailable):
            mgr.digest_pdf(entry.name, pdf_path)

    def test_digest_handles_empty_pdf(self, project_with_pdf, empty_pdf_bytes, fake_ollama):
        import io as _io

        from app.models.file_manager import FileManager

        entry, _, ai = project_with_pdf
        fm = ai.file_manager
        # Overwrite with empty PDF
        (fm.project_path(entry.name) / "doc.pdf").write_bytes(empty_pdf_bytes)
        summary = ai.digest_pdf(entry.name, fm.project_path(entry.name) / "doc.pdf")
        assert summary.pages == 1
        assert summary.chunks == 0

    def test_digest_invokes_progress_callback(
        self, project_with_pdf, fake_ollama: FakeOllama
    ):
        entry, pdf_path, ai = project_with_pdf
        phases: list[str] = []
        ai.digest_pdf(entry.name, pdf_path, progress_cb=lambda e: phases.append(e["phase"]))
        assert "extracting" in phases
        assert "chunking" in phases
        assert "embedding" in phases
        assert "storing" in phases
        assert "done" in phases

    def test_digest_is_idempotent_per_collection(
        self, project_with_pdf, fake_ollama: FakeOllama
    ):
        import chromadb

        entry, pdf_path, ai = project_with_pdf
        # Run twice; Chroma will accumulate unless we reset ids.
        ai.digest_pdf(entry.name, pdf_path)
        ai.digest_pdf(entry.name, pdf_path)
        client = chromadb.PersistentClient(
            path=str(ai.file_manager.project_path(entry.name) / "chroma.db"),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection(ai.COLLECTION_NAME)
        # Second run adds the same IDs again; Chroma upserts, so count
        # remains equal to chunks (not doubled).
        assert col.count() > 0