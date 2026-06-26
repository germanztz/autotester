"""Utility validators for file uploads and project naming.

Provides functions to validate PDF files (by extension and magic bytes) and
to normalize user-supplied project names into safe filesystem identifiers.
"""
from __future__ import annotations

import io
import re
from typing import Any


PDF_MAGIC = b"%PDF-"
_ALLOWED_PDF_EXT = ".pdf"


def is_valid_pdf_filename(filename: str | None) -> bool:
    """Return True if the filename ends with .pdf (case-insensitive)."""
    if not filename or not isinstance(filename, str):
        return False
    return filename.lower().endswith(_ALLOWED_PDF_EXT)


def _read_start(data: Any, n: int = 5) -> bytes | None:
    """Read the first n bytes from bytes or a file-like object."""
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data[:n])
    if hasattr(data, "stream"):
        try:
            data.stream.seek(0)
            chunk = data.stream.read(n)
            data.stream.seek(0)
            return chunk
        except (AttributeError, OSError):
            return None
    if hasattr(data, "read"):
        try:
            data.seek(0)
            chunk = data.read(n)
            data.seek(0)
            return chunk
        except (AttributeError, OSError):
            return None
    return None


def is_valid_pdf_bytes(data: Any) -> bool:
    """Return True if the provided bytes/file-like starts with the PDF magic."""
    start = _read_start(data)
    if not start:
        return False
    return start.startswith(PDF_MAGIC)


def safe_project_name(name: str | None, max_length: int = 50) -> str:
    """Normalize a user-supplied name into a safe filesystem identifier.

    Removes path separators and unsafe characters; collapses consecutive
    underscores; lowercases. Returns 'project' when the cleaned result
    would be empty.
    """
    if not name:
        return "project"

    cleaned = re.sub(r"[\\/]+", "", name)
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", cleaned)
    cleaned = cleaned.replace("..", "")
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._-")

    if not cleaned:
        return "project"

    cleaned = cleaned.lower()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("._-")

    return cleaned or "project"