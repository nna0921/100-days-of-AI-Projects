import type { Driver } from "neo4j-driver";

import { callOllamaEmbed } from "./ollama";
import type { MemoryGraphSettings } from "./settings";
import type { ExtractedRelation } from "./extract";
import {
  getAllEntities,
  setEntityAliases,
  mergeEntity,
  deleteEntity,
  getAllMentions,
  getAllEdges,
  persistMergeSuggestions,
  deleteMergeSuggestionsReferencing,
  type EntityRecord,
} from "./graph";

export interface CanonicalEntity {
  name: string;
  type: string;
  aliases: string[];
}

export interface AmbiguityLogEntry {
  candidate: string;
  type: string;
  matchedCandidates: string[];
  tier: "fuzzy" | "embedding";
}

export interface SharedContext {
  found: boolean;
  evidence: string[];
}

export type SharedContextChecker = (
  candidate: { name: string; type: string },
  matched: CanonicalEntity
) => SharedContext;

export interface MergeSuggestion {
  candidateName: string;
  candidateType: string;
  matchedName: string;
  matchedType: string;
  matchedAliases: string[];
  tier: "exact" | "fuzzy" | "embedding";
  typeMismatch: boolean;
  sharedContext: SharedContext;
  similarity?: number;
}

export interface JunkLogEntry {
  raw: string;
  type: string;
  reason: string;
}

// Embedding similarity cutoff for merging a candidate entity name into an
// existing one. Higher than the predicate threshold (0.65) because a wrong
// entity merge silently corrupts the graph (two different people's facts
// blend into one node), whereas a wrong predicate mapping just loses one
// edge — see the bias-against-merging rule below.
export const ENTITY_SIMILARITY_THRESHOLD = 0.85;

const PRONOUNS = new Set(["i", "he", "she", "they", "it", "we", "you"]);
const POSSESSIVES = new Set(["his", "her", "their", "its", "my", "your", "our"]);
// Conservative: only names made up ENTIRELY of these are dropped, so a real
// entity that merely contains a stopword ("Bank of America") survives.
const STOPWORDS = new Set([
  "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
  "with", "by", "from", "into", "onto", "over", "under", "more", "most",
  "some", "any", "this", "that", "these", "those", "is", "are", "was",
  "were", "be", "been", "being", "has", "have", "had", "do", "does", "did",
  "not", "no", "so", "if", "than", "then", "as",
]);
const HONORIFICS = new Set(["mr", "mrs", "ms", "dr", "prof"]);

export function normalizeEntityName(raw: string): string {
  const collapsed = raw.trim().toLowerCase().replace(/\s+/g, " ");
  const tokens = collapsed
    .split(" ")
    .filter(Boolean)
    .map((t) => t.replace(/[.,!?;:]+$/g, ""));
  while (tokens.length > 1 && HONORIFICS.has(tokens[0])) {
    tokens.shift();
  }
  return tokens.join(" ").trim();
}

export interface JunkCheck {
  junk: boolean;
  reason?: string;
}

/** True if at least one whitespace-split token starts with an uppercase
 * letter. Must run on the model's raw output before anything lowercases
 * it — by the time an entity is written to the graph its name is already
 * lowercase (see graph.ts's normalizeName), so this only means something
 * at ingest time, never when re-scanning already-stored entities. */
function hasCapitalizedToken(raw: string): boolean {
  return raw
    .trim()
    .split(/\s+/)
    .some((token) => /^[A-Z]/.test(token));
}

/** Rule 1: the cheapest filter, run before any matching.
 *
 * checkCapitalization should be true only when rawName is still in the
 * model's original casing (ingest time). Passing true against
 * already-lowercased graph data (the standalone resolve pass) would flag
 * every existing entity as junk, since none of them have any casing left. */
