"""AI manager for autotester: PDF extraction, chunking, embeddings, vector store.

Layered so each concern can be tested independently:

    PDFChunker      -> pure function: text -> chunks
    OllamaClient    -> HTTP wrapper: /api/tags, /api/embeddings
    AIManager       -> orchestration: extract -> chunk -> embed -> chroma
    DigestSummary   -> result type returned to controllers
"""
from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A single text chunk derived from a PDF page."""

    text: str
    index: int
    page: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DigestSummary:
    """Result of processing one PDF into the vector store."""

    pages: int
    chunks: int
    duration_seconds: float
    project_name: str
    collection_name: str = "documents"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class PDFChunker:
    """Split per-page text into overlapping word-based chunks.

    Pure function. Concatenates pages into one stream, splits on word
    boundaries, and tracks the originating page for each chunk.
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and < chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, pages: list[str]) -> list[Chunk]:
        """Return a list of Chunk objects covering the concatenated pages."""
        if not pages:
            return []

        # Build a flat list of (word, page_number) preserving order.
        tokens: list[tuple[str, int]] = []
        for page_idx, raw in enumerate(pages, start=1):
            for word in raw.split():
                tokens.append((word, page_idx))

        if not tokens:
            return []

        step = self.chunk_size - self.chunk_overlap
        chunks: list[Chunk] = []
        idx = 0
        start = 0
        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            window = tokens[start:end]
            text = " ".join(w for w, _ in window)
            page = window[0][1]
            chunks.append(Chunk(text=text, index=idx, page=page))
            idx += 1
            if end == len(tokens):
                break
            start += step

        return chunks


# ---------------------------------------------------------------------------
# Ollama HTTP client
# ---------------------------------------------------------------------------


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama is not reachable."""


class OllamaClient:
    """Minimal HTTP client for the two endpoints we use.

    Uses the ``requests`` library. Designed so tests can patch ``requests``
    via the ``responses`` library or a fake ``Session``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session  # may be None; we use module-level requests

    def _do(self, method: str, path: str, **kwargs: Any) -> Any:
        import requests as _requests

        url = f"{self.base_url}{path}"
        sess = self._session or _requests
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = sess.request(method, url, **kwargs)
        except _requests.exceptions.RequestException as exc:
            raise OllamaUnavailable(f"Ollama unreachable at {self.base_url}") from exc

        if response.status_code >= 400:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
            )
        return response

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and responds 200 to /api/tags."""
        try:
            self._do("GET", "/api/tags")
            return True
        except OllamaUnavailable:
            return False

    def embed(self, text: str, model: str) -> list[float]:
        """Return the embedding vector for a single text."""
        response = self._do(
            "POST",
            "/api/embeddings",
            json={"model": model, "prompt": text},
        )
        data = response.json()
        if "embedding" not in data:
            raise OllamaUnavailable("Ollama response missing 'embedding'")
        return list(data["embedding"])

    def embed_batch(self, texts: list[str], model: str, batch_size: int = 16) -> list[list[float]]:
        """Embed multiple texts sequentially in small batches.

        Sequential to avoid overloading a local Ollama server. Chunk size
        is bounded so progress callbacks stay responsive.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            for text in texts[i : i + batch_size]:
                vectors.append(self.embed(text, model))
        return vectors


# ---------------------------------------------------------------------------
# AIManager: orchestrates extract -> chunk -> embed -> persist
# ---------------------------------------------------------------------------


class AIManager:
    """End-to-end PDF ingestion into a per-project ChromaDB collection."""

    COLLECTION_NAME = "documents"

    def __init__(
        self,
        config_manager: Any,
        file_manager: Any,
        ollama_client: OllamaClient | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.file_manager = file_manager
        self.ollama = ollama_client or OllamaClient()

    # ----- configuration -------------------------------------------------

    def get_ia_settings(self) -> dict[str, Any]:
        """Return the IA section from config.yaml, with defaults applied."""
        cfg = self.config_manager.load()
        defaults = {
            "ollama_url": "http://localhost:11434",
            "embedding_model": "qwen3-embedding:4b",
            "chunk_size": 500,
            "chunk_overlap": 50,
        }
        ia = cfg.get("ia") or {}
        merged = dict(defaults)
        if isinstance(ia, dict):
            merged.update(ia)
        return merged

    def validate_ollama(self, url: str | None = None) -> tuple[bool, str]:
        """Check that Ollama is reachable. Returns (ok, message)."""
        target_url = url or self.get_ia_settings()["ollama_url"]
        client = OllamaClient(base_url=target_url, timeout=5.0)
        if client.is_available():
            return True, f"Ollama reachable at {target_url}"
        return False, f"Ollama not reachable at {target_url}"

    # ----- ingestion ------------------------------------------------------

    def _extract_pages(self, pdf_path: Path) -> list[str]:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        try:
            pages = [page.get_text("text") or "" for page in doc]
        finally:
            doc.close()
        return pages

    def _chroma_collection(self, project_name: str):
        """Return a ChromaDB collection rooted at projects/<name>/chroma.db."""
        import chromadb

        project_dir = self.file_manager.project_path(project_name)
        chroma_dir = project_dir / "chroma.db"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(chroma_dir))
        return client.get_or_create_collection(self.COLLECTION_NAME)

    def digest_pdf(
        self,
        project_name: str,
        pdf_path: Path,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> DigestSummary:
        """Extract, chunk, embed and persist a PDF.

        Raises ``OllamaUnavailable`` if the embedding service is down.
        Raises ``FileNotFoundError`` if the project does not exist.
        """
        settings = self.get_ia_settings()
        project_dir = self.file_manager.project_path(project_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project not found: {project_name}")

        started = time.monotonic()

        if progress_cb:
            progress_cb({"phase": "extracting", "elapsed": 0.0})

        pages = self._extract_pages(pdf_path)

        if progress_cb:
            progress_cb({"phase": "chunking", "elapsed": time.monotonic() - started})

        chunker = PDFChunker(
            chunk_size=int(settings["chunk_size"]),
            chunk_overlap=int(settings["chunk_overlap"]),
        )
        chunks = chunker.split(pages)

        if not chunks:
            # No text extracted; nothing to embed. Record zero chunks and exit.
            duration = time.monotonic() - started
            summary = DigestSummary(
                pages=len(pages),
                chunks=0,
                duration_seconds=round(duration, 3),
                project_name=project_name,
            )
            if progress_cb:
                progress_cb({"phase": "done", "elapsed": duration, "summary": summary.to_dict()})
            return summary

        if progress_cb:
            progress_cb(
                {"phase": "embedding", "elapsed": time.monotonic() - started, "total": len(chunks)}
            )

        vectors = self.ollama.embed_batch(
            [c.text for c in chunks],
            model=settings["embedding_model"],
        )

        if progress_cb:
            progress_cb({"phase": "storing", "elapsed": time.monotonic() - started})

        collection = self._chroma_collection(project_name)
        ids = [f"{project_name}-{c.index}" for c in chunks]
        metadatas = [{"page": c.page, "index": c.index} for c in chunks]
        collection.add(
            ids=ids,
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=metadatas,
        )

        duration = time.monotonic() - started
        summary = DigestSummary(
            pages=len(pages),
            chunks=len(chunks),
            duration_seconds=round(duration, 3),
            project_name=project_name,
        )
        if progress_cb:
            progress_cb({"phase": "done", "elapsed": duration, "summary": summary.to_dict()})
        return summary