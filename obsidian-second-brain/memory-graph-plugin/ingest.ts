import { createHash } from "crypto";
import type { App } from "obsidian";

import type { MemoryGraphSettings } from "./settings";
import { loadNotes, chunkNote } from "./vault";
import { extractFromChunks, newExtractionStats } from "./extract";
import {
  clearGraph,
  ensureConstraints,
  getCounts,
  getDriver,
  getNoteHashes,
  upsertNote,
  upsertRelations,
  type GraphCounts,
} from "./graph";
import { resolveRelationEntities, resolveExistingGraph, type ResolveGraphResult } from "./resolve";
import { resolveContradictions, type ContradictionResult } from "./contradictions";
import { syncToVault, type SyncResult } from "./vaultSync";

function hashContent(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export interface IngestProgress {
  phase: "scanning" | "extracting" | "resolving" | "writing";
  notesTotal?: number;
  notesChanged?: number;
  chunksDone?: number;
  chunksTotal?: number;
}

export interface IngestResult {
  notesScanned: number;
  notesChanged: number;
  relationsWritten: number;
  relationsDropped: number; // referenced a junk entity, post entity-resolution
  ambiguousEntities: number;
  suggestions: number; // merge suggestions left for review — see "Resolve entities"
  counts: GraphCounts;
}

export async function ingestVault(
  app: App,
  settings: MemoryGraphSettings,
  onProgress?: (p: IngestProgress) => void
): Promise<IngestResult> {
  const driver = getDriver(settings);
  try {
    await ensureConstraints(driver);

    onProgress?.({ phase: "scanning" });
    const notes = await loadNotes(app, settings.excludedFolders);
    const withHashes = notes.map((note) => ({ note, hash: hashContent(note.body) }));

    const existingHashes = await getNoteHashes(driver, notes.map((n) => n.path));
    const changed = withHashes.filter(({ note, hash }) => existingHashes.get(note.path) !== hash);

    onProgress?.({ phase: "extracting", notesTotal: notes.length, notesChanged: changed.length });

    const knownEntities = Array.from(new Set(notes.map((note) => note.title).filter(Boolean)));

    const chunks = changed.flatMap(({ note }) => chunkNote(note));
    const extractionStats = newExtractionStats();
    const relations = await extractFromChunks(
      chunks,
      settings,
      (done, total) => {
        onProgress?.({
          phase: "extracting",
          notesTotal: notes.length,
          notesChanged: changed.length,
          chunksDone: done,
          chunksTotal: total,
        });
      },
      knownEntities,
      extractionStats
    );

    onProgress?.({ phase: "resolving" });
    const { relations: resolvedRelations, droppedRelations, ambiguous, junk, suggestions } = await resolveRelationEntities(
      driver,
      relations,
      settings
    );
    // Per-item detail goes to debug (visible with devtools' log level turned
    // up, invisible by default) — the one summary line below is what
    // actually gets read after every run.
    for (const j of junk) {
      console.debug(`[memory-graph] Dropping junk entity "${j.raw}" (${j.type}): ${j.reason}`);
    }
    for (const a of ambiguous) {
      console.debug(
        `[memory-graph] Ambiguous entity "${a.candidate}" (${a.type}) matched multiple existing ` +
          `entities via ${a.tier}: ${a.matchedCandidates.join(", ")} — left unmerged`
      );
    }
    for (const s of suggestions) {
      console.debug(
        `[memory-graph] Merge suggestion (not auto-merged): "${s.candidateName}" (${s.candidateType}) ` +
          `~ "${s.matchedName}" (${s.matchedType}) via ${s.tier}` +
          `${s.typeMismatch ? " — TYPE MISMATCH" : ""}` +
          `${s.sharedContext.found ? `; evidence: ${s.sharedContext.evidence.join("; ")}` : "; no shared context found"}` +
          ` — run "Resolve entities" to review it.`
      );
    }
    console.log(
      `[memory-graph] dropped ${extractionStats.triplesDroppedPredicate} triples (uncontrolled predicate), ` +
        `${junk.length} junk entities, ${suggestions.length} merge suggestions pending review` +
        `${ambiguous.length ? `, ${ambiguous.length} ambiguous entities left unmerged` : ""}.`
    );

    onProgress?.({ phase: "writing" });
    await upsertRelations(driver, resolvedRelations);

    const ingestedAt = new Date().toISOString();
    for (const { note, hash } of changed) {
      await upsertNote(driver, { path: note.path, title: note.title, contentHash: hash, ingestedAt });
    }

    const counts = await getCounts(driver);

    return {
      notesScanned: notes.length,
      notesChanged: changed.length,
      relationsWritten: resolvedRelations.length,
      relationsDropped: droppedRelations.length,
      ambiguousEntities: ambiguous.length,
      suggestions: suggestions.length,
      counts,
    };
  } finally {
    await driver.close();
  }
}

export async function clearGraphForSettings(settings: MemoryGraphSettings): Promise<void> {
  const driver = getDriver(settings);
  try {
    await clearGraph(driver);
  } finally {
    await driver.close();
  }
}

export async function resolveEntitiesForSettings(settings: MemoryGraphSettings): Promise<ResolveGraphResult> {
  const driver = getDriver(settings);
  try {
    return await resolveExistingGraph(driver, settings);
  } finally {
    await driver.close();
  }
}

export async function resolveContradictionsForSettings(
  app: App,
  settings: MemoryGraphSettings
): Promise<ContradictionResult> {
  const driver = getDriver(settings);
  try {
    return await resolveContradictions(app, driver, settings);
  } finally {
    await driver.close();
  }
}

export async function syncToVaultForSettings(app: App, settings: MemoryGraphSettings): Promise<SyncResult> {
  const driver = getDriver(settings);
  try {
    return await syncToVault(app, driver, settings);
  } finally {
    await driver.close();
  }
}