export function checkJunkEntity(rawName: string, checkCapitalization: boolean): JunkCheck {
  const normalized = normalizeEntityName(rawName);
  if (normalized.length < 2) return { junk: true, reason: "single character / too short" };

  const tokens = normalized.split(" ").filter(Boolean);
  if (tokens.length === 1 && PRONOUNS.has(tokens[0])) return { junk: true, reason: "pronoun" };
  if (POSSESSIVES.has(tokens[0])) return { junk: true, reason: "starts with possessive" };
  if (tokens.every((t) => STOPWORDS.has(t))) return { junk: true, reason: "entirely stopwords" };
  if (checkCapitalization && !hasCapitalizedToken(rawName)) {
    return { junk: true, reason: "no capitalized token in the model's raw output" };
  }

  return { junk: false };
}

function isTokenPrefixOf(shortTokens: string[], longTokens: string[]): boolean {
  if (shortTokens.length > longTokens.length) return false;
  for (let i = 0; i < shortTokens.length; i++) {
    if (!longTokens[i].startsWith(shortTokens[i])) return false;
  }
  return true;
}

/**
 * Rule 3b. Symmetric: works for equal-token-count abbreviations ("anna z" /
 * "anna zubair", "tom w" / "tom whitfield") and for a bare first name being
 * a prefix of a fuller name ("anna" / "anna zubair") — the latter is a
 * deliberate generalization beyond the two-example spec, since embeddings
 * alone don't clear 0.85 for single-name-vs-full-name pairs (measured
 * ~0.70-0.81 on this vault) and the bare-first-name case is exactly what's
 * needed to collapse anna/anna z/anna zubair into one node.
 */
export function tokenPrefixMatch(a: string, b: string): boolean {
  const ta = a.split(" ").filter(Boolean);
  const tb = b.split(" ").filter(Boolean);
  return isTokenPrefixOf(ta, tb) || isTokenPrefixOf(tb, ta);
}

function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

interface ResolveContext {
  settings: MemoryGraphSettings;
  pool: CanonicalEntity[];
  ambiguous: AmbiguityLogEntry[];
  junk: JunkLogEntry[];
  suggestions: MergeSuggestion[];
  embeddingCache: Map<string, number[]>;
  checkCapitalization: boolean;
  sharedContextChecker: SharedContextChecker;
}

const NO_SHARED_CONTEXT: SharedContextChecker = () => ({ found: false, evidence: [] });

async function embedManyCached(ctx: ResolveContext, names: string[]): Promise<number[][]> {
  const toFetch = names.filter((n) => !ctx.embeddingCache.has(n));
  if (toFetch.length > 0) {
    const vecs = await callOllamaEmbed(ctx.settings.ollamaUrl, ctx.settings.ollamaEmbeddingModel, toFetch);
    toFetch.forEach((n, i) => ctx.embeddingCache.set(n, vecs[i]));
  }
  return names.map((n) => ctx.embeddingCache.get(n)!);
}

function addAlias(entity: CanonicalEntity, alias: string): void {
  if (!entity.aliases.includes(alias)) entity.aliases.push(alias);
}

/** Rule 5: longest matched form (by character length) wins as canonical —
 * and since exact/fuzzy matching is now cross-type, its type comes along
 * with it. "northwind" (tagged Project by one note) fuzzy-matching
 * "northwind labs" (tagged Org by another) should end up as one Org entity,
 * not a Project entity with an Org-flavored name. */
function mergeCandidateIntoPool(entity: CanonicalEntity, normalized: string, candidateType: string): CanonicalEntity {
  addAlias(entity, normalized);
  if (normalized.length > entity.name.length) {
    entity.name = normalized;
    entity.type = candidateType;
  }
  return entity;
}

function createNewCanonical(ctx: ResolveContext, normalized: string, type: string): CanonicalEntity {
  const entity: CanonicalEntity = { name: normalized, type, aliases: [normalized] };
  ctx.pool.push(entity);
  return entity;
}

/**
 * Resolves one candidate mention against the (growing) pool. Returns the
 * live CanonicalEntity object — not a name string — because a later
 * candidate in the same batch can still rename this entity (rule 5), and
 * callers must read `.name` only after the whole batch is resolved so every
 * mention of the same person ends up pointing at the same final name.
 */
