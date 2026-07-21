import { App, Modal, Notice, Plugin } from "obsidian";
import { DEFAULT_SETTINGS, MemoryGraphSettingTab, MemoryGraphSettings } from "./settings";
import {
  ingestVault,
  clearGraphForSettings,
  resolveEntitiesForSettings,
  resolveContradictionsForSettings,
  syncToVaultForSettings,
} from "./ingest";
import { getDriver, mergeEntity } from "./graph";
import type { MergeSuggestion } from "./resolve";

/**
 * Lists merge suggestions that were matched but NOT auto-merged (a type
 * mismatch, or a same-type match with no corroborating evidence) so a
 * human can approve or reject each one. Never auto-merges anything itself
 * — every row requires an explicit click. Both candidate and matched
 * entity already exist as real, separate nodes in the graph by the time
 * this opens (resolution wrote them that way specifically so there's
 * something concrete here to merge or leave alone).
 */
class MergeSuggestionsModal extends Modal {
  constructor(app: App, private settings: MemoryGraphSettings, private suggestions: MergeSuggestion[]) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h2", { text: `Merge suggestions (${this.suggestions.length})` });
    contentEl.createEl("p", {
      text: "Matched, but not auto-merged. Review the evidence and approve or reject each one.",
    });

    for (const s of this.suggestions) {
      const row = contentEl.createDiv();
      row.style.border = "1px solid var(--background-modifier-border)";
      row.style.borderRadius = "6px";
      row.style.padding = "10px";
      row.style.marginBottom = "10px";

      const title = row.createDiv({ text: `"${s.candidateName}" (${s.candidateType})  ⟷  "${s.matchedName}" (${s.matchedType})` });
      title.style.fontWeight = "600";

      row.createDiv({
        text: `Match tier: ${s.tier}${s.similarity !== undefined ? ` (similarity ${s.similarity.toFixed(2)})` : ""}`,
      });

      if (s.typeMismatch) {
        const mismatchEl = row.createDiv({
          text: `⚠ TYPE MISMATCH: ${s.candidateType} ≠ ${s.matchedType} — evidence against merging`,
        });
        mismatchEl.style.color = "var(--text-error)";
        mismatchEl.style.fontWeight = "600";
      }

      row.createDiv({
        text: s.sharedContext.found ? `Evidence: ${s.sharedContext.evidence.join("; ")}` : "No shared context found.",
      });

      const btnRow = row.createDiv();
      btnRow.style.marginTop = "8px";
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      btnRow.style.alignItems = "center";

      const approveBtn = btnRow.createEl("button", { text: "Approve merge" });
      const rejectBtn = btnRow.createEl("button", { text: "Reject" });
      const status = btnRow.createEl("span", { text: "" });
      status.style.fontStyle = "italic";

      approveBtn.onclick = async () => {
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        try {
          const driver = getDriver(this.settings);
          try {
            await mergeEntity(driver, {
              dupName: s.candidateName,
              dupType: s.candidateType,
              canonName: s.matchedName,
              canonType: s.matchedType,
              aliases: Array.from(new Set([...s.matchedAliases, s.candidateName])),
            });
          } finally {
            await driver.close();
          }
          status.setText("Merged.");
        } catch (err) {
          status.setText(`Failed: ${err instanceof Error ? err.message : String(err)}`);
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
        }
      };

      rejectBtn.onclick = () => {
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        status.setText("Rejected — left separate.");
      };
    }
  }

  onClose() {
    this.contentEl.empty();
  }
}

