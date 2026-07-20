import { Notice, Plugin } from "obsidian";
import { DEFAULT_SETTINGS, MemoryGraphSettingTab, MemoryGraphSettings } from "./settings";
import { ingestVault, clearGraphForSettings } from "./ingest";

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
        } else if (p.phase === "writing") {
          notice.setMessage("Memory Graph: writing to graph…");
        }
      });

      notice.setMessage(
        `Memory Graph: ${result.notesChanged}/${result.notesScanned} notes changed, ` +
          `${result.relationsWritten} relations written. Graph now has ` +
          `${result.counts.entities} entities, ${result.counts.notes} notes, ` +
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
}
