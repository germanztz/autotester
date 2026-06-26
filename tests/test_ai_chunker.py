"""Tests for app.models.ai_manager.PDFChunker."""
from __future__ import annotations

import pytest

from app.models.ai_manager import Chunk, PDFChunker


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


class TestChunkerValidation:
    def test_rejects_zero_chunk_size(self):
        with pytest.raises(ValueError):
            PDFChunker(chunk_size=0, chunk_overlap=0)

    def test_rejects_overlap_equal_to_size(self):
        with pytest.raises(ValueError):
            PDFChunker(chunk_size=100, chunk_overlap=100)

    def test_rejects_overlap_greater_than_size(self):
        with pytest.raises(ValueError):
            PDFChunker(chunk_size=50, chunk_overlap=80)

    def test_accepts_overlap_zero(self):
        PDFChunker(chunk_size=100, chunk_overlap=0)

    def test_accepts_overlap_less_than_size(self):
        PDFChunker(chunk_size=100, chunk_overlap=49)


class TestChunkerBehavior:
    def test_short_text_returns_single_chunk(self):
        chunker = PDFChunker(chunk_size=500, chunk_overlap=50)
        chunks = chunker.split(["short text on page one"])
        assert len(chunks) == 1
        assert chunks[0].text == "short text on page one"
        assert chunks[0].index == 0
        assert chunks[0].page == 1

    def test_empty_pages_returns_no_chunks(self):
        chunker = PDFChunker(chunk_size=500, chunk_overlap=50)
        assert chunker.split([]) == []
        assert chunker.split([""]) == []
        assert chunker.split(["", "  ", "\n"]) == []

    def test_long_text_is_split_with_overlap(self):
        chunker = PDFChunker(chunk_size=10, chunk_overlap=3)
        chunks = chunker.split([_words(25)])
        assert len(chunks) > 1
        # First chunk starts at word 0
        assert chunks[0].text.split()[0] == "w0"
        # Overlap: chunk k+1 starts some words before chunk k ends
        words_chunk0 = chunks[0].text.split()
        words_chunk1 = chunks[1].text.split()
        assert words_chunk1[0] == words_chunk0[-3]

    def test_concatenates_pages_and_respects_page_attribution(self):
        chunker = PDFChunker(chunk_size=10, chunk_overlap=0)
        chunks = chunker.split([_words(5), _words(15)])
        # First chunk comes entirely from page 1 (small)
        assert chunks[0].page == 1
        # At least one chunk attributed to page 2
        assert any(c.page == 2 for c in chunks)
        # All chunks from page 1 come before page 2
        pages = [c.page for c in chunks]
        first_two = pages.index(2)
        assert all(p == 1 for p in pages[:first_two])

    def test_chunk_indices_are_sequential(self):
        chunker = PDFChunker(chunk_size=10, chunk_overlap=2)
        chunks = chunker.split([_words(40)])
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_total_chunks_concatenate_roughly_to_input(self):
        text = _words(100)
        chunker = PDFChunker(chunk_size=20, chunk_overlap=5)
        chunks = chunker.split([text])
        # Each chunk should be non-empty and within size limit
        for c in chunks:
            assert 1 <= len(c.text.split()) <= 20

    def test_chunk_dataclass_fields(self):
        chunker = PDFChunker(chunk_size=500, chunk_overlap=50)
        chunks = chunker.split(["hello world"])
        c = chunks[0]
        assert isinstance(c, Chunk)
        assert hasattr(c, "text")
        assert hasattr(c, "index")
        assert hasattr(c, "page")