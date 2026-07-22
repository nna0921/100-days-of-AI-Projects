import type { Driver, Integer } from "neo4j-driver";
// @ts-ignore — neo4j-driver's browser bundle (ESM), no colocated .d.ts for
// this deep import. Importing this specific file (not "neo4j-driver" itself)
// keeps bundling on the WebSocket channel only, never Node's TCP socket one.
import neo4j from "neo4j-driver/lib/browser/neo4j-web.esm.js";

import type { ExtractedRelation } from "./extract";
import type { MemoryGraphSettings } from "./settings";
import type { MergeSuggestion } from "./resolve";

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
    // One-time migration: every edge written before the controlled/
    // uncontrolled tiering existed was, by definition, a controlled-
    // vocabulary predicate — the old code dropped anything else instead of
    // persisting it. Without this backfill, getActiveEdges' new
    // `r.controlled = true` filter would silently exclude all pre-existing
    // edges from contradiction detection, since a missing property compares
    // as null, not true.
    await session.run("MATCH ()-[r:REL]->() WHERE r.controlled IS NULL SET r.controlled = true");
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
    r.controlled = $controlled,
    r.valid_from = datetime($validFrom),
    r.last_seen = datetime($lastSeen),
    r.status = "active"
  ON MATCH SET
    r.confidence = $confidence,
    r.predicate_raw = $predicateRaw,
    r.controlled = $controlled,
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
      controlled: relation.controlled,
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
    const result = await session.run(_MERGE_ENTITY_QUERY, params);
    // Both MATCH clauses have to hit for anything downstream (the CALL
    // blocks, SET, DELETE) to run at all — if either the dup or the canon
    // entity is already gone (e.g. a stale/duplicate suggestion pointing at
    // an entity a previous merge already deleted), containsUpdates() is
    // false and this would otherwise silently no-op while the caller still
    // reports success.
    if (!result.summary.counters.containsUpdates()) {
      throw new Error(
        `Nothing to merge — "${params.dupName}" (${params.dupType}) or ` +
          `"${params.canonName}" (${params.canonType}) no longer exists in the graph.`
      );
    }
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

/** Only edges with status "active" AND controlled=true are eligible for
 * contradiction detection — a previously superseded/disputed/rejected edge
 * shouldn't be re-flagged, and an uncontrolled edge (tier 2: no controlled-
 * predicate match, e.g. "visited France") was never given the
 * single/multi + mutable/immutable classification contradiction detection
 * depends on, so it's excluded rather than mishandled. Any future decay pass
 * is meant to read from this same query, so it inherits the same exclusion
 * for free. */
export async function getActiveEdges(driver: Driver): Promise<ActiveEdge[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (s:Entity)-[r:REL]->(o:Entity) WHERE r.status = 'active' AND r.controlled = true " +
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

export interface RelationStatusCounts {
  active: number;
  superseded: number;
  disputed: number;
  rejected: number;
}

/** Powers the panel's STATS section — one grouped query rather than four
 * separate count() calls. */
export async function getRelationStatusCounts(driver: Driver): Promise<RelationStatusCounts> {
  const session = driver.session();
  try {
    const result = await session.run("MATCH ()-[r:REL]->() RETURN r.status AS status, count(*) AS c");
    const counts: RelationStatusCounts = { active: 0, superseded: 0, disputed: 0, rejected: 0 };
    for (const record of result.records) {
      const status = record.get("status") as string;
      if (status in counts) counts[status as keyof RelationStatusCounts] = toNumber(record.get("c"));
    }
    return counts;
  } finally {
    await session.close();
  }
}

export interface DisputedObject {
  object: string;
  sourceNotePath: string;
  sourceNoteTitle: string | null;
  reasoning: string | null;
}

export interface DisputedGroup {
  subject: string;
  subjectType: string;
  predicate: string;
  objects: DisputedObject[]; // >= 2 conflicting objects for the same (subject, predicate)
}

/** Powers the panel's NEEDS REVIEW section. Groups flat disputed edges by
 * (subject, predicate) so e.g. anna zubair's two disputed born_in edges
 * (karachi, lahore) render as one row with both conflicting objects rather
 * than two separate rows. */
export async function getDisputedGroups(driver: Driver): Promise<DisputedGroup[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (s:Entity)-[r:REL]->(o:Entity) WHERE r.status = 'disputed' " +
        "OPTIONAL MATCH (n:Note {path: r.source_note}) " +
        "RETURN s.name AS subject, s.type AS subjectType, r.type AS predicate, o.name AS object, " +
        "r.source_note AS sourceNotePath, n.title AS sourceNoteTitle, r.contradiction_reasoning AS reasoning " +
        "ORDER BY s.name, r.type, o.name"
    );
    const groups = new Map<string, DisputedGroup>();
    for (const record of result.records) {
      const subject = record.get("subject");
      const subjectType = record.get("subjectType");
      const predicate = record.get("predicate");
      const key = `${subject} ${subjectType} ${predicate}`;
      if (!groups.has(key)) groups.set(key, { subject, subjectType, predicate, objects: [] });
      groups.get(key)!.objects.push({
        object: record.get("object"),
        sourceNotePath: record.get("sourceNotePath"),
        sourceNoteTitle: record.get("sourceNoteTitle"),
        reasoning: record.get("reasoning"),
      });
    }
    return [...groups.values()];
  } finally {
    await session.close();
  }
}

