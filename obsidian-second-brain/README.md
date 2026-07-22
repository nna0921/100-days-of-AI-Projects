<p align="center">
  <img src="assets/memory_graph_wordmark.png" alt="Memory Graph" width="480">
</p>

# Memory Graph

An Obsidian plugin that turns your everyday notes into a self-updating
personal knowledge graph. Write normally — no manual linking, no tagging.
Memory Graph reads your vault, extracts entities and relationships with a
local LLM, and keeps them in Neo4j: tracking what's currently true, what's
changed over time, and what genuinely contradicts itself.

**Runs entirely locally.** No cloud, no paid APIs, no third party ever sees
your notes — Neo4j runs in Docker on your machine, extraction runs on a
local Ollama model. This stack costs $0 to run.

## What it does

- **Extracts facts** from your notes as `(subject, predicate, object)`
  triples — people, projects, places, orgs, concepts, events, and how
  they relate.
- **Catches contradictions.** If two notes assert incompatible facts about
  the same thing (e.g. two different birthplaces), it flags the conflict
  for you instead of silently picking one.
- **Tracks change over time.** A job change or a move isn't a contradiction
  — it's history. Superseded facts stay visible, with a trail back to when
  they changed and why.
- **Deduplicates entities** written under different names ("Kestrel" vs
  "Kestrel Consulting"), without silently merging anything it isn't sure
  about — merges always go through a human review step.
- **Syncs back to your vault** as generated notes, one per entity, so the
  graph is browsable as plain markdown, not locked away in a database.
- **A sidebar panel** inside Obsidian shows everything that needs your
  attention: disputed facts, pending merges, recently superseded facts, and
  overall graph stats — with a badge on the ribbon icon so you know at a
  glance whether anything needs a look.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- [Ollama](https://ollama.com) installed, with two models pulled:
  ```bash
  brew install ollama
  ollama pull llama3.1:8b          # extraction + contradiction adjudication
  ollama pull nomic-embed-text     # predicate/entity similarity matching
  ```
- [Obsidian](https://obsidian.md) with the vault you want to use
- Node.js (to build the plugin)

A 7–8B model needs ~8GB free RAM (16GB total recommended). No GPU required,
just slower.

## Setup

**1. Start Neo4j**
```bash
cp .env.example .env   # edit NEO4J_PASSWORD if you want a different one
docker compose up -d
```
Neo4j Browser is at `http://localhost:7474` (user `neo4j`, password from
`.env`) if you ever want to inspect the graph directly.

**2. Build the plugin**
```bash
cd memory-graph-plugin
npm install
npm run build
```

**3. Install it into your vault**

Copy (or symlink) `main.js`, `manifest.json`, and `styles.css` into your
vault's plugin folder:
```bash
cp main.js manifest.json styles.css "/path/to/your/vault/.obsidian/plugins/memory-graph/"
```
Then in Obsidian: **Settings → Community plugins → enable "Memory Graph"**.

**4. Configure it**

Open the plugin's settings tab and confirm/set:
- Neo4j URI, user, password (must match your `.env`)
- Ollama URL and model names
- Any folders to exclude from ingestion

## Using it

Everything is available from the command palette (`Cmd/Ctrl+P`), or via the
ribbon icon (network icon) to open the sidebar panel.

| Command | What it does |
|---|---|
| **Update everything** | Runs the full pipeline in one go: ingest → resolve entities → resolve contradictions → sync to vault. The command to reach for normally. |
| **Ingest vault** | Scans for changed notes and extracts facts from them. Incremental — only reprocesses notes whose content actually changed. |
| **Resolve entities** | Re-clusters the whole graph to find and merge duplicate entities, or flag ones that need a human decision. |
| **Resolve contradictions** | Checks all active facts for conflicts and classifies each as a genuine change, a real conflict, or an extraction error. |
| **Sync to vault** | Regenerates one markdown note per entity, so the graph is readable and linkable as plain notes. |
| **Clear graph** | Wipes everything in Neo4j. Doesn't touch your vault's markdown files. |
| **Open Memory Graph panel** | Opens the sidebar review panel. |

### The sidebar panel

Opens in the right sidebar, reads live from Neo4j, and always shows four
sections, most important first:

1. **Needs review** — disputed facts, with both conflicting claims, the
   reasoning behind the conflict, and links back to both source notes.
2. **Pending merges** — duplicate entities waiting on your approval, with
   any type-mismatch warnings. Click a row to review and approve or reject.
3. **Recently superseded** — facts that changed, most recent first: what it
   used to be, until when, what it is now.
4. **Stats** — entity count, active/superseded/disputed relation counts,
   pending merges.

Every entity name and source-note link is clickable, jumping straight to the
relevant generated note or original note. The ribbon icon carries a badge
with the count of things needing attention (disputed + pending merges), so
you know before you even open the panel.

## Project layout

```
docker-compose.yml           # neo4j:5-community, ports 7474 / 7687
.env.example                 # NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OLLAMA_*
memory-graph-plugin/
  main.ts                    # plugin entry point, commands, ribbon icon
  view.ts                    # the sidebar review panel (ItemView)
  mergeModal.ts              # merge-suggestion review/approve UI
  ingest.ts                  # orchestrates scan → extract → resolve → write
  extract.ts                 # LLM extraction + controlled predicate mapping
  resolve.ts                 # entity deduplication (exact/fuzzy/embedding)
  contradictions.ts          # LLM-adjudicated contradiction resolution
  vaultSync.ts                # generates one markdown note per entity
  graph.ts                   # all Neo4j reads/writes
  settings.ts                # plugin settings tab
```

## Graph schema

**Nodes**
- `(:Entity {name, type, aliases, created_at})` — `type` ∈ `Person | Project | Concept | Org | Place | Event`
- `(:Note {path, title, contentHash, ingested_at})`
- `(:MergeSuggestion {...})` — the pending-merge queue

**Relationships**
- `(:Entity)-[:REL {type, confidence, valid_from, last_seen, status, source_note, controlled}]->(:Entity)` — `status` ∈ `active | superseded | disputed | rejected`
- `(:Entity)-[:MENTIONED_IN]->(:Note)`
