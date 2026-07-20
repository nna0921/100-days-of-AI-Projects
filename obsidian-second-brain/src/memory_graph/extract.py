"""Orchestrates extraction: calls llm.py per chunk and attaches provenance
(source note + timestamps) that graph.py needs to write onto edges.
"""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel

from memory_graph.ingest import Chunk
from memory_graph.llm import LLMBackend, Triple, extract_triples

logger = logging.getLogger(__name__)


class ExtractedRelation(BaseModel):
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    confidence: float
    source_note: str
    note_title: str
    valid_from: datetime
    last_seen: datetime


def _to_relation(triple: Triple, chunk: Chunk) -> ExtractedRelation:
    return ExtractedRelation(
        subject=triple.subject,
        subject_type=triple.subject_type,
        predicate=triple.predicate,
        object=triple.object,
        object_type=triple.object_type,
        confidence=triple.confidence,
        source_note=chunk.note_path,
        note_title=chunk.note_title,
        valid_from=chunk.mtime,
        last_seen=chunk.mtime,
    )


def extract_from_chunk(
    chunk: Chunk, backend: LLMBackend | None = None
) -> list[ExtractedRelation]:
    triples = extract_triples(chunk.text, backend=backend)
    return [_to_relation(t, chunk) for t in triples]


def extract_from_chunks(
    chunks: list[Chunk], backend: LLMBackend | None = None
) -> list[ExtractedRelation]:
    relations: list[ExtractedRelation] = []
    for i, chunk in enumerate(chunks, start=1):
        logger.info(
            "Extracting chunk %d/%d (%s%s)",
            i,
            len(chunks),
            chunk.note_path,
            f" > {chunk.heading}" if chunk.heading else "",
        )
        relations.extend(extract_from_chunk(chunk, backend=backend))
    return relations