export interface SupersededEntry {
  subject: string;
  subjectType: string;
  predicate: string;
  object: string; // the old, no-longer-true value
  currentObject: string | null; // the active replacement, if one exists
  sourceNotePath: string;
  sourceNoteTitle: string | null;
  untilDate: string; // formatted date the old value stopped being true
  resolvedAt: string; // ISO timestamp, for sorting most-recent-first
}

const _SUPERSEDED_QUERY = `
MATCH (s:Entity)-[r:REL]->(o:Entity) WHERE r.status = 'superseded'
OPTIONAL MATCH (s)-[active:REL {type: r.type}]->(cur:Entity) WHERE active.status = 'active'
OPTIONAL MATCH (n:Note {path: r.source_note})
RETURN s.name AS subject, s.type AS subjectType, r.type AS predicate, o.name AS object,
       cur.name AS currentObject,
       r.source_note AS sourceNotePath, n.title AS sourceNoteTitle,
       toString(coalesce(r.contradiction_resolved_at, r.last_seen)) AS resolvedAt,
       toString(coalesce(active.valid_from, r.last_seen)) AS untilDate
ORDER BY resolvedAt DESC
`;

/** Powers the panel's RECENTLY SUPERSEDED section — "X was Y until <date>,
 * now Z" lines, most recently resolved first. currentObject/untilDate mirror
 * vaultSync's buildSupersededSection logic: the replacement's valid_from is
 * the end date if a replacement exists, otherwise the superseded edge's own
 * last_seen. */
export async function getSupersededEntries(driver: Driver): Promise<SupersededEntry[]> {
  const session = driver.session();
  try {
    const result = await session.run(_SUPERSEDED_QUERY);
    return result.records.map((r) => ({
      subject: r.get("subject"),
      subjectType: r.get("subjectType"),
      predicate: r.get("predicate"),
      object: r.get("object"),
      currentObject: r.get("currentObject"),
      sourceNotePath: r.get("sourceNotePath"),
      sourceNoteTitle: r.get("sourceNoteTitle"),
      untilDate: r.get("untilDate"),
      resolvedAt: r.get("resolvedAt"),
    }));
  } finally {
    await session.close();
  }
}

export interface PendingMergeSuggestion {
  candidateName: string;
  candidateType: string;
  matchedName: string;
  matchedType: string;
  matchedAliases: string[];
  tier: "exact" | "fuzzy" | "embedding";
  typeMismatch: boolean;
  sharedContextFound: boolean;
  sharedContextEvidence: string[];
  similarity: number | null;
  createdAt: string;
}

/** Two independent passes can suggest the same underlying duplicate pair in
 * opposite directions — e.g. resolveRelationEntities (ingest-time) sees a
 * brand-new "tom w" against the already-existing "tom whitfield" and
 * suggests candidate=tom w/matched=tom whitfield, while a later standalone
 * resolveExistingGraph pass re-clusters the WHOLE graph alphabetically from
 * scratch and, because "tom w" now sorts first and becomes the pool entry,
 * suggests the same pair reversed: candidate=tom whitfield/matched=tom w.
 * Keying the suggestion node on the ordered (candidate, matched) fields let
 * both directions persist as two separate nodes for the same pair — approve
 * one and the other silently no-ops (the entity it names is already gone)
 * while still reporting success. Sorting the pair into an order-independent
 * key collapses both directions onto one node. */
function suggestionPairKey(a: { name: string; type: string }, b: { name: string; type: string }): string {
  const x = `${a.name} ${a.type}`;
  const y = `${b.name} ${b.type}`;
  return x <= y ? `${x}${y}` : `${y}${x}`;
}

const _UPSERT_MERGE_SUGGESTION_QUERY = `
MERGE (m:MergeSuggestion {pairKey: $pairKey})
SET m.candidateName = $candidateName,
    m.candidateType = $candidateType,
    m.matchedName = $matchedName,
    m.matchedType = $matchedType,
    m.matchedAliases = $matchedAliases,
    m.tier = $tier,
    m.typeMismatch = $typeMismatch,
    m.sharedContextFound = $sharedContextFound,
    m.sharedContextEvidence = $sharedContextEvidence,
    m.similarity = $similarity,
    m.createdAt = coalesce(m.createdAt, datetime($now))
`;

