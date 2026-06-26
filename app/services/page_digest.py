"""Lazy, page-by-page PDF digestion for autotester.

Splits a PDF into per-page text stored in a markdown sidecar with
``### Page N`` markers, then embeds each page incrementally. Removing the
marker after a successful embedding acts as a checkpoint so the digest
can resume after an interruption.

Functions:
    extract_to_markdown      — write <name>.md from PDF text
    find_first_pending_page  — smallest page still marked
    remove_marker            — atomic removal of one marker
    get_page_text            — return text between two markers
    is_complete              — true when no markers remain

Class:
    LazyAIManager            — orchestrates one-page-at-a-time embedding
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app.utils.logging_setup import get_logger

logger = get_logger()


_MARKER_RE = re.compile(r"^### Page (\d+)\s*$")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def extract_to_markdown(pdf_path: Path, md_path: Path) -> int:
    """Extract text from a PDF and write a markdown file with page markers.

    The output format is::

        ### Page 1
        <page 1 text>

        ### Page 2
        <page 2 text>
        ...

    Idempotent: if ``md_path`` already exists, the existing file is kept
    unchanged and the page count returned is derived from the marker count
    in the existing file. Returns the number of pages.

    Empty pages produce no text but still get a marker.
    """
    md_path = Path(md_path)
    if md_path.exists():
        # Idempotent: count markers in the existing file.
        with md_path.open(encoding="utf-8") as fh:
            return sum(1 for line in fh if _MARKER_RE.match(line))

    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    try:
        pages = [page.get_text("text") or "" for page in doc]
    finally:
        doc.close()

    lines: list[str] = []
    for i, text in enumerate(pages, start=1):
        lines.append(f"### Page {i}")
        lines.append(text)
        lines.append("")  # blank line separator

    md_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(md_path)
    return len(pages)


def find_first_pending_page(md_path: Path) -> Optional[int]:
    """Return the smallest page number that still has a ``### Page N`` marker.

    Returns ``None`` when no markers remain or the file doesn't exist.
    """
    md_path = Path(md_path)
    if not md_path.exists():
        return None
    pending: list[int] = []
    with md_path.open(encoding="utf-8") as fh:
        for line in fh:
            m = _MARKER_RE.match(line)
            if m:
                pending.append(int(m.group(1)))
    return min(pending) if pending else None


def get_page_text(md_path: Path, page_number: int) -> str:
    """Return the text body for ``page_number``.

    The body is the content between the ``### Page N`` marker for that
    page and the next marker (or end of file). Whitespace is trimmed.
    """
    md_path = Path(md_path)
    if not md_path.exists():
        return ""

    with md_path.open(encoding="utf-8") as fh:
        lines = fh.readlines()

    start = None
    end = len(lines)
    target_marker = f"### Page {page_number}"
    for i, line in enumerate(lines):
        if _MARKER_RE.match(line) and int(_MARKER_RE.match(line).group(1)) == page_number:  # type: ignore[union-attr]
            start = i + 1
            continue
        if start is not None and _MARKER_RE.match(line):
            end = i
            break

    if start is None:
        return ""
    return "\n".join(line.rstrip("\n") for line in lines[start:end]).strip()


def remove_marker(md_path: Path, page_number: int) -> None:
    """Atomically remove the ``### Page N`` marker line from the file.

    The body text below the marker is preserved; only the marker line
    itself is dropped. If the marker is not found, the call is a no-op.
    """
    md_path = Path(md_path)
    if not md_path.exists():
        return

    with md_path.open(encoding="utf-8") as fh:
        lines = fh.readlines()

    target_marker = f"### Page {page_number}"
    new_lines: list[str] = []
    removed = False
    for line in lines:
        if not removed and _MARKER_RE.match(line) and line.strip() == target_marker:
            removed = True
            continue
        new_lines.append(line)

    tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    tmp.write_text("".join(new_lines), encoding="utf-8")
    tmp.replace(md_path)


def is_complete(md_path: Path) -> bool:
    """Return True when no ``### Page N`` markers remain in the file."""
    md_path = Path(md_path)
    if not md_path.exists():
        return True
    with md_path.open(encoding="utf-8") as fh:
        return not any(_MARKER_RE.match(line) for line in fh)


