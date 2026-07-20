import type { Chunk } from "./vault";
import type { MemoryGraphSettings } from "./settings";
import { callOllamaChat } from "./ollama";

export interface Triple {
  subject: string;
  subjectType: string;
  predicate: string;
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

function extractionPrompt(text: string): string {
  return `You extract structured facts from personal notes.

Read the note text below and return a JSON array of relationship triples.
Each triple has this exact shape:
{"subject": "<name>", "subject_type": "<one of Person, Project, Concept, Org, Place, Event>",
  "predicate": "<short snake_case relation, e.g. works_on, lives_in, prefers>",
  "object": "<name>", "object_type": "<one of Person, Project, Concept, Org, Place, Event>",
  "confidence": <float 0-1>}

Rules:
- Only extract facts explicitly stated or clearly implied in the text.
- Use short, consistent snake_case predicates.
- confidence reflects how directly the text states the fact (1.0 = explicit, 0.5 = inferred).
- If there are no facts, return [].
- Return ONLY the JSON array, no prose, no markdown fences.

Note text:
"""
${text}
"""
`;
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function toTriple(item: unknown): Triple | null {
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
    predicate: rec.predicate,
    object: rec.object,
    objectType: rec.object_type as string,
    confidence: rec.confidence,
  };
}

/** Malformed items are skipped (logged), not thrown — one bad triple shouldn't
 * discard an entire chunk's extraction. */
export function parseTriples(raw: string): Triple[] {
  if (!raw.trim()) return [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.warn("[memory-graph] LLM returned invalid JSON, skipping chunk:", raw.slice(0, 200));
    return [];
  }

  const TRIPLE_KEYS = ["subject", "subject_type", "predicate", "object", "object_type", "confidence"];
  const looksLikeTriple = (obj: Record<string, unknown>) => TRIPLE_KEYS.every((k) => k in obj);

  let items: unknown[];
  if (Array.isArray(parsed)) {
    items = parsed;
  } else if (parsed && typeof parsed === "object") {
    const rec = parsed as Record<string, unknown>;
    if (looksLikeTriple(rec)) {
      // Model returned a single triple object instead of a one-item array.
      items = [rec];
    } else if (Object.keys(rec).length === 1 && Array.isArray(Object.values(rec)[0])) {
      // Some models wrap the array in an object like {"triples": [...]}.
      items = Object.values(rec)[0] as unknown[];
    } else {
      console.warn("[memory-graph] LLM JSON was not a list, skipping chunk:", raw.slice(0, 200));
      return [];
    }
  } else {
    console.warn("[memory-graph] LLM JSON was not a list, skipping chunk:", raw.slice(0, 200));
    return [];
  }

  const triples: Triple[] = [];
  for (const item of items) {
    const triple = toTriple(item);
    if (triple) {
      triples.push(triple);
    } else {
      console.warn("[memory-graph] Skipping malformed triple:", item);
    }
  }
  return triples;
}

export async function extractTriples(
  text: string,
  settings: MemoryGraphSettings
): Promise<Triple[]> {
  if (!text.trim()) return [];
  const raw = await callOllamaChat(settings.ollamaUrl, settings.ollamaModel, extractionPrompt(text));
  return parseTriples(raw);
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
  settings: MemoryGraphSettings
): Promise<ExtractedRelation[]> {
  const triples = await extractTriples(chunk.text, settings);
  return triples.map((t) => toRelation(t, chunk));
}

export async function extractFromChunks(
  chunks: Chunk[],
  settings: MemoryGraphSettings,
  onProgress?: (done: number, total: number, chunk: Chunk) => void
): Promise<ExtractedRelation[]> {
  const relations: ExtractedRelation[] = [];
  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    relations.push(...(await extractFromChunk(chunk, settings)));
    onProgress?.(i + 1, chunks.length, chunk);
  }
  return relations;
}
