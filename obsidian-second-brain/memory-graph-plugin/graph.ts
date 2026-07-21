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
    r.predicate_raw = $predicateRaw,
    r.valid_from = datetime($validFrom),
    r.last_seen = datetime($lastSeen),
    r.status = "active"
  ON MATCH SET
    r.confidence = $confidence,
    r.predicate_raw = $predicateRaw,
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
      predicateRaw: relation.predicateRaw,
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

export interface EntityRecord {
  name: string;
  type: string;
  aliases: string[];
}

export async function getAllEntities(driver: Driver): Promise<EntityRecord[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (e:Entity) RETURN e.name AS name, e.type AS type, coalesce(e.aliases, [e.name]) AS aliases"
    );
    return result.records.map((r) => ({
      name: r.get("name"),
      type: r.get("type"),
      aliases: r.get("aliases"),
    }));
  } finally {
    await session.close();
  }
}

export async function setEntityAliases(
  driver: Driver,
  params: { name: string; type: string; aliases: string[] }
): Promise<void> {
  const session = driver.session();
  try {
    await session.run("MERGE (e:Entity {name: $name, type: $type}) SET e.aliases = $aliases", params);
  } finally {
    await session.close();
  }
}

export async function deleteEntity(driver: Driver, params: { name: string; type: string }): Promise<void> {
  const session = driver.session();
  try {
    await session.run("MATCH (e:Entity {name: $name, type: $type}) DETACH DELETE e", params);
  } finally {
    await session.close();
  }
}

// Rewires all REL/MENTIONED_IN edges from a duplicate entity onto its
// canonical entity, then deletes the duplicate. Parallel REL edges that
// result from the rewire (same predicate type + same target) are deduped by
// MERGE's own semantics — ON CREATE for the first one seen, ON MATCH keeps
// whichever of the two has the later last_seen. No APOC available (plain
// neo4j:5-community), so this is plain Cypher rather than apoc.refactor.mergeNodes.
const _MERGE_ENTITY_QUERY = `
MATCH (dup:Entity {name: $dupName, type: $dupType})
MATCH (canon:Entity {name: $canonName, type: $canonType})

CALL {
  WITH dup, canon
  MATCH (dup)-[r:REL]->(target)
  MERGE (canon)-[r2:REL {type: r.type}]->(target)
  ON CREATE SET r2 = properties(r)
  ON MATCH SET r2 = CASE WHEN r.last_seen > r2.last_seen THEN properties(r) ELSE properties(r2) END
  RETURN count(*) AS outgoingRewired
}

CALL {
  WITH dup, canon
  MATCH (source)-[r:REL]->(dup)
  MERGE (source)-[r2:REL {type: r.type}]->(canon)
  ON CREATE SET r2 = properties(r)
  ON MATCH SET r2 = CASE WHEN r.last_seen > r2.last_seen THEN properties(r) ELSE properties(r2) END
  RETURN count(*) AS incomingRewired
}

CALL {
  WITH dup, canon
  MATCH (dup)-[:MENTIONED_IN]->(note)
  MERGE (canon)-[:MENTIONED_IN]->(note)
  RETURN count(*) AS mentionsRewired
}

SET canon.aliases = $aliases
DETACH DELETE dup
`;

export async function mergeEntity(
  driver: Driver,
  params: { dupName: string; dupType: string; canonName: string; canonType: string; aliases: string[] }
): Promise<void> {
  if (params.dupName === params.canonName && params.dupType === params.canonType) {
    await setEntityAliases(driver, { name: params.canonName, type: params.canonType, aliases: params.aliases });
    return;
  }
  const session = driver.session();
  try {
    await session.run(_MERGE_ENTITY_QUERY, params);
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

export interface ActiveEdge {
  rid: string;
  subject: string;
  subjectType: string;
  predicate: string;
  object: string;
  sourceNote: string;
  validFrom: string; // ISO string
  confidence: number;
  predicateRaw: string;
}

/** Only edges with status "active" are eligible for contradiction detection
 * — a previously superseded/disputed/rejected edge shouldn't be re-flagged. */
export async function getActiveEdges(driver: Driver): Promise<ActiveEdge[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (s:Entity)-[r:REL]->(o:Entity) WHERE r.status = 'active' " +
        "RETURN elementId(r) AS rid, s.name AS subject, s.type AS subjectType, r.type AS predicate, " +
        "o.name AS object, r.source_note AS sourceNote, toString(r.valid_from) AS validFrom, " +
        "r.confidence AS confidence, r.predicate_raw AS predicateRaw " +
        "ORDER BY s.name, r.type, r.valid_from"
    );
    return result.records.map((r) => ({
      rid: r.get("rid"),
      subject: r.get("subject"),
      subjectType: r.get("subjectType"),
      predicate: r.get("predicate"),
      object: r.get("object"),
      sourceNote: r.get("sourceNote"),
      validFrom: r.get("validFrom"),
      confidence: r.get("confidence"),
      predicateRaw: r.get("predicateRaw"),
    }));
  } finally {
    await session.close();
  }
}

