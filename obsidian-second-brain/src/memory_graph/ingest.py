"""Walks an Obsidian vault, strips frontmatter, and chunks notes by heading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)

# Rough chunk budget: ~600 tokens ≈ ~450 words.
CHUNK_WORD_BUDGET = 450


@dataclass(frozen=True)
class Note:
    path: str  # relative to vault root, used as stable identifier
    title: str
    mtime: datetime
    body: str  # frontmatter stripped


@dataclass(frozen=True)
class Chunk:
    note_path: str
    note_title: str
    mtime: datetime
    heading: str
    text: str


def _strip_frontmatter(raw: str) -> str:
    return FRONTMATTER_RE.sub("", raw, count=1)


def _title_from(body: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def load_notes(vault_path: str | Path) -> list[Note]:
    vault_path = Path(vault_path)
    notes: list[Note] = []
    for md_path in sorted(vault_path.rglob("*.md")):
        raw = md_path.read_text(encoding="utf-8")
        body = _strip_frontmatter(raw)
        mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
        rel_path = str(md_path.relative_to(vault_path))
        title = _title_from(body, fallback=md_path.stem)
        notes.append(Note(path=rel_path, title=title, mtime=mtime, body=body))
    return notes


def _split_by_heading(body: str) -> list[tuple[str, str]]:
    """Returns [(heading, section_text), ...]. Text before the first heading
    gets heading '' (top-level / no section)."""
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        return [("", body.strip())] if body.strip() else []

    sections: list[tuple[str, str]] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        heading_text = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_text = body[start:end].strip()
        if section_text:
            sections.append((heading_text, section_text))
    return sections


def _split_by_words(text: str, budget: int) -> list[str]:
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current and current_words + para_words > budget:
            chunks.append("\n\n".join(current))
            current, current_words = [], 0
        current.append(para)
        current_words += para_words

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def chunk_note(note: Note) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, section_text in _split_by_heading(note.body):
        for piece in _split_by_words(section_text, CHUNK_WORD_BUDGET):
            chunks.append(
                Chunk(
                    note_path=note.path,
                    note_title=note.title,
                    mtime=note.mtime,
                    heading=heading,
                    text=piece,
                )
            )
    return chunks


def load_and_chunk_vault(vault_path: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for note in load_notes(vault_path):
        chunks.extend(chunk_note(note))
    return chunks