async function resolveOne(
  rawName: string,
  type: string,
  ctx: ResolveContext
): Promise<CanonicalEntity | null> {
  const junkCheck = checkJunkEntity(rawName, ctx.checkCapitalization);
  if (junkCheck.junk) {
    ctx.junk.push({ raw: rawName, type, reason: junkCheck.reason! });
    return null;
  }

  const normalized = normalizeEntityName(rawName);

  // (a) exact normalized match — cross-type search (the graph's uniqueness
  // constraint is (name, type), so the same real name can already exist
  // twice under different type guesses), but a type mismatch always
  // downgrades to a suggestion regardless of how exact the name match is —
  // a plausibly-different-thing-with-the-same-name-and-different-type is
  // exactly the case that needs a human, not an algorithm.
  const exact = ctx.pool.find((e) => e.name === normalized || e.aliases.includes(normalized));
  if (exact) {
    if (exact.type === type) {
      addAlias(exact, normalized);
      return exact;
    }
    pushSuggestion(ctx, { name: normalized, type }, exact, "exact");
    return createNewCanonical(ctx, normalized, type);
  }

  // (b) fuzzy token-prefix match — cross-type search, but auto-merge only
  // fires for same-type matches that also have corroborating shared
  // context (a shared source note or a shared graph neighbour). Anything
  // short of that — type mismatch, or same-type with no corroboration —
  // becomes a suggestion instead of a silent merge.
  const fuzzyMatches = ctx.pool.filter((e) => tokenPrefixMatch(normalized, e.name));
  if (fuzzyMatches.length === 1) {
    const match = fuzzyMatches[0];
    const typeMismatch = match.type !== type;
    const shared = typeMismatch ? { found: false, evidence: [] } : ctx.sharedContextChecker({ name: normalized, type }, match);
    if (!typeMismatch && shared.found) {
      return mergeCandidateIntoPool(match, normalized, type);
    }
    pushSuggestion(ctx, { name: normalized, type }, match, "fuzzy", typeMismatch, shared);
    return createNewCanonical(ctx, normalized, type);
  }
  if (fuzzyMatches.length > 1) {
    ctx.ambiguous.push({
      candidate: normalized,
      type,
      matchedCandidates: fuzzyMatches.map((e) => e.name),
      tier: "fuzzy",
    });
    return createNewCanonical(ctx, normalized, type);
  }

  // (c) embedding similarity — same-type only (semantic closeness across
  // types isn't good evidence of identity), and always a suggestion now,
  // never an auto-merge: it's the weakest tier, used only when exact and
  // prefix both failed, so it's exactly the kind of "plausible but not
  // certain" match that should go to review rather than merge silently.
  const sameType = ctx.pool.filter((e) => e.type === type);
  if (sameType.length > 0) {
    const [candVec] = await embedManyCached(ctx, [normalized]);
    const poolVecs = await embedManyCached(ctx, sameType.map((e) => e.name));
    const above = sameType
      .map((e, i) => ({ e, sim: cosineSimilarity(candVec, poolVecs[i]) }))
      .filter((s) => s.sim >= ENTITY_SIMILARITY_THRESHOLD);

    if (above.length === 1) {
      const shared = ctx.sharedContextChecker({ name: normalized, type }, above[0].e);
      pushSuggestion(ctx, { name: normalized, type }, above[0].e, "embedding", false, shared, above[0].sim);
      return createNewCanonical(ctx, normalized, type);
    }
    if (above.length > 1) {
      ctx.ambiguous.push({
        candidate: normalized,
        type,
        matchedCandidates: above.map((s) => s.e.name),
        tier: "embedding",
      });
      return createNewCanonical(ctx, normalized, type);
    }
  }

  return createNewCanonical(ctx, normalized, type);
}

