from datetime import datetime, timezone

from memory_graph.extract import extract_from_chunk
from memory_graph.ingest import Chunk
from memory_graph.llm import LLMBackend, Triple, extract_triples


class FakeBackend(LLMBackend):
    def __init__(self, payload: str):
        self.payload = payload

    def generate_json(self, prompt: str) -> str:
        return self.payload


def test_extract_triples_returns_well_formed_triples():
    payload = """
    [
      {"subject": "Anna", "subject_type": "Person", "predicate": "works_on",
       "object": "Memory Graph", "object_type": "Project", "confidence": 0.9}
    ]
    """
    triples = extract_triples("Anna works on Memory Graph.", backend=FakeBackend(payload))

    assert len(triples) == 1
    triple = triples[0]
    assert isinstance(triple, Triple)
    assert triple.subject == "Anna"
    assert triple.predicate == "works_on"
    assert triple.object == "Memory Graph"
    assert 0.0 <= triple.confidence <= 1.0


def test_extract_triples_skips_malformed_items():
    payload = """
    [
      {"subject": "Anna", "subject_type": "Person", "predicate": "works_on",
       "object": "Memory Graph", "object_type": "Project", "confidence": 0.9},
      {"subject": "Bad", "confidence": "not-a-number"}
    ]
    """
    triples = extract_triples("...", backend=FakeBackend(payload))
    assert len(triples) == 1


def test_extract_triples_handles_invalid_json():
    triples = extract_triples("...", backend=FakeBackend("not json at all"))
    assert triples == []


def test_extract_triples_empty_text_short_circuits():
    triples = extract_triples("   ", backend=FakeBackend("[]"))
    assert triples == []


def test_extract_from_chunk_attaches_note_metadata():
    payload = """
    [
      {"subject": "Anna", "subject_type": "Person", "predicate": "lives_in",
       "object": "Berlin", "object_type": "Place", "confidence": 0.95}
    ]
    """
    mtime = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
    chunk = Chunk(
        note_path="anna-moved-to-berlin.md",
        note_title="Anna moved to Berlin",
        mtime=mtime,
        heading="Update",
        text="Anna lives in Berlin now.",
    )

    relations = extract_from_chunk(chunk, backend=FakeBackend(payload))

    assert len(relations) == 1
    relation = relations[0]
    assert relation.subject == "Anna"
    assert relation.object == "Berlin"
    assert relation.source_note == "anna-moved-to-berlin.md"
    assert relation.note_title == "Anna moved to Berlin"
    assert relation.valid_from == mtime
    assert relation.last_seen == mtime
