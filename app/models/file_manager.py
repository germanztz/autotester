"""File manager for autotester.

Each PDF upload becomes a project directory under ``projects/<name>/``,
holding the original PDF (sanitized) plus optionally a metadata file.

Operations:
    - list_projects(): enumerate projects as ``ProjectEntry`` records
    - save_upload(): persist a new PDF into a project directory
    - rename_project(): rename the project folder (with collision suffix)
    - delete_project(): remove the project directory entirely
"""
from __future__ import annotations

import io
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, BinaryIO

from app.utils.validators import is_valid_pdf_bytes, safe_project_name


@dataclass
class ProjectEntry:
    """Lightweight descriptor for a project shown in the sidebar."""

    name: str
    pdf_count: int
    size_bytes: int
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FileManager:
    """Manage project folders on disk under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _ensure_safe_name(self, name: str) -> str:
        cleaned = safe_project_name(name)
        if cleaned != name and name:
            raise ValueError(f"Invalid project name: {name!r}")
        return cleaned

    def project_path(self, name: str) -> Path:
        return self.root / name

    def list_projects(self) -> list[ProjectEntry]:
        """Return all projects (subdirectories containing at least one PDF)."""
        entries: list[ProjectEntry] = []
        if not self.root.exists():
            return entries

        for path in sorted(self.root.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir():
                continue
            pdfs = list(path.glob("*.pdf"))
            if not pdfs:
                continue
            size = sum((p.stat().st_size for p in pdfs), 0)
            created = path.stat().st_ctime
            entries.append(
                ProjectEntry(
                    name=path.name,
                    pdf_count=len(pdfs),
                    size_bytes=size,
                    created_at=created,
                )
            )
        return entries

    def save_upload(
        self,
        fileobj: BinaryIO | bytes,
        original_filename: str,
        project_name: str,
    ) -> ProjectEntry:
        """Save a PDF upload under a project directory.

        Returns the created ``ProjectEntry``. Raises ``ValueError`` if the
        payload is not a valid PDF or if the project name is unsafe.
        """
        if isinstance(fileobj, (bytes, bytearray)):
            fileobj = io.BytesIO(fileobj)

        if not is_valid_pdf_bytes(fileobj):
            raise ValueError("Uploaded file is not a valid PDF")

        clean_name = self._ensure_safe_name(project_name)
        target_dir = self._unique_path(self.root / clean_name)
        target_dir.mkdir(parents=True)

        sanitized_name = self._sanitize_filename(original_filename)
        target_file = target_dir / sanitized_name
        with open(target_file, "wb") as fh:
            shutil.copyfileobj(fileobj, fh)

        size = target_file.stat().st_size
        return ProjectEntry(
            name=target_dir.name,
            pdf_count=1,
            size_bytes=size,
            created_at=target_dir.stat().st_ctime,
        )

    def rename_project(self, old_name: str, new_name: str) -> str:
        """Rename a project directory. Returns the final name used."""
        old_clean = self._ensure_safe_name(old_name)
        new_clean = self._ensure_safe_name(new_name)

        src = self.root / old_clean
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"Project not found: {old_name!r}")

        if src.name == new_clean:
            return src.name

        dst = self._unique_path(self.root / new_clean)
        src.rename(dst)
        return dst.name

    def delete_project(self, name: str) -> None:
        """Delete a project directory and its contents."""
        clean = self._ensure_safe_name(name)
        target = self.root / clean
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Project not found: {name!r}")
        shutil.rmtree(target)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Keep only the basename and ensure a .pdf extension."""
        base = Path(filename).name or "document.pdf"
        if not base.lower().endswith(".pdf"):
            base = base + ".pdf"
        return base

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """If path exists, append _2, _3, ... until free."""
        if not path.exists():
            return path
        parent = path.parent
        stem = path.name
        counter = 2
        while True:
            candidate = parent / f"{stem}_{counter}"
            if not candidate.exists():
                return candidate
            counter += 1