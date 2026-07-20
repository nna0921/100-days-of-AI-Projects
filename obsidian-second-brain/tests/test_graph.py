from datetime import datetime, timezone

import pytest

from memory_graph.extract import ExtractedRelation
from memory_graph.graph import ensure_constraints, get_counts, get_driver, upsert_relations


@pytest.fixture(scope="module")
def driver():
    d = get_driver()
    try:
        d.verify_connectivity()
    except Exception:
        d.close()
        pytest.skip("Neo4j is not reachable; start it with `docker compose up -d`")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean_graph(driver):
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    ensure_constraints(driver)
    yield
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")


def _sample_relations() -> list[ExtractedRelation]:
    mtime = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    return [
        ExtractedRelation(
            subject="Anna",
            subject_type="Person",
            predicate="works_on",
            object="Memory Graph",
            object_type="Project",
            confidence=0.9,
            source_note="people/anna-zubair.md",
            note_title="Anna Zubair",
            valid_from=mtime,
            last_seen=mtime,
        ),
        ExtractedRelation(
            subject="Anna",
            subject_type="Person",
            predicate="lives_in",
            object="Lahore",
            object_type="Place",
            confidence=0.9,
            source_note="people/anna-zubair.md",
            note_title="Anna Zubair",
            valid_from=mtime,
            last_seen=mtime,
        ),
    ]


def test_upsert_is_idempotent(driver):
    relations = _sample_relations()

    upsert_relations(driver, relations)
    first_counts = get_counts(driver)

    upsert_relations(driver, relations)
    second_counts = get_counts(driver)

    assert first_counts == second_counts
    assert first_counts["entities"] == 3  # Anna, Memory Graph, Lahore
    assert first_counts["notes"] == 1
    assert first_counts["relations"] == 2


def test_upsert_updates_last_seen_on_reassertion(driver):
    mtime = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    later_mtime = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)

    relation = ExtractedRelation(
        subject="Anna",
        subject_type="Person",
        predicate="works_on",
        object="Memory Graph",
        object_type="Project",
        confidence=0.5,
        source_note="people/anna-zubair.md",
        note_title="Anna Zubair",
        valid_from=mtime,
        last_seen=mtime,
    )
    upsert_relations(driver, [relation])

    reasserted = relation.model_copy(
        update={"confidence": 0.95, "last_seen": later_mtime}
    )
    upsert_relations(driver, [reasserted])

    with driver.session() as session:
        record = session.run(
            "MATCH ()-[r:REL {type: 'works_on'}]->() RETURN r.confidence AS c, "
            "r.last_seen AS last_seen, r.valid_from AS valid_from"
        ).single()

    assert record["c"] == 0.95
    assert record["last_seen"].to_native() == later_mtime
    assert record["valid_from"].to_native() == mtime  # valid_from stays fixed
