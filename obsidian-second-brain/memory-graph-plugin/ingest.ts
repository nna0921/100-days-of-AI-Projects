import { createHash } from "crypto";
import type { App } from "obsidian";

import type { MemoryGraphSettings } from "./settings";
import { loadNotes, chunkNote } from "./vault";
import { extractFromChunks } from "./extract";
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

function hashContent(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export interface IngestProgress {
  phase: "scanning" | "extracting" | "writing";
  notesTotal?: number;
  notesChanged?: number;
  chunksDone?: number;
  chunksTotal?: number;
}

export interface IngestResult {
  notesScanned: number;
  notesChanged: number;
  relationsWritten: number;
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

    const chunks = changed.flatMap(({ note }) => chunkNote(note));
    const relations = await extractFromChunks(chunks, settings, (done, total) => {
      onProgress?.({
        phase: "extracting",
        notesTotal: notes.length,
        notesChanged: changed.length,
        chunksDone: done,
        chunksTotal: total,
      });
    });

    onProgress?.({ phase: "writing" });
    await upsertRelations(driver, relations);

    const ingestedAt = new Date().toISOString();
    for (const { note, hash } of changed) {
      await upsertNote(driver, { path: note.path, title: note.title, contentHash: hash, ingestedAt });
    }

    const counts = await getCounts(driver);

    return {
      notesScanned: notes.length,
      notesChanged: changed.length,
      relationsWritten: relations.length,
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
