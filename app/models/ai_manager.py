"""AI manager for autotester: PDF extraction, chunking, embeddings, vector store.

Layered so each concern can be tested independently:

    PDFChunker      -> pure function: text -> chunks
    OllamaClient    -> HTTP wrapper: /api/tags, /api/embed, /api/embeddings
    AIManager       -> orchestration: extract -> chunk -> embed -> chroma
    DigestSummary   -> result type returned to controllers
"""
from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from app.utils.logging_setup import get_logger

logger = get_logger()


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


# Retry policy for HTTP calls. Connection errors, read timeouts and 5xx
# responses are retried with exponential backoff (1s, 2s, 4s). 4xx errors
# (e.g., 404 model not found) are NOT retried — they indicate real config
# bugs that retrying would just mask.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)
_RETRYABLE_HTTP = {500, 502, 503, 504}


class OllamaClient:
    """HTTP client for the Ollama endpoints we use.

    Features:
    - Connection pooling via a shared ``requests.Session``.
    - Probes the modern batch endpoint ``/api/embed`` (plural) on first
      use; falls back to the legacy per-text ``/api/embeddings`` endpoint
      when the modern one returns 404.
    - Retries transient failures (connection errors, read timeouts, 5xx)
      up to three times with exponential backoff (1s, 2s, 4s).

    Tests can override behaviour by passing a ``session=`` (a
    ``requests.Session`` instance or a mock) and by patching
    ``app.models.ai_manager.time.sleep``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
        session: Any | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
        backoff_base: float = _BACKOFF_BASE_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self.max_attempts = max(1, max_attempts)
        self.backoff_base = backoff_base
        # None = unprobed; True/False cached after first embed_batch call.
        self._batch_supported: bool | None = None

    def _do(self, method: str, path: str, **kwargs: Any) -> Any:
        """Single HTTP attempt (no retry). Wraps errors as OllamaUnavailable."""
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        logger.debug("HTTP %s %s", method, path)
        try:
            response = self._session.request(method, url, **kwargs)
        except _RETRYABLE_EXC as exc:
            raise OllamaUnavailable(f"Ollama unreachable at {self.base_url}") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> {type(exc).__name__}: {exc}"
            ) from exc

        if response.status_code in _RETRYABLE_HTTP:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
            )
        logger.debug("HTTP %s %s -> %s", method, path, response.status_code)
        return response

    def _do_with_retry(self, method: str, path: str, **kwargs: Any) -> Any:
        """Run ``_do`` with retry policy applied."""
        last_exc: OllamaUnavailable | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._do(method, path, **kwargs)
            except OllamaUnavailable as exc:
                last_exc = exc
                # Only retry on transient signals: connection/timeout
                # exceptions are surfaced as "unreachable", 5xx as "HTTP 5xx".
                transient = (
                    "unreachable" in str(exc)
                    or any(f"HTTP {code}" in str(exc) for code in _RETRYABLE_HTTP)
                )
                if not transient or attempt >= self.max_attempts:
                    # Re-raise with attempt count for the final failure.
                    if attempt >= self.max_attempts and transient:
                        logger.warning(
                            "Ollama %s %s failed after %d attempts: %s",
                            method,
                            path,
                            self.max_attempts,
                            exc,
                        )
                        raise OllamaUnavailable(
                            f"{exc} (after {self.max_attempts} attempts)"
                        ) from exc
                    raise
                logger.debug(
                    "Ollama %s %s attempt %d/%d failed: %s (retrying)",
                    method,
                    path,
                    attempt,
                    self.max_attempts,
                    exc,
                )
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        # Defensive: loop always returns or raises.
        raise last_exc  # pragma: no cover

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and responds 200 to /api/tags."""
        try:
            self._do_with_retry("GET", "/api/tags")
            return True
        except OllamaUnavailable:
            return False

    def embed(self, text: str, model: str) -> list[float]:
        """Return the embedding vector for a single text (legacy endpoint)."""
        response = self._do_with_retry(
            "POST",
            "/api/embeddings",
            json={"model": model, "prompt": text},
        )
        data = response.json()
        if "embedding" not in data:
            raise OllamaUnavailable("Ollama response missing 'embedding'")
        return list(data["embedding"])

    def _probe_batch(self) -> bool:
        """Probe whether /api/embed (plural) is supported.

        Sends a tiny batch request; on 200 we cache True, on any failure
        (404 in particular) we cache False and fall back to the legacy
        per-text endpoint.
        """
        try:
            response = self._do("POST", "/api/embed", json={"model": "probe", "input": ["probe"]})
            self._batch_supported = response.status_code == 200
        except OllamaUnavailable:
            self._batch_supported = False
        return self._batch_supported

    def embed_batch(
        self, texts: list[str], model: str, batch_size: int = 16
    ) -> list[list[float]]:
        """Embed multiple texts using the best available Ollama endpoint.

        Tries the modern batch endpoint ``/api/embed`` (plural, accepts
        ``input: [...]``) on first use. If unsupported, falls back to one
        ``/api/embeddings`` call per text. The choice is cached per client
        instance.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        if self._batch_supported is None:
            self._probe_batch()

        mode = "modern" if self._batch_supported else "legacy"
        logger.debug("Embedding %d texts via %s endpoint (model=%s)", len(texts), mode, model)
        if self._batch_supported:
            return self._embed_batch_modern(texts, model, batch_size)
        return self._embed_batch_legacy(texts, model)

    def _embed_batch_modern(
        self, texts: list[str], model: str, batch_size: int
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            response = self._do_with_retry(
                "POST",
                "/api/embed",
                json={"model": model, "input": chunk},
            )
            data = response.json()
            if "embeddings" not in data:
                # Server accepted the endpoint but returned an unexpected
                # payload; treat as a hard failure.
                raise OllamaUnavailable("Ollama /api/embed missing 'embeddings'")
            vectors.extend(list(v) for v in data["embeddings"])
        return vectors

    def _embed_batch_legacy(self, texts: list[str], model: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
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
        request_timeout: float = 60.0,
        batch_size: int = 16,
        max_attempts: int = _MAX_ATTEMPTS,
        backoff_base: float = _BACKOFF_BASE_SECONDS,
    ) -> None:
        self.config_manager = config_manager
        self.file_manager = file_manager
        self.request_timeout = request_timeout
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        settings = self.get_ia_settings()
        self.ollama = ollama_client or OllamaClient(
            base_url=settings["ollama_url"],
            timeout=request_timeout,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )

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
        client = OllamaClient(
            base_url=target_url,
            timeout=5.0,
            max_attempts=self.max_attempts,
            backoff_base=self.backoff_base,
        )
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
        client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
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

        logger.info(
            "AI digest started: project=%s pdf=%s model=%s chunk_size=%s",
            project_name,
            pdf_path,
            settings["embedding_model"],
            settings["chunk_size"],
        )
        started = time.monotonic()

        if progress_cb:
            progress_cb({"phase": "extracting", "elapsed": 0.0})

        pages = self._extract_pages(pdf_path)
        logger.debug("Extracted %d pages from %s", len(pages), pdf_path.name)

        if progress_cb:
            progress_cb({"phase": "chunking", "elapsed": time.monotonic() - started})

        chunker = PDFChunker(
            chunk_size=int(settings["chunk_size"]),
            chunk_overlap=int(settings["chunk_overlap"]),
        )
        chunks = chunker.split(pages)
        logger.debug("Produced %d chunks (chunk_size=%s overlap=%s)", len(chunks), chunker.chunk_size, chunker.chunk_overlap)

        if not chunks:
            # No text extracted; nothing to embed. Record zero chunks and exit.
            duration = time.monotonic() - started
            summary = DigestSummary(
                pages=len(pages),
                chunks=0,
                duration_seconds=round(duration, 3),
                project_name=project_name,
            )
            logger.info(
                "AI digest finished (no chunks): project=%s pages=%s duration=%.3fs",
                project_name,
                len(pages),
                duration,
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
            batch_size=self.batch_size,
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
        logger.info(
            "AI digest finished: project=%s pages=%s chunks=%s duration=%.3fs",
            project_name,
            len(pages),
            len(chunks),
            duration,
        )
        if progress_cb:
            progress_cb({"phase": "done", "elapsed": duration, "summary": summary.to_dict()})
        return summary