# ---------------------------------------------------------------------------
# LazyAIManager
# ---------------------------------------------------------------------------


_DEFAULT_STATE: dict[str, Any] = {
    "state": "queued",
    "current_page": 0,
    "total_pages": 0,
    "chunks_embedded": 0,
    "error": None,
    "updated_at": 0.0,
}


@dataclass
class DigestSummary:
    """Aggregate result of a completed (or cancelled) digest run."""

    project_name: str
    state: str  # complete | cancelled
    pages: int
    chunks: int
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "state": self.state,
            "pages": self.pages,
            "chunks": self.chunks,
            "duration_seconds": self.duration_seconds,
        }


class LazyAIManager:
    """Orchestrate one-page-at-a-time PDF embedding for a single project."""

    def __init__(self, ai_manager: Any, file_manager: Any) -> None:
        self.ai_manager = ai_manager
        self.file_manager = file_manager
        # Cache cancellation events per project name so the same cancel
        # token works even across worker threads.
        self._cancel_events: dict[str, threading.Event] = {}

    # ----- paths ----------------------------------------------------------

    def _project_dir(self, project_name: str) -> Path:
        return self.file_manager.project_path(project_name)

    def _md_path(self, project_name: str) -> Path:
        return self._project_dir(project_name) / f"{project_name}.md"

    def _state_path(self, project_name: str) -> Path:
        return self._project_dir(project_name) / "digest.json"

    # ----- state persistence ---------------------------------------------

    def _load_state(self, project_name: str) -> dict[str, Any]:
        path = self._state_path(project_name)
        if not path.exists():
            return dict(_DEFAULT_STATE)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(_DEFAULT_STATE)
            merged.update({k: v for k, v in data.items() if k in _DEFAULT_STATE})
            return merged
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULT_STATE)

    def _persist_state(self, project_name: str, **fields: Any) -> dict[str, Any]:
        current = self._load_state(project_name)
        current.update(fields)
        current["updated_at"] = time.time()
        path = self._state_path(project_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(path)
        return current

    # ----- public API -----------------------------------------------------

    def ensure_markdown(self, project_name: str, pdf_path: Path) -> Path:
        """Extract the PDF to ``<name>.md`` if not already present.

        Returns the markdown file path. Idempotent.
        """
        md_path = self._md_path(project_name)
        n_pages = extract_to_markdown(pdf_path, md_path)
        # Persist total_pages on first extraction; preserve existing state otherwise.
        existing = self._load_state(project_name)
        if existing.get("total_pages") != n_pages:
            self._persist_state(project_name, total_pages=n_pages)
        return md_path

    def project_status(self, project_name: str) -> dict[str, Any]:
        """Return the current digest state for the project.

        If the project does not exist on disk, returns ``{"state": "error"}``.
        """
        if not self._project_dir(project_name).exists():
            return {"state": "error", "error": "project not found"}
        return self._load_state(project_name)

    def process_one_page(
        self, project_name: str, on_progress: Optional[Callable[[dict[str, Any]], None]] = None
    ) -> Optional[dict[str, Any]]:
        """Embed the next pending page; return progress info or ``None`` when done.

        On success, removes the corresponding ``### Page N`` marker and
        updates ``digest.json``. On Ollama failure, transitions the state
        to ``error`` and re-raises the exception.
        """
        state = self._load_state(project_name)
        md_path = self._md_path(project_name)
        if not md_path.exists():
            # Nothing to do; treat as complete.
            self._persist_state(project_name, state="complete")
            return None

        page = find_first_pending_page(md_path)
        if page is None:
            self._persist_state(project_name, state="complete")
            return None

        self._persist_state(project_name, state="processing", current_page=page)
        text = get_page_text(md_path, page)
        try:
            vector = self.ai_manager.ollama.embed(text, model=self.ai_manager.get_ia_settings()["embedding_model"])
        except Exception as exc:  # noqa: BLE001
            self._persist_state(
                project_name,
                state="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        collection = self.ai_manager._chroma_collection(project_name)
        chunk_id = f"{project_name}-p{page}"
        collection.add(
            ids=[chunk_id],
            embeddings=[vector],
            documents=[text],
            metadatas=[{"page": page}],
        )

        remove_marker(md_path, page)

        new_chunks = state.get("chunks_embedded", 0) + 1
        info = {"page": page, "chunks_embedded": new_chunks, "state": "processing"}
        self._persist_state(project_name, chunks_embedded=new_chunks)

        if on_progress:
            on_progress({"phase": "page_done", **info})

        return info

    def cancel(self, project_name: str) -> None:
        """Signal that a running digest for this project should stop.

        The next ``process_one_page`` call (or the current ``run_to_completion``
        loop) will exit early and leave the remaining ``### Page N`` markers
        in place so the digest can resume later.
        """
        ev = self._cancel_events.setdefault(project_name, threading.Event())
        ev.set()

    def is_cancelled(self, project_name: str) -> bool:
        return self._cancel_events.get(project_name, threading.Event()).is_set()

    def clear_cancel(self, project_name: str) -> None:
        ev = self._cancel_events.get(project_name)
        if ev:
            ev.clear()

    def run_to_completion(
        self,
        project_name: str,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> DigestSummary:
        """Loop ``process_one_page`` until complete or cancelled.

        Returns a ``DigestSummary`` with the final state (``complete`` or
        ``cancelled``).
        """
        started = time.monotonic()
        cleared = False
        while True:
            if self.is_cancelled(project_name) and not cleared:
                # User clicked stop; do one final cleanup pass then exit.
                self._persist_state(project_name, state="cancelled")
                cleared = True
            if cleared:
                break
            info = self.process_one_page(project_name, on_progress=on_progress)
            if info is None:
                break

        duration = time.monotonic() - started
        state = self._load_state(project_name)
        final_state = "cancelled" if cleared else "complete"
        self._persist_state(project_name, state=final_state)
        if on_progress:
            on_progress(
                {
                    "phase": "done",
                    "state": final_state,
                    "duration_seconds": duration,
                }
            )
        return DigestSummary(
            project_name=project_name,
            state=final_state,
            pages=state.get("total_pages", 0),
            chunks=state.get("chunks_embedded", 0),
            duration_seconds=round(duration, 3),
        )

    def project_pdf_path(self, project_name: str) -> Optional[Path]:
        """Return the path to the project's PDF, or None if not found."""
        project_dir = self._project_dir(project_name)
        if not project_dir.exists():
            return None
        pdfs = sorted(project_dir.glob("*.pdf"))
        return pdfs[0] if pdfs else None

    def start(
        self, project_name: str, job_runner: Any
    ) -> str:
        """Schedule ``run_to_completion`` for the project on the job runner.

        Returns the job_id. Idempotent: a second call while a job is
        already running for the same project is a no-op and returns the
        existing job_id.
        """
        if hasattr(job_runner, "find_by_project"):
            existing = job_runner.find_by_project(project_name)
            if existing:
                return existing
        pdf = self.project_pdf_path(project_name)
        if pdf is None:
            raise FileNotFoundError(f"No PDF found for project {project_name!r}")
        # Clear any stale cancel flag before starting fresh.
        self.clear_cancel(project_name)
        job_id = job_runner.submit(
            self._run_wrapper, project_name, pdf
        )
        if hasattr(job_runner, "register_project"):
            job_runner.register_project(job_id, project_name)
        return job_id

    def _run_wrapper(self, project_name: str, pdf_path: Path) -> DigestSummary:
        """Internal wrapper that ensures markdown and runs to completion."""
        self.ensure_markdown(project_name, pdf_path)
        return self.run_to_completion(project_name)