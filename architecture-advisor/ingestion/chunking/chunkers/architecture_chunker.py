"""Architecture-pattern chunker for the gpt-rag-ingestion chunker factory.

Most Architecture Center pages are short enough to fit in a single chunk,
but a few long reference architectures benefit from section-aware splitting.
This chunker treats each H2 section as a chunk boundary and falls back to a
fixed character window when no headings are present.

Drop into `gpt-rag-ingestion/chunking/chunkers/architecture_chunker.py` and
register in `chunker_factory.py` for the `architecture-center` source type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

H2_PATTERN = re.compile(r"^##\s+", re.MULTILINE)
DEFAULT_MAX_CHARS = 4000
DEFAULT_OVERLAP_CHARS = 200


@dataclass
class ArchitectureChunk:
    chunk_id: int
    title: str
    section: str
    content: str


class ArchitectureChunker:
    """Section-aware chunker for Azure Architecture Center patterns."""

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> None:
        self._max = max_chars
        self._overlap = overlap_chars

    def chunk(self, title: str, body: str) -> List[ArchitectureChunk]:
        if not body or not body.strip():
            return []

        sections = self._split_by_h2(body)
        chunks: List[ArchitectureChunk] = []
        chunk_id = 0
        for section_title, section_body in sections:
            for piece in self._window(section_body):
                chunks.append(
                    ArchitectureChunk(
                        chunk_id=chunk_id,
                        title=title,
                        section=section_title,
                        content=piece.strip(),
                    )
                )
                chunk_id += 1
        return chunks

    def _split_by_h2(self, body: str) -> List[tuple[str, str]]:
        # If no H2s, return a single untitled section.
        if not H2_PATTERN.search(body):
            return [("", body)]

        parts = H2_PATTERN.split(body)
        # First slice is the lead-in before the first H2.
        sections: List[tuple[str, str]] = []
        if parts[0].strip():
            sections.append(("Overview", parts[0]))
        # Re-pair each H2 title with its following body.
        headings = re.findall(r"^##\s+(.+)$", body, re.MULTILINE)
        for heading, content in zip(headings, parts[1:]):
            sections.append((heading.strip(), content))
        return sections

    def _window(self, text: str) -> List[str]:
        text = text.strip()
        if len(text) <= self._max:
            return [text] if text else []

        pieces: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + self._max, len(text))
            pieces.append(text[start:end])
            if end == len(text):
                break
            start = end - self._overlap
        return pieces
