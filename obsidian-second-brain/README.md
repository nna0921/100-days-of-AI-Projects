# Memory Graph — Phase 1

A self-updating personal knowledge graph for an Obsidian vault. Phase 1 covers
the ingest → extract → store pipeline: read markdown notes, extract
entity/relationship triples with a local LLM, and write them to Neo4j.

This stack is **$0**: Neo4j Community runs in Docker, extraction runs on a
local Ollama model, and there are no paid APIs. The LLM sits behind a single
interface (`llm.py`) so swapping in a hosted API later is a one-line config
change.

Decay, contradiction resolution, entity-resolution dedup, and Graph RAG are
**not** part of Phase 1 — see "Future work" below.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- [Ollama](https://ollama.com) installed, with a model pulled:
  ```bash
  brew install ollama
  ollama pull llama3.1:8b   # or: ollama pull qwen2.5:7b
  ```
  Verify it works: `ollama run llama3.1:8b "return the JSON array [1,2,3]"`
- Python 3.10+

A 7–8B model needs ~8GB free RAM (16GB total recommended). No GPU required,
just slower. If your machine can't run it, the only paid fallback is a
hosted API — see `llm.py`'s `ApiBackend` stub.

## Setup

```bash
# 1. Start Neo4j
cp .env.example .env   # edit NEO4J_PASSWORD if you want a different one
docker compose up -d
# Neo4j Browser: http://localhost:7474 (user: neo4j, password: from .env)

# 2. Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Make sure Ollama is running and has pulled the model
ollama pull llama3.1:8b
```

## Run

```bash
python -m memory_graph.cli ingest ./sample_vault
```

This reads every `.md` file in `sample_vault/`, chunks it by heading, calls
the local LLM for each chunk, and MERGEs the resulting triples into Neo4j.
Open `http://localhost:7474` and run:

```cypher
MATCH (n) RETURN n LIMIT 200
```

to see the populated graph. Re-running the same command is idempotent —
edges are matched on `(subject, predicate, object, source_note)`, so
re-ingesting only refreshes `confidence`/`last_seen`, it doesn't duplicate.

## Tests

```bash
pytest
```

`test_extract.py` mocks the LLM backend and checks the extraction contract
(well-formed `Triple`s, malformed items skipped, metadata attached).
`test_graph.py` asserts idempotent upserts against a real Neo4j instance —
it auto-skips if Neo4j isn't reachable, so `docker compose up -d` first.

## Project layout

```
docker-compose.yml          # neo4j:5-community, ports 7474 / 7687
pyproject.toml
.env.example                # NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, LLM_BACKEND, OLLAMA_MODEL
src/memory_graph/
  config.py                 # loads .env, picks LLM backend
  llm.py                    # extract_triples(text) -> list[Triple]; Ollama impl + hosted-API stub
  ingest.py                 # walks vault, strips frontmatter, chunks by heading (~600 tokens)
  extract.py                # calls llm.py per chunk, attaches note provenance/timestamps
  graph.py                  # Neo4j driver, constraints, MERGE upserts
  cli.py                    # typer: `ingest <path>`
sample_vault/                # ~15 fake notes: people, projects, places, an org, an event
tests/
  test_extract.py
  test_graph.py
```

## Graph schema

**Nodes**
- `(:Entity {name, type, created_at})` — `type` ∈ `Person | Project | Concept | Org | Place | Event`. `name` is stored normalized (trimmed, lowercased) so entity resolution in Phase 2 has a clean base to work from.
- `(:Note {path, title, ingested_at})`

**Relationships**
- `(:Entity)-[:REL {type, confidence, valid_from, last_seen, status, source_note}]->(:Entity)` — `status` defaults to `"active"`; `confidence` (0–1) comes from the extractor; `valid_from`/`last_seen` are the source note's mtime.
- `(:Entity)-[:MENTIONED_IN]->(:Note)`

Phase 1 doesn't *use* `status`/`confidence`/`last_seen` for any logic yet —
they're written on every edge so Phase 2 (decay + contradiction resolution)
has the data it needs from day one.

**Constraint**: a uniqueness constraint on `(Entity.name, Entity.type)` is
created on startup, so `MERGE` never produces duplicate entity nodes.

## Extraction contract

The LLM is asked to return a strict JSON array (Ollama's `format: "json"`
option enforces this) of:

```json
[
  {"subject": "Anna", "subject_type": "Person",
   "predicate": "works_on", "object": "Memory Graph", "object_type": "Project",
   "confidence": 0.9}
]
```

Each item is validated against a Pydantic `Triple` model; malformed items
are logged and skipped rather than crashing the ingest run.

## The sample vault's built-in conflict

`sample_vault/people/anna-zubair.md` (dated 2026-02-02) says Anna lives in
Lahore. `sample_vault/anna-moved-to-berlin.md` (dated 2026-06-15) says she
moved to Berlin. Phase 1 stores both edges as-is with their respective
`valid_from`/`last_seen` timestamps — it's Phase 2's contradiction
resolution that will look at this pair and decide "change over time, mark
the older one superseded."

## Future work (not in Phase 1)

- Entity resolution (embedding + fuzzy-match dedup of co-referent names)
- Temporal decay of unreasserted facts
- Edge consolidation (merge near-duplicate predicates)
- LLM-adjudicated contradiction resolution
- Graph RAG question answering with citations
- Streamlit demo UI