function pushSuggestion(
  ctx: ResolveContext,
  candidate: { name: string; type: string },
  matched: CanonicalEntity,
  tier: "exact" | "fuzzy" | "embedding",
  typeMismatch = true,
  sharedContext: SharedContext = { found: false, evidence: [] },
  similarity?: number
): void {
  ctx.suggestions.push({
    candidateName: candidate.name,
    candidateType: candidate.type,
    matchedName: matched.name,
    matchedType: matched.type,
    matchedAliases: [...matched.aliases],
    tier,
    typeMismatch,
    sharedContext,
    similarity,
  });
}

export interface ResolveBatchResult {
  resolved: (CanonicalEntity | null)[];
  pool: CanonicalEntity[];
  ambiguous: AmbiguityLogEntry[];
  junk: JunkLogEntry[];
  suggestions: MergeSuggestion[];
}

/**
 * Resolves a batch of candidate (name, type) mentions against a starting
 * pool of already-canonical entities. Candidates are processed sequentially
 * (not in parallel) because each one can grow or rename the pool that later
 * candidates match against — that sequencing is what lets three mentions of
 * the same person in one batch collapse into a single node regardless of
 * the order they're seen in.
 */
export async function resolveEntityBatch(
  candidates: { name: string; type: string }[],
  existingPool: EntityRecord[],
  settings: MemoryGraphSettings,
  options: { checkCapitalization?: boolean; sharedContextChecker?: SharedContextChecker } = {}
): Promise<ResolveBatchResult> {
  const ctx: ResolveContext = {
    settings,
    pool: existingPool.map((e) => ({ name: e.name, type: e.type, aliases: [...e.aliases] })),
    ambiguous: [],
    junk: [],
    suggestions: [],
    embeddingCache: new Map(),
    checkCapitalization: options.checkCapitalization ?? false,
    sharedContextChecker: options.sharedContextChecker ?? NO_SHARED_CONTEXT,
  };

  const resolved: (CanonicalEntity | null)[] = [];
  for (const c of candidates) {
    resolved.push(await resolveOne(c.name, c.type, ctx));
  }

  return { resolved, pool: ctx.pool, ambiguous: ctx.ambiguous, junk: ctx.junk, suggestions: ctx.suggestions };
}

/** Shared-context evidence from the current graph state: a shared source
 * note, or a shared active-edge neighbour. Used to corroborate same-type
 * fuzzy matches before letting them auto-merge. */
function buildGraphSharedContextChecker(
  mentions: { entityName: string; entityType: string; notePath: string }[],
  edges: { subject: string; subjectType: string; object: string; objectType: string; status: string }[]
): SharedContextChecker {
  const key = (name: string, type: string) => `${name} ${type}`;

  const notesByEntity = new Map<string, Set<string>>();
  for (const m of mentions) {
    const k = key(m.entityName, m.entityType);
    if (!notesByEntity.has(k)) notesByEntity.set(k, new Set());
    notesByEntity.get(k)!.add(m.notePath);
  }

  const neighborsByEntity = new Map<string, Set<string>>();
  const addNeighbor = (a: string, b: string) => {
    if (!neighborsByEntity.has(a)) neighborsByEntity.set(a, new Set());
    neighborsByEntity.get(a)!.add(b);
  };
  for (const e of edges) {
    if (e.status !== "active") continue;
    const sKey = key(e.subject, e.subjectType);
    const oKey = key(e.object, e.objectType);
    addNeighbor(sKey, oKey);
    addNeighbor(oKey, sKey);
  }

  // Union a set across every known alias of an entity, not just its current
  // display name. Necessary because the pool entry's .name can be renamed
  // mid-batch (rule 5) as it accumulates merges — e.g. once "anna" merges
  // into "anna z", the combined entity's real evidence is the UNION of what
  // "anna" and "anna z" each had on their own original nodes, not just
  // whatever the static mentions/edges snapshot recorded under the string
  // "anna z". Looking up by .name alone would silently lose "anna"'s half
  // of the evidence on every subsequent comparison.
  function unionByAliases(map: Map<string, Set<string>>, entity: { name: string; type: string; aliases?: string[] }): Set<string> {
    const names = entity.aliases && entity.aliases.length > 0 ? entity.aliases : [entity.name];
    const union = new Set<string>();
    for (const alias of names) {
      for (const v of map.get(key(alias, entity.type)) ?? []) union.add(v);
    }
    return union;
  }

  return (candidate, matched) => {
    const evidence: string[] = [];

    const cNotes = unionByAliases(notesByEntity, candidate);
    const mNotes = unionByAliases(notesByEntity, matched);
    const sharedNotes = [...cNotes].filter((n) => mNotes.has(n));
    if (sharedNotes.length > 0) evidence.push(`co-mentioned in: ${sharedNotes.join(", ")}`);

    const cNeighbors = unionByAliases(neighborsByEntity, candidate);
    const mNeighbors = unionByAliases(neighborsByEntity, matched);
    const sharedNeighbors = [...cNeighbors].filter((n) => mNeighbors.has(n));
    if (sharedNeighbors.length > 0) {
      evidence.push(`shared neighbour: ${sharedNeighbors.map((k) => k.split(" ")[0]).join(", ")}`);
    }

    return { found: evidence.length > 0, evidence };
  };
}

