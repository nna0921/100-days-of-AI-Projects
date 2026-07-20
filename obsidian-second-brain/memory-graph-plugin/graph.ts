import type { Driver, Integer } from "neo4j-driver";
// @ts-ignore — neo4j-driver's browser bundle (ESM), no colocated .d.ts for
// this deep import. Importing this specific file (not "neo4j-driver" itself)
// keeps bundling on the WebSocket channel only, never Node's TCP socket one.
import neo4j from "neo4j-driver/lib/browser/neo4j-web.esm.js";

import type { ExtractedRelation } from "./extract";
import type { MemoryGraphSettings } from "./settings";

export function getDriver(settings: MemoryGraphSettings): Driver {
  return neo4j.driver(
    settings.neo4jUri,
    neo4j.auth.basic(settings.neo4jUser, settings.neo4jPassword)
  );
}

export async function ensureConstraints(driver: Driver): Promise<void> {
  const session = driver.session();
  try {
    await session.run(
      "CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS " +
        "FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
    );
    await session.run(
      "CREATE CONSTRAINT note_path_unique IF NOT EXISTS " +
        "FOR (n:Note) REQUIRE n.path IS UNIQUE"
    );
  } finally {
    await session.close();
  }
}

export function normalizeName(name: string): string {
  return name.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

/** Looks up stored content hashes for the given note paths, for incremental skip. */
export async function getNoteHashes(
  driver: Driver,
  paths: string[]
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  if (paths.length === 0) return map;

  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (n:Note) WHERE n.path IN $paths RETURN n.path AS path, n.contentHash AS contentHash",
      { paths }
    );
    for (const record of result.records) {
      const hash = record.get("contentHash");
      if (hash) map.set(record.get("path"), hash);
    }
    return map;
  } finally {
    await session.close();
  }
}

const _UPSERT_NOTE_QUERY = `
MERGE (n:Note {path: $path})
SET n.title = $title,
    n.contentHash = $contentHash,
    n.ingested_at = datetime($ingestedAt)
`;

/** Touches a :Note node's metadata + content hash — called for every note whose
 * content changed, even if extraction found zero relations in it, so it's
 * correctly skipped on the next incremental run. */
export async function upsertNote(
  driver: Driver,
  params: { path: string; title: string; contentHash: string; ingestedAt: string }
): Promise<void> {
  const session = driver.session();
  try {
    await session.run(_UPSERT_NOTE_QUERY, params);
  } finally {
    await session.close();
  }
}

const _UPSERT_RELATION_QUERY = `
MERGE (note:Note {path: $sourceNote})
  ON CREATE SET note.title = $noteTitle, note.ingested_at = datetime($ingestedAt)

MERGE (subj:Entity {name: $subjectName, type: $subjectType})
  ON CREATE SET subj.created_at = datetime($ingestedAt)
MERGE (obj:Entity {name: $objectName, type: $objectType})
  ON CREATE SET obj.created_at = datetime($ingestedAt)

MERGE (subj)-[r:REL {type: $predicate, source_note: $sourceNote}]->(obj)
  ON CREATE SET
    r.confidence = $confidence,
    r.valid_from = datetime($validFrom),
    r.last_seen = datetime($lastSeen),
    r.status = "active"
  ON MATCH SET
    r.confidence = $confidence,
    r.last_seen = datetime($lastSeen)

MERGE (subj)-[:MENTIONED_IN]->(note)
MERGE (obj)-[:MENTIONED_IN]->(note)
`;

export async function upsertRelation(driver: Driver, relation: ExtractedRelation): Promise<void> {
  const session = driver.session();
  try {
    await session.run(_UPSERT_RELATION_QUERY, {
      subjectName: normalizeName(relation.subject),
      subjectType: relation.subjectType,
      objectName: normalizeName(relation.object),
      objectType: relation.objectType,
      predicate: relation.predicate,
      confidence: relation.confidence,
      sourceNote: relation.sourceNote,
      noteTitle: relation.noteTitle,
      validFrom: new Date(relation.validFrom).toISOString(),
      lastSeen: new Date(relation.lastSeen).toISOString(),
      ingestedAt: new Date().toISOString(),
    });
  } finally {
    await session.close();
  }
}

export async function upsertRelations(
  driver: Driver,
  relations: ExtractedRelation[]
): Promise<void> {
  for (const relation of relations) {
    await upsertRelation(driver, relation);
  }
}

export async function clearGraph(driver: Driver): Promise<void> {
  const session = driver.session();
  try {
    await session.run("MATCH (n) DETACH DELETE n");
  } finally {
    await session.close();
  }
}

function toNumber(value: Integer | number): number {
  return typeof value === "number" ? value : value.toNumber();
}

export interface GraphCounts {
  entities: number;
  notes: number;
  relations: number;
  mentions: number;
}

export async function getCounts(driver: Driver): Promise<GraphCounts> {
  const session = driver.session();
  try {
    const entities = await session.run("MATCH (e:Entity) RETURN count(e) AS c");
    const notes = await session.run("MATCH (n:Note) RETURN count(n) AS c");
    const rels = await session.run("MATCH ()-[r:REL]->() RETURN count(r) AS c");
    const mentions = await session.run("MATCH ()-[m:MENTIONED_IN]->() RETURN count(m) AS c");
    return {
      entities: toNumber(entities.records[0].get("c")),
      notes: toNumber(notes.records[0].get("c")),
      relations: toNumber(rels.records[0].get("c")),
      mentions: toNumber(mentions.records[0].get("c")),
    };
  } finally {
    await session.close();
  }
}
