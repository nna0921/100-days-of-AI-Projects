import type { Chunk } from "./vault";
import type { MemoryGraphSettings } from "./settings";
import { callOllamaChat, callOllamaEmbed } from "./ollama";

export interface Triple {
  subject: string;
  subjectType: string;
  predicate: string; // always a member of CONTROLLED_PREDICATES — see resolveTriples
  predicateRaw: string;
  object: string;
  objectType: string;
  confidence: number;
}

/** A parsed-and-validated triple whose predicate hasn't been resolved against
 * CONTROLLED_PREDICATES yet. */
export interface UnresolvedTriple {
  subject: string;
  subjectType: string;
  predicateRaw: string;
  object: string;
  objectType: string;
  confidence: number;
}

export interface ExtractedRelation extends Triple {
  sourceNote: string;
  noteTitle: string;
  validFrom: number; // epoch ms
  lastSeen: number; // epoch ms
}

/** The only predicates that end up on an edge's `type`. Prompting alone
 * doesn't hold with llama3.1:8b — the model still invents synonyms and
 * run-on predicates — so this is enforced in code (see resolveTriples), not
 * just requested in the prompt. */
export const CONTROLLED_PREDICATES: readonly string[] = [
  "works_at",
  "works_on",
  "leads",
  "lives_in",
  "born_in",
  "studied_at",
  "founded",
  "uses",
  "recommends",
  "knows",
  "member_of",
  "located_in",
  "part_of",
  "created",
  "replaced_by",
];

export type PredicateCardinality = "single" | "multi";

/**
 * single: an entity has at most one true value at a time — a new value
 * supersedes the old one rather than coexisting with it (contradiction
 * candidates only ever come from these). multi: many simultaneous true
 * values are normal, never a contradiction (a person knows many people,
 * uses many tools, works on many things at once).
 *
 * Only 7 of these 15 were specified directly (single: works_at, lives_in,
 * born_in / multi: knows, uses, works_on, recommends); the rest are a
 * judgment call by analogy — flagged in the contradiction-resolution report
 * for review rather than assumed correct:
 *   located_in, part_of, replaced_by → single (analogous to lives_in: a
 *     thing's location/container/successor is normally one value at a time).
 *   leads, studied_at, founded, member_of, created → multi (a person can
 *     lead multiple projects, have studied at several schools, founded or
 *     created more than one thing, and belong to multiple groups, all
 *     simultaneously true without any of them going stale).
 */
export const PREDICATE_CARDINALITY: Record<string, PredicateCardinality> = {
  works_at: "single",
  works_on: "multi",
  leads: "multi",
  lives_in: "single",
  born_in: "single",
  studied_at: "multi",
  founded: "multi",
  uses: "multi",
  recommends: "multi",
  knows: "multi",
  member_of: "multi",
  located_in: "single",
  part_of: "single",
  created: "multi",
  replaced_by: "single",
};

export type PredicateMutability = "mutable" | "immutable";

/**
 * mutable: the fact can legitimately change over time — a contradiction may
 * be adjudicated as CHANGE, and (later) confidence may decay with elapsed
 * time. immutable: the underlying fact cannot change once true — a
 * contradiction can only be an ERROR (bad extraction) or a genuine CONFLICT,
 * never a CHANGE, and confidence should never decay just because time
 * passed (a birthplace doesn't get less true with age).
 *
 * This is a property of the predicate itself, not something local to
 * contradiction resolution — both the adjudication prompt (see
 * contradictions.ts) and the future confidence-decay pass read it from
 * here, so the two features can't drift apart on what counts as fixed.
 *
 * born_in, located_in, part_of are marked immutable provisionally.
 * born_in is solid (birthplace cannot change). located_in and part_of are
 * weaker assumptions — an org's headquarters can relocate, a project can
 * get reorganized under a different parent — worth revisiting if either
 * starts producing false ERROR/CONFLICT calls in practice. Everything else
 * defaults to mutable.
 */
export const PREDICATE_MUTABILITY: Record<string, PredicateMutability> = {
  works_at: "mutable",
  works_on: "mutable",
  leads: "mutable",
  lives_in: "mutable",
  born_in: "immutable",
  studied_at: "mutable",
  founded: "mutable",
  uses: "mutable",
  recommends: "mutable",
  knows: "mutable",
  member_of: "mutable",
  located_in: "immutable",
  part_of: "immutable",
  created: "mutable",
  replaced_by: "mutable",
};

