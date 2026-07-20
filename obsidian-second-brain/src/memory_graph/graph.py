"""Neo4j driver, schema constraints, and idempotent MERGE upserts."""

from __future__ import annotations

from datetime import datetime, timezone

from neo4j import Driver, GraphDatabase

from memory_graph.config import get_settings
from memory_graph.extract import ExtractedRelation


def get_driver() -> Driver:
    settings = get_settings()
    return GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def ensure_constraints(driver: Driver) -> None:
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT note_path_unique IF NOT EXISTS "
            "FOR (n:Note) REQUIRE n.path IS UNIQUE"
        )


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


_UPSERT_RELATION_QUERY = """
MERGE (note:Note {path: $source_note})
  ON CREATE SET note.title = $note_title, note.ingested_at = datetime($ingested_at)

MERGE (subj:Entity {name: $subject_name, type: $subject_type})
  ON CREATE SET subj.created_at = datetime($ingested_at)
MERGE (obj:Entity {name: $object_name, type: $object_type})
  ON CREATE SET obj.created_at = datetime($ingested_at)

MERGE (subj)-[r:REL {type: $predicate, source_note: $source_note}]->(obj)
  ON CREATE SET
    r.confidence = $confidence,
    r.valid_from = datetime($valid_from),
    r.last_seen = datetime($last_seen),
    r.status = "active"
  ON MATCH SET
    r.confidence = $confidence,
    r.last_seen = datetime($last_seen)

MERGE (subj)-[:MENTIONED_IN]->(note)
MERGE (obj)-[:MENTIONED_IN]->(note)
"""


def upsert_relation(driver: Driver, relation: ExtractedRelation) -> None:
    with driver.session() as session:
        session.run(
            _UPSERT_RELATION_QUERY,
            subject_name=normalize_name(relation.subject),
            subject_type=relation.subject_type,
            object_name=normalize_name(relation.object),
            object_type=relation.object_type,
            predicate=relation.predicate,
            confidence=relation.confidence,
            source_note=relation.source_note,
            note_title=relation.note_title,
            valid_from=relation.valid_from.isoformat(),
            last_seen=relation.last_seen.isoformat(),
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )


def upsert_relations(driver: Driver, relations: list[ExtractedRelation]) -> None:
    for relation in relations:
        upsert_relation(driver, relation)


def get_counts(driver: Driver) -> dict[str, int]:
    """Returns node/edge counts, mainly used to assert idempotency in tests."""
    with driver.session() as session:
        entities = session.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
        notes = session.run("MATCH (n:Note) RETURN count(n) AS c").single()["c"]
        rels = session.run("MATCH ()-[r:REL]->() RETURN count(r) AS c").single()["c"]
        mentions = session.run(
            "MATCH ()-[m:MENTIONED_IN]->() RETURN count(m) AS c"
        ).single()["c"]
        return {
            "entities": entities,
            "notes": notes,
            "relations": rels,
            "mentions": mentions,
        }