/** Applies an adjudicated outcome to one edge. Never deletes — only status
 * and the contradiction fields change; predicate, object, source_note,
 * valid_from, confidence, predicate_raw are untouched so the original
 * wording and provenance survive for future contradiction checks to read. */
export async function applyContradictionOutcome(
  driver: Driver,
  params: {
    rid: string;
    status: "active" | "superseded" | "disputed" | "rejected";
    classification: "CHANGE" | "CONFLICT" | "ERROR";
    reasoning: string;
    winner: boolean;
  }
): Promise<void> {
  const session = driver.session();
  try {
    await session.run(
      "MATCH ()-[r:REL]->() WHERE elementId(r) = $rid " +
        "SET r.status = $status, r.contradiction_classification = $classification, " +
        "r.contradiction_reasoning = $reasoning, r.contradiction_winner = $winner, " +
        "r.contradiction_resolved_at = datetime()",
      params
    );
  } finally {
    await session.close();
  }
}

export interface FullEdge {
  subject: string;
  subjectType: string;
  predicate: string;
  object: string;
  objectType: string;
  status: string;
  confidence: number;
  validFrom: string;
  lastSeen: string;
  sourceNotePath: string;
  sourceNoteTitle: string | null;
  classification: string | null;
  reasoning: string | null;
}

/** Every REL edge regardless of status, with the source note's title
 * resolved (for building human-readable [[wikilinks]] to it). Used for
 * vault sync, which needs to render superseded/disputed edges too, not
 * just active ones. */
export async function getAllEdges(driver: Driver): Promise<FullEdge[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (s:Entity)-[r:REL]->(o:Entity) " +
        "OPTIONAL MATCH (n:Note {path: r.source_note}) " +
        "RETURN s.name AS subject, s.type AS subjectType, r.type AS predicate, " +
        "o.name AS object, o.type AS objectType, r.status AS status, r.confidence AS confidence, " +
        "toString(r.valid_from) AS validFrom, toString(r.last_seen) AS lastSeen, " +
        "r.source_note AS sourceNotePath, n.title AS sourceNoteTitle, " +
        "r.contradiction_classification AS classification, r.contradiction_reasoning AS reasoning " +
        "ORDER BY s.name, r.type"
    );
    return result.records.map((r) => ({
      subject: r.get("subject"),
      subjectType: r.get("subjectType"),
      predicate: r.get("predicate"),
      object: r.get("object"),
      objectType: r.get("objectType"),
      status: r.get("status"),
      confidence: r.get("confidence"),
      validFrom: r.get("validFrom"),
      lastSeen: r.get("lastSeen"),
      sourceNotePath: r.get("sourceNotePath"),
      sourceNoteTitle: r.get("sourceNoteTitle"),
      classification: r.get("classification"),
      reasoning: r.get("reasoning"),
    }));
  } finally {
    await session.close();
  }
}

export interface EntityMention {
  entityName: string;
  entityType: string;
  notePath: string;
  noteTitle: string | null;
}

export async function getAllMentions(driver: Driver): Promise<EntityMention[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (e:Entity)-[:MENTIONED_IN]->(n:Note) " +
        "RETURN e.name AS entityName, e.type AS entityType, n.path AS notePath, n.title AS noteTitle"
    );
    return result.records.map((r) => ({
      entityName: r.get("entityName"),
      entityType: r.get("entityType"),
      notePath: r.get("notePath"),
      noteTitle: r.get("noteTitle"),
    }));
  } finally {
    await session.close();
  }
}