/** Cosine-similarity cutoff for mapping an invented predicate onto
 * CONTROLLED_PREDICATES via embeddings. Calibrated by hand against
 * nomic-embed-text on this vocabulary: at 0.65, clear synonyms clear the bar
 * (was_born_in→born_in 0.94, would_use→uses 0.83, did_masters_at→studied_at
 * 0.72) while unrelated predicates stay below it (thinks→knows 0.61,
 * warns→recommends 0.63, left→member_of 0.50). It isn't perfect — a couple
 * of borderline cases land on a plausible-but-not-ideal predicate (e.g.
 * works_remotely_for→works_on instead of works_at) — but predicate_raw is
 * always kept on the edge, so a wrong or dropped mapping is reviewable
 * rather than silently lost. */
export const PREDICATE_SIMILARITY_THRESHOLD = 0.65;

/** Sanitizes a predicate to snake_case for the CONTROLLED_PREDICATES
 * exact-match fast path. Does not by itself constrain the result — see
 * resolveTriples for the enforcement step. */
function sanitizeSnakeCase(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
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

// Canonical vocabulary embeddings are stable for the lifetime of a chosen
// embedding model, so they're computed once (one batched call) and reused
// across the whole ingest run rather than per chunk.
let controlledEmbeddingsCache: { model: string; vectors: number[][] } | null = null;

async function getControlledPredicateEmbeddings(settings: MemoryGraphSettings): Promise<number[][]> {
  if (controlledEmbeddingsCache?.model === settings.ollamaEmbeddingModel) {
    return controlledEmbeddingsCache.vectors;
  }
  const vectors = await callOllamaEmbed(
    settings.ollamaUrl,
    settings.ollamaEmbeddingModel,
    CONTROLLED_PREDICATES as string[]
  );
  controlledEmbeddingsCache = { model: settings.ollamaEmbeddingModel, vectors };
  return vectors;
}

/**
 * Hard predicate enforcement: every predicate that reaches the graph must be
 * a member of CONTROLLED_PREDICATES. A raw predicate that doesn't exactly
 * match is embedded and mapped to the nearest canonical predicate if the
 * cosine similarity clears PREDICATE_SIMILARITY_THRESHOLD; otherwise the
 * whole triple is dropped and logged for review.
 *
 * Batches one embedding call per distinct raw predicate value in the input
 * (not one per triple), so a chunk with five triples that all say "uses"
 * only pays for one embedding lookup.
 */
export interface ExtractionStats {
  triplesDroppedPredicate: number;
}

export function newExtractionStats(): ExtractionStats {
  return { triplesDroppedPredicate: 0 };
}

export async function resolveTriples(
  unresolved: UnresolvedTriple[],
  settings: MemoryGraphSettings,
  stats?: ExtractionStats
): Promise<Triple[]> {
  if (unresolved.length === 0) return [];

  const resolutions = new Map<string, string | null>();
  const toEmbed: string[] = [];
  for (const t of unresolved) {
    if (resolutions.has(t.predicateRaw)) continue;
    const sanitized = sanitizeSnakeCase(t.predicateRaw);
    if (CONTROLLED_PREDICATES.includes(sanitized)) {
      resolutions.set(t.predicateRaw, sanitized);
    } else {
      toEmbed.push(t.predicateRaw);
    }
  }

  if (toEmbed.length > 0) {
    const [controlledVectors, rawVectors] = await Promise.all([
      getControlledPredicateEmbeddings(settings),
      callOllamaEmbed(settings.ollamaUrl, settings.ollamaEmbeddingModel, toEmbed),
    ]);

    toEmbed.forEach((rawPredicate, i) => {
      let best = -Infinity;
      let bestPredicate = "";
      controlledVectors.forEach((vec, j) => {
        const sim = cosineSimilarity(rawVectors[i], vec);
        if (sim > best) {
          best = sim;
          bestPredicate = CONTROLLED_PREDICATES[j];
        }
      });
      if (best >= PREDICATE_SIMILARITY_THRESHOLD) {
        resolutions.set(rawPredicate, bestPredicate);
      } else {
        console.debug(
          `[memory-graph] Dropping triple: predicate "${rawPredicate}" has no controlled match ` +
            `(best "${bestPredicate}" @ ${best.toFixed(2)}, threshold ${PREDICATE_SIMILARITY_THRESHOLD})`
        );
        resolutions.set(rawPredicate, null);
      }
    });
  }

  const triples: Triple[] = [];
  for (const t of unresolved) {
    const predicate = resolutions.get(t.predicateRaw);
    if (!predicate) {
      if (stats) stats.triplesDroppedPredicate++;
      continue;
    }
    triples.push({ ...t, predicate });
  }
  return triples;
}

// Entity names here are capitalized to match how they actually appear in
// the input — that's deliberate, not cosmetic. An earlier version of this
// example used all-lowercase names in the output, and the model latched
// onto that as the required output convention regardless of input casing,
// which quietly lowercased every entity it ever extracted. That was
// invisible while nothing read casing, but it now silently defeats the
// capitalization heuristic in resolve.ts's junk filter (checkJunkEntity),
// which depends on the model's raw output preserving real capitalization.
const FEW_SHOT_INPUT =
  "Priya joined Beacon as tech lead in January and previously worked at Acme Corp " +
  "in Lahore before relocating to Berlin. The team is standardizing on Postgres " +
  "for the analytics service.";

const FEW_SHOT_OUTPUT = `{"relations": [
  {"subject": "Priya", "subject_type": "Person", "predicate": "leads", "object": "Beacon", "object_type": "Project", "confidence": 0.9},
  {"subject": "Priya", "subject_type": "Person", "predicate": "works_at", "object": "Acme Corp", "object_type": "Org", "confidence": 0.8},
  {"subject": "Priya", "subject_type": "Person", "predicate": "lives_in", "object": "Berlin", "object_type": "Place", "confidence": 1.0},
  {"subject": "Beacon", "subject_type": "Project", "predicate": "uses", "object": "Postgres", "object_type": "Concept", "confidence": 0.8}
]}`;

function extractionPrompt(text: string, knownEntities: string[]): string {
  const predicateList = CONTROLLED_PREDICATES.join(", ");
  const knownEntitiesBlock =
    knownEntities.length > 0
      ? `\nKnown entity names already in this vault (if the note refers to one of these,\nreuse the name exactly as written here instead of inventing a variant):\n${knownEntities
          .map((e) => `- ${e}`)
          .join("\n")}\n`
      : "";

  return `You extract structured facts from personal notes.

Read the note text below and return a JSON object of this exact shape:
{"relations": [
  {"subject": "<name>", "subject_type": "<one of Person, Project, Concept, Org, Place, Event>",
   "predicate": "<relation, prefer one from the vocabulary below>",
   "object": "<name>", "object_type": "<one of Person, Project, Concept, Org, Place, Event>",
   "confidence": <float 0-1>}
]}

ENTITIES
Subjects and objects must be named things: a specific person, organization,
place, project, technology, or concept with a proper name — something you
could put on a graph node and reuse across notes. They are never activities,
descriptions, or clauses lifted from the sentence.
- "extraction side" is NOT an entity — it's a fragment of a sentence, not a named thing.
- "postgres for atlas" is NOT an entity — the entity is "postgres"; its relation to atlas
  (e.g. uses) belongs in the predicate, not the entity name.
- Strip filler like "the", "our", "my" and qualifying phrases; keep entity names short and reusable.
${knownEntitiesBlock}
PREDICATES
Prefer one of these exact predicates: ${predicateList}.
Only invent a different predicate if none of these fit, and keep it short snake_case.
The predicate must never contain the object — that's the model packing the object into
the predicate slot instead of leaving it in the "object" field. For example, if the text
says Priya thinks postgres is the right call for Atlas, do NOT emit
predicate "thinks_postgres_is_the_right_call_for" with object "atlas"; emit
predicate "recommends" with object "postgres" instead.

RULES
- Only extract facts explicitly stated or clearly implied in the text.
- confidence reflects how directly the text states the fact (1.0 = explicit, 0.5 = inferred).
- If there are no facts, return {"relations": []}.
- Return ONLY the JSON object, no prose, no markdown fences.

EXAMPLE
Input:
"""
${FEW_SHOT_INPUT}
"""
Output:
${FEW_SHOT_OUTPUT}

Note text:
"""
${text}
"""
`;
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function toTriple(item: unknown): UnresolvedTriple | null {
  if (typeof item !== "object" || item === null) return null;
  const rec = item as Record<string, unknown>;
  if (
    !isNonEmptyString(rec.subject) ||
    !isNonEmptyString(rec.subject_type) ||
    !isNonEmptyString(rec.predicate) ||
    !isNonEmptyString(rec.object) ||
    !isNonEmptyString(rec.object_type) ||
    typeof rec.confidence !== "number" ||
    rec.confidence < 0 ||
    rec.confidence > 1
  ) {
    return null;
  }
  return {
    subject: rec.subject,
    subjectType: rec.subject_type as string,
    predicateRaw: rec.predicate,
    object: rec.object,
    objectType: rec.object_type as string,
    confidence: rec.confidence,
  };
}

/** Malformed items are skipped (logged), not thrown — one bad triple shouldn't
 * discard an entire chunk's extraction. Predicates are not yet resolved
 * against CONTROLLED_PREDICATES here — see resolveTriples. */
export function parseTriples(raw: string): UnresolvedTriple[] {
  if (!raw.trim()) return [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.debug("[memory-graph] LLM returned invalid JSON, skipping chunk:", raw.slice(0, 200));
    return [];
  }

  const TRIPLE_KEYS = ["subject", "subject_type", "predicate", "object", "object_type", "confidence"];
  const looksLikeTriple = (obj: Record<string, unknown>) => TRIPLE_KEYS.every((k) => k in obj);

  let items: unknown[];
  if (Array.isArray(parsed)) {
    // Fallback: bare array, no wrapper — some local models ignore the wrapper instruction.
    items = parsed;
  } else if (parsed && typeof parsed === "object") {
    const rec = parsed as Record<string, unknown>;
    if (Array.isArray(rec.relations)) {
      // Expected shape: {"relations": [...]}.
      items = rec.relations;
    } else if (looksLikeTriple(rec)) {
      // Fallback: model returned a single triple object instead of a wrapped list.
      items = [rec];
    } else if (Object.keys(rec).length === 1 && Array.isArray(Object.values(rec)[0])) {
      // Fallback: model wrapped the array under some other key, e.g. {"triples": [...]}.
      items = Object.values(rec)[0] as unknown[];
    } else {
      console.debug("[memory-graph] LLM JSON was not a list, skipping chunk:", raw.slice(0, 200));
      return [];
    }
  } else {
    console.debug("[memory-graph] LLM JSON was not a list, skipping chunk:", raw.slice(0, 200));
    return [];
  }

  const triples: UnresolvedTriple[] = [];
  for (const item of items) {
    const triple = toTriple(item);
    if (triple) {
      triples.push(triple);
    } else {
      console.debug("[memory-graph] Skipping malformed triple:", item);
    }
  }
  return triples;
}

export async function extractTriples(
  text: string,
  settings: MemoryGraphSettings,
  knownEntities: string[] = [],
  stats?: ExtractionStats
): Promise<Triple[]> {
  if (!text.trim()) return [];
  const raw = await callOllamaChat(
    settings.ollamaUrl,
    settings.ollamaModel,
    extractionPrompt(text, knownEntities)
  );
  const unresolved = parseTriples(raw);
  return resolveTriples(unresolved, settings, stats);
}

function toRelation(triple: Triple, chunk: Chunk): ExtractedRelation {
  return {
    ...triple,
    sourceNote: chunk.notePath,
    noteTitle: chunk.noteTitle,
    validFrom: chunk.mtime,
    lastSeen: chunk.mtime,
  };
}

export async function extractFromChunk(
  chunk: Chunk,
  settings: MemoryGraphSettings,
  knownEntities: string[] = [],
  stats?: ExtractionStats
): Promise<ExtractedRelation[]> {
  const triples = await extractTriples(chunk.text, settings, knownEntities, stats);
  return triples.map((t) => toRelation(t, chunk));
}

export async function extractFromChunks(
  chunks: Chunk[],
  settings: MemoryGraphSettings,
  onProgress?: (done: number, total: number, chunk: Chunk) => void,
  knownEntities: string[] = [],
  stats?: ExtractionStats
): Promise<ExtractedRelation[]> {
  const relations: ExtractedRelation[] = [];
  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    relations.push(...(await extractFromChunk(chunk, settings, knownEntities, stats)));
    onProgress?.(i + 1, chunks.length, chunk);
  }
  return relations;
}
