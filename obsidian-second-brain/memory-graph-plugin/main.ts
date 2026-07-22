import { Notice, Plugin } from "obsidian";
import { DEFAULT_SETTINGS, MemoryGraphSettingTab, MemoryGraphSettings } from "./settings";
import {
  ingestVault,
  clearGraphForSettings,
  resolveEntitiesForSettings,
  resolveContradictionsForSettings,
  syncToVaultForSettings,
} from "./ingest";
import { getDriver, getRelationStatusCounts, getPendingMergeSuggestionCount } from "./graph";
import { MergeSuggestionsModal } from "./mergeModal";
import { MemoryGraphView, VIEW_TYPE_MEMORY_GRAPH } from "./view";

export default class MemoryGraphPlugin extends Plugin {
  settings!: MemoryGraphSettings;
  private ribbonIconEl?: HTMLElement;
  private ribbonBadgeEl?: HTMLElement;

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new MemoryGraphSettingTab(this.app, this));

    this.registerView(VIEW_TYPE_MEMORY_GRAPH, (leaf) => new MemoryGraphView(leaf, this));

    this.ribbonIconEl = this.addRibbonIcon("network", "Open Memory Graph panel", () => this.activateView());
    this.ribbonBadgeEl = this.ribbonIconEl.createSpan({ cls: "memory-graph-ribbon-badge" });
    this.ribbonBadgeEl.hide();

    this.addCommand({
      id: "open-memory-graph-panel",
      name: "Open Memory Graph panel",
      callback: () => this.activateView(),
    });

    this.addCommand({
      id: "update-everything",
      name: "Update everything (ingest, resolve, sync)",
      callback: () => this.runFullPipeline(),
    });

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

    // Best-effort: Neo4j may not be up yet when Obsidian starts. A failed
    // badge refresh here just leaves the badge hidden — the panel itself
    // shows the real error state when the user opens it.
    this.refreshBadge();
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  /** Opens the Memory Graph panel in the right sidebar, reusing an existing
   * leaf if one is already open rather than spawning duplicates. */
  async activateView() {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE_MEMORY_GRAPH)[0];
    if (!leaf) {
      leaf = workspace.getRightLeaf(false) ?? workspace.getLeaf(true);
      await leaf.setViewState({ type: VIEW_TYPE_MEMORY_GRAPH, active: true });
    }
    workspace.revealLeaf(leaf);
  }

  /** Sets the ribbon icon's badge to disputed + pending-merge count — the
   * "you have things to review" signal. Hides the badge on zero or on
   * failure (Neo4j unreachable), since a stale/wrong count is worse than no
   * badge. Called on load and after any command that can change these
   * counts; the panel also calls this after its own refresh. */
  async refreshBadge() {
    if (!this.ribbonBadgeEl) return;
    try {
      const driver = getDriver(this.settings);
      let disputed: number;
      let pendingMerges: number;
      try {
        [disputed, pendingMerges] = await Promise.all([
          getRelationStatusCounts(driver).then((c) => c.disputed),
          getPendingMergeSuggestionCount(driver),
        ]);
      } finally {
        await driver.close();
      }
      const total = disputed + pendingMerges;
      if (total > 0) {
        this.ribbonBadgeEl.setText(total > 99 ? "99+" : String(total));
        this.ribbonBadgeEl.show();
      } else {
        this.ribbonBadgeEl.hide();
      }
    } catch {
      this.ribbonBadgeEl.hide();
    }
  }

  /** Chains all four steps in the order they need to run — ingest, then
   * resolve entities (so contradiction detection sees post-merge active
   * edges), then resolve contradictions, then sync to vault — under one
   * notice instead of four separate manual command invocations. Runs the
   * same underlying *ForSettings functions the individual commands use, so
   * behavior (incremental ingest, merge-suggestion persistence, etc.) is
   * identical either way. */
  async runFullPipeline() {
    const notice = new Notice("Memory Graph: updating — scanning vault…", 0);
    try {
      const ingestResult = await ingestVault(this.app, this.settings, (p) => {
        if (p.phase === "scanning") {
          notice.setMessage("Memory Graph: updating — scanning vault…");
        } else if (p.phase === "extracting") {
          notice.setMessage(
            p.chunksTotal
              ? `Memory Graph: updating — extracting ${p.chunksDone}/${p.chunksTotal} chunks…`
              : `Memory Graph: updating — ${p.notesChanged}/${p.notesTotal} notes changed, extracting…`
          );
        } else if (p.phase === "resolving") {
          notice.setMessage("Memory Graph: updating — resolving entities…");
        } else if (p.phase === "writing") {
          notice.setMessage("Memory Graph: updating — writing to graph…");
        }
      });

      notice.setMessage("Memory Graph: updating — resolving entities across the graph…");
      const resolveResult = await resolveEntitiesForSettings(this.settings);

      notice.setMessage("Memory Graph: updating — checking for contradictions…");
      const contradictionResult = await resolveContradictionsForSettings(this.app, this.settings);

      notice.setMessage("Memory Graph: updating — syncing to vault…");
      const syncResult = await syncToVaultForSettings(this.app, this.settings);
      if (syncResult.excludedFolderAdded) {
        await this.saveSettings();
      }

      const byClass = { CHANGE: 0, CONFLICT: 0, ERROR: 0 };
      for (const o of contradictionResult.outcomes) byClass[o.classification]++;

      notice.setMessage(
        `Memory Graph: updated. ${ingestResult.notesChanged}/${ingestResult.notesScanned} notes changed, ` +
          `${ingestResult.relationsWritten} relations written, ${resolveResult.merges.length} entities auto-merged, ` +
          `${resolveResult.suggestions.length} pending merge suggestion(s), ${byClass.CHANGE} change/` +
          `${byClass.CONFLICT} conflict/${byClass.ERROR} error resolved, ${syncResult.written} notes synced.`
      );
      console.log("[memory-graph] full pipeline complete", { ingestResult, resolveResult, contradictionResult, syncResult });
      window.setTimeout(() => notice.hide(), 12000);

      this.refreshBadge();
      this.refreshOpenView();

      if (resolveResult.suggestions.length > 0) {
        new MergeSuggestionsModal(this.app, this, resolveResult.suggestions, () => {
          this.refreshBadge();
          this.refreshOpenView();
        }).open();
      }
    } catch (err) {
      console.error("[memory-graph] full pipeline failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: update failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
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
          `${result.relationsWritten} relations written ` +
          `(${result.relationsControlled} controlled, ${result.relationsUncontrolled} uncontrolled)` +
          `${result.relationsDropped ? `, ${result.relationsDropped} dropped as junk` : ""}` +
          `${result.ambiguousEntities ? `, ${result.ambiguousEntities} ambiguous entities left unmerged` : ""}` +
          `${result.suggestions ? `, ${result.suggestions} merge suggestion(s) — see "Resolve entities"` : ""}. ` +
          `Graph now has ${result.counts.entities} entities, ${result.counts.notes} notes, ` +
          `${result.counts.relations} relations, ${result.counts.mentions} mentions.`
      );
      console.log("[memory-graph] ingest complete", result);
      window.setTimeout(() => notice.hide(), 10000);
      this.refreshBadge();
      this.refreshOpenView();
    } catch (err) {
      console.error("[memory-graph] ingest failed:", err);
      const detail = err instanceof Error ? err.message : String(err);
      notice.setMessage(`Memory Graph: ingest failed — ${detail}`);
      window.setTimeout(() => notice.hide(), 15000);
    }
  }

  /** Refreshes an already-open panel leaf, if any, so its sections reflect
   * a command that just ran (ingest, resolve entities, resolve
   * contradictions) without requiring the user to click the panel's own
   * refresh button. */
  refreshOpenView() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_MEMORY_GRAPH)) {
      if (leaf.view instanceof MemoryGraphView) leaf.view.refresh();
    }
  }

  async runClearGraph() {
    try {
      await clearGraphForSettings(this.settings);
      new Notice("Memory Graph: graph cleared.");
      this.refreshBadge();
      this.refreshOpenView();
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
      this.refreshBadge();
      this.refreshOpenView();
      if (result.suggestions.length > 0) {
        new MergeSuggestionsModal(this.app, this, result.suggestions, () => {
          this.refreshBadge();
          this.refreshOpenView();
        }).open();
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
      this.refreshBadge();
      this.refreshOpenView();
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