/** Persists the merge-suggestion queue so the panel can read it back on a
 * later open without re-running resolution — resolveRelationEntities and
 * resolveExistingGraph compute MergeSuggestion[] fresh every run but never
 * stored it anywhere until now. Keyed on the order-independent pair (see
 * suggestionPairKey) so re-suggesting the same pair — even reversed — on a
 * later run updates the same node rather than duplicating it; createdAt is
 * preserved across those updates. */
export async function persistMergeSuggestions(driver: Driver, suggestions: MergeSuggestion[]): Promise<void> {
  if (suggestions.length === 0) return;
  const session = driver.session();
  const now = new Date().toISOString();
  try {
    for (const s of suggestions) {
      await session.run(_UPSERT_MERGE_SUGGESTION_QUERY, {
        pairKey: suggestionPairKey(
          { name: s.candidateName, type: s.candidateType },
          { name: s.matchedName, type: s.matchedType }
        ),
        candidateName: s.candidateName,
        candidateType: s.candidateType,
        matchedName: s.matchedName,
        matchedType: s.matchedType,
        matchedAliases: s.matchedAliases,
        tier: s.tier,
        typeMismatch: s.typeMismatch,
        sharedContextFound: s.sharedContext.found,
        sharedContextEvidence: s.sharedContext.evidence,
        similarity: s.similarity ?? null,
        now,
      });
    }
  } finally {
    await session.close();
  }
}

export async function getPendingMergeSuggestions(driver: Driver): Promise<PendingMergeSuggestion[]> {
  const session = driver.session();
  try {
    const result = await session.run(
      "MATCH (m:MergeSuggestion) RETURN m.candidateName AS candidateName, m.candidateType AS candidateType, " +
        "m.matchedName AS matchedName, m.matchedType AS matchedType, m.matchedAliases AS matchedAliases, " +
        "m.tier AS tier, m.typeMismatch AS typeMismatch, m.sharedContextFound AS sharedContextFound, " +
        "m.sharedContextEvidence AS sharedContextEvidence, m.similarity AS similarity, " +
        "toString(m.createdAt) AS createdAt " +
        "ORDER BY m.createdAt DESC"
    );
    return result.records.map((r) => ({
      candidateName: r.get("candidateName"),
      candidateType: r.get("candidateType"),
      matchedName: r.get("matchedName"),
      matchedType: r.get("matchedType"),
      matchedAliases: r.get("matchedAliases") ?? [],
      tier: r.get("tier"),
      typeMismatch: r.get("typeMismatch"),
      sharedContextFound: r.get("sharedContextFound"),
      sharedContextEvidence: r.get("sharedContextEvidence") ?? [],
      similarity: r.get("similarity"),
      createdAt: r.get("createdAt"),
    }));
  } finally {
    await session.close();
  }
}

export async function getPendingMergeSuggestionCount(driver: Driver): Promise<number> {
  const session = driver.session();
  try {
    const result = await session.run("MATCH (m:MergeSuggestion) RETURN count(m) AS c");
    return toNumber(result.records[0].get("c"));
  } finally {
    await session.close();
  }
}

/** Removes one suggestion from the pending queue — called once a human has
 * approved or rejected it via MergeSuggestionsModal, so it doesn't linger in
 * the panel after being handled. */
export async function deleteMergeSuggestion(
  driver: Driver,
  params: { candidateName: string; candidateType: string; matchedName: string; matchedType: string }
): Promise<void> {
  const session = driver.session();
  try {
    await session.run("MATCH (m:MergeSuggestion {pairKey: $pairKey}) DETACH DELETE m", {
      pairKey: suggestionPairKey(
        { name: params.candidateName, type: params.candidateType },
        { name: params.matchedName, type: params.matchedType }
      ),
    });
  } finally {
    await session.close();
  }
}

/** After a real merge deletes an entity, ANY other pending suggestion that
 * still names it (as either candidate or matched) is now stale — it would
 * mergeEntity() against a node that no longer exists. Called right after a
 * successful approve so those don't linger to silently no-op later. */
export async function deleteMergeSuggestionsReferencing(
  driver: Driver,
  params: { name: string; type: string }
): Promise<void> {
  const session = driver.session();
  try {
    await session.run(
      "MATCH (m:MergeSuggestion) WHERE " +
        "(m.candidateName = $name AND m.candidateType = $type) OR " +
        "(m.matchedName = $name AND m.matchedType = $type) " +
        "DETACH DELETE m",
      params
    );
  } finally {
    await session.close();
  }
}