export interface ResolveRelationsResult {
  relations: ExtractedRelation[];
  droppedRelations: { subject: string; object: string; reason: string }[];
  ambiguous: AmbiguityLogEntry[];
  junk: JunkLogEntry[];
  suggestions: MergeSuggestion[];
}

/**
 * Ingest-time integration: resolves every subject/object mention in a batch
 * of freshly extracted relations against the existing graph, rewrites each
 * relation to use its canonical entity name, drops relations that reference
 * a junk entity, and persists the resulting aliases. Call this before
 * upsertRelations.
 */
export async function resolveRelationEntities(
  driver: Driver,
  relations: ExtractedRelation[],
  settings: MemoryGraphSettings
): Promise<ResolveRelationsResult> {
  if (relations.length === 0) {
    return { relations: [], droppedRelations: [], ambiguous: [], junk: [], suggestions: [] };
  }

  const [existingPool, existingMentions, existingEdges] = await Promise.all([
    getAllEntities(driver),
    getAllMentions(driver),
    getAllEdges(driver),
  ]);

  const candidates: { name: string; type: string }[] = [];
  // In-batch co-occurrence: two brand-new mentions sharing a source note in
  // THIS batch haven't been written to the graph yet, so getAllMentions
  // alone wouldn't see them as co-mentioned — merge in this batch's own
  // (subject/object, sourceNote) pairs so that counts as evidence too.
  const mentions = [...existingMentions];
  for (const r of relations) {
    candidates.push({ name: r.subject, type: r.subjectType });
    candidates.push({ name: r.object, type: r.objectType });
    mentions.push({ entityName: normalizeEntityName(r.subject), entityType: r.subjectType, notePath: r.sourceNote, noteTitle: null });
    mentions.push({ entityName: normalizeEntityName(r.object), entityType: r.objectType, notePath: r.sourceNote, noteTitle: null });
  }
  const sharedContextChecker = buildGraphSharedContextChecker(mentions, existingEdges);

  const { resolved, pool, ambiguous, junk, suggestions } = await resolveEntityBatch(candidates, existingPool, settings, {
    checkCapitalization: true, // candidates here are still the model's raw-cased output
    sharedContextChecker,
  });

  const finalRelations: ExtractedRelation[] = [];
  const droppedRelations: { subject: string; object: string; reason: string }[] = [];
  relations.forEach((r, i) => {
    const subjCanon = resolved[2 * i];
    const objCanon = resolved[2 * i + 1];
    if (!subjCanon || !objCanon) {
      droppedRelations.push({
        subject: r.subject,
        object: r.object,
        reason: !subjCanon ? "subject was junk" : "object was junk",
      });
      return;
    }
    // subjectType/objectType must be rewritten too, not just the name — a
    // cross-type merge (northwind Project -> northwind labs Org) means the
    // canonical entity's type can differ from what this particular mention
    // was originally tagged. Writing the stale type would MERGE a node with
    // the right name but the wrong type, splitting the entity right back
    // into two.
    finalRelations.push({
      ...r,
      subject: subjCanon.name,
      subjectType: subjCanon.type,
      object: objCanon.name,
      objectType: objCanon.type,
    });
  });

  for (const entity of pool) {
    await setEntityAliases(driver, entity);
  }

  await persistMergeSuggestions(driver, suggestions);

  return { relations: finalRelations, droppedRelations, ambiguous, junk, suggestions };
}