export default class MemoryGraphPlugin extends Plugin {
  settings!: MemoryGraphSettings;

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new MemoryGraphSettingTab(this.app, this));

    this.addCommand({
      id: "ingest-vault",
      name: "Ingest vault",
      callback: () => this.runIngest(),
    });

    this.addCommand({
      id: "clear-graph",
      name: "Clear graph",
      callback: () => this.runClearGraph(),
    });

    this.addCommand({
      id: "resolve-entities",
      name: "Resolve entities",
      callback: () => this.runResolveEntities(),
    });

    this.addCommand({
      id: "resolve-contradictions",
      name: "Resolve contradictions",
      callback: () => this.runResolveContradictions(),
    });

    this.addCommand({
      id: "sync-to-vault",
      name: "Sync to vault",
      callback: () => this.runSyncToVault(),
    });
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async runIngest() {
    const notice = new Notice("Memory Graph: scanning vault…", 0);
    try {
      const result = await ingestVault(this.app, this.settings, (p) => {
        if (p.phase === "scanning") {
          notice.setMessage("Memory Graph: scanning vault…");
        } else if (p.phase === "extracting") {
          notice.setMessage(
            p.chunksTotal
              ? `Memory Graph: extracting ${p.chunksDone}/${p.chunksTotal} chunks ` +
                  `(${p.notesChanged}/${p.notesTotal} notes changed)…`
              : `Memory Graph: ${p.notesChanged}/${p.notesTotal} notes changed, extracting…`
          );
        } else if (p.phase === "resolving") {
          notice.setMessage("Memory Graph: resolving entities…");
        } else if (p.phase === "writing") {
          notice.setMessage("Memory Graph: writing to graph…");
        }
      });

      notice.setMessage(
        `Memory Graph: ${result.notesChanged}/${result.notesScanned} notes changed, ` +
          `${result.relationsWritten} relations written` +
          `${result.relationsDropped ? ` (${result.relationsDropped} dropped as junk)` : ""}` +
          `${result.ambiguousEntities ? `, ${result.ambiguousEntities} ambiguous entities left unmerged` : ""}` +
          `${result.suggestions ? `, ${result.suggestions} merge suggestion(s) — see "Resolve entities"` : ""}. ` +
          `Graph now has ${result.counts.entities} entities, ${result.counts.notes} notes, ` +
          `${result.counts.relations} relations, ${result.counts.mentions} mentions.`
      );
      console.log("[memory-graph] ingest complete", result);
      window.setTimeout(() => notice.hide(), 10000);
    } catch (err) {
      console.error("[memory-graph] ingest failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: ingest failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
  }

  async runClearGraph() {
    try {
      await clearGraphForSettings(this.settings);
      new Notice("Memory Graph: graph cleared.");
    } catch (err) {
      console.error("[memory-graph] clear graph failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      new Notice(`Memory Graph: clear failed — ${detail}`, 15000);
    }
  }

  async runResolveEntities() {
    const notice = new Notice("Memory Graph: resolving entities…", 0);
    try {
      const result = await resolveEntitiesForSettings(this.settings);
      notice.setMessage(
        `Memory Graph: ${result.entitiesBefore} → ${result.entitiesAfter} entities ` +
          `(${result.merges.length} merged, ${result.deletedJunk.length} junk deleted, ` +
          `${result.ambiguous.length} ambiguous left unmerged, ${result.suggestions.length} suggestions).`
      );
      console.log("[memory-graph] resolve entities complete", result);
      window.setTimeout(() => notice.hide(), 10000);
      if (result.suggestions.length > 0) {
        new MergeSuggestionsModal(this.app, this.settings, result.suggestions).open();
      }
    } catch (err) {
      console.error("[memory-graph] resolve entities failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: resolve entities failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
  }

  async runResolveContradictions() {
    const notice = new Notice("Memory Graph: checking for contradictions…", 0);
    try {
      const result = await resolveContradictionsForSettings(this.app, this.settings);
      const byClass = { CHANGE: 0, CONFLICT: 0, ERROR: 0 };
      for (const o of result.outcomes) byClass[o.classification]++;
      notice.setMessage(
        `Memory Graph: ${result.candidatesFound} candidate(s) found — ` +
          `${byClass.CHANGE} change, ${byClass.CONFLICT} conflict, ${byClass.ERROR} error` +
          `${result.unparsedSkipped ? `, ${result.unparsedSkipped} unparsed/skipped` : ""}.`
      );
      console.log("[memory-graph] resolve contradictions complete", result);
      window.setTimeout(() => notice.hide(), 10000);
    } catch (err) {
      console.error("[memory-graph] resolve contradictions failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: resolve contradictions failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
  }

  async runSyncToVault() {
    const notice = new Notice("Memory Graph: syncing to vault…", 0);
    try {
      const result = await syncToVaultForSettings(this.app, this.settings);
      if (result.excludedFolderAdded) {
        await this.saveSettings();
      }
      notice.setMessage(
        `Memory Graph: wrote ${result.written} notes to ${result.folder} ` +
          `(${result.skippedNoActiveEdges} entities skipped — no active edges)` +
          `${result.excludedFolderAdded ? `. Added "${result.folder.replace(/\/$/, "")}" to excluded folders.` : ". Sync folder already excluded."}` +
          ` Excluded folders: [${result.excludedFolders.join(", ")}].`
      );
      console.log("[memory-graph] sync to vault complete", result);
      window.setTimeout(() => notice.hide(), 10000);
    } catch (err) {
      console.error("[memory-graph] sync to vault failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: sync to vault failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
  }
}