export interface ResolveGraphResult {
  entitiesBefore: number;
  entitiesAfter: number;
  merges: { from: string; fromType: string; into: string; intoType: string }[];
  deletedJunk: JunkLogEntry[];
  ambiguous: AmbiguityLogEntry[];
  suggestions: MergeSuggestion[];
}

/**
 * Standalone pass over the whole existing graph: treats every current
 * :Entity as a candidate against an empty starting pool, so entities that
 * already fragmented in earlier runs (before this feature existed) get
 * clustered and merged retroactively.
 *
 * checkCapitalization is always off here — names read back from the graph
 * are already lowercase (graph.ts normalizes on write), so there's no
 * casing left to check.
 */
export async function resolveExistingGraph(
  driver: Driver,
  settings: MemoryGraphSettings
): Promise<ResolveGraphResult> {
  const [existing, mentions, edges] = await Promise.all([getAllEntities(driver), getAllMentions(driver), getAllEdges(driver)]);
  const candidates = existing
    .map((e) => ({ name: e.name, type: e.type }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const { resolved, ambiguous, junk, suggestions } = await resolveEntityBatch(candidates, [], settings, {
    checkCapitalization: false,
    sharedContextChecker: buildGraphSharedContextChecker(mentions, edges),
  });

  // Group original (name, type) entities by the canonical entity they
  // resolved to. A cross-type merge means an original member's own type can
  // differ from the canonical's final type, so both must travel together.
  const groups = new Map<CanonicalEntity, { name: string; type: string }[]>();
  candidates.forEach((c, i) => {
    const canon = resolved[i];
    if (!canon) return;
    if (!groups.has(canon)) groups.set(canon, []);
    groups.get(canon)!.push(c);
  });

  const merges: { from: string; fromType: string; into: string; intoType: string }[] = [];
  for (const [canon, originals] of groups) {
    for (const original of originals) {
      if (original.name === canon.name && original.type === canon.type) continue; // this IS the surviving node
      merges.push({ from: original.name, fromType: original.type, into: canon.name, intoType: canon.type });
      await mergeEntity(driver, {
        dupName: original.name,
        dupType: original.type,
        canonName: canon.name,
        canonType: canon.type,
        aliases: canon.aliases,
      });
      // This auto-merge (shared-context corroborated, so no human review
      // needed) can resolve a pair an EARLIER ingest run already persisted
      // as a pending MergeSuggestion — without this, that suggestion node
      // keeps naming an entity that no longer exists and lingers in the
      // panel forever, out of sync with what this run actually found.
      await deleteMergeSuggestionsReferencing(driver, { name: original.name, type: original.type });
    }
    // Persist final aliases even for singleton groups / the surviving node.
    await setEntityAliases(driver, canon);
  }

  for (const j of junk) {
    await deleteEntity(driver, { name: normalizeEntityName(j.raw), type: j.type });
  }

  await persistMergeSuggestions(driver, suggestions);

  const entitiesAfter = candidates.length - merges.length - junk.length;

  return {
    entitiesBefore: candidates.length,
    entitiesAfter,
    merges,
    deletedJunk: junk,
    ambiguous,
    suggestions,
  };
}
