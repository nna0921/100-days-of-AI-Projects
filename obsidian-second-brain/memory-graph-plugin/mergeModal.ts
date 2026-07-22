import { App, Modal } from "obsidian";
import type { MemoryGraphSettings } from "./settings";
import { getDriver, mergeEntity, deleteMergeSuggestion, deleteMergeSuggestionsReferencing } from "./graph";
import { syncToVaultForSettings } from "./ingest";
import type { MergeSuggestion } from "./resolve";

/** Structurally matches MemoryGraphPlugin (settings + saveSettings) without
 * importing it — main.ts already imports this file, so importing the
 * plugin's class back here would be circular. */
interface SettingsHost {
  settings: MemoryGraphSettings;
  saveSettings(): Promise<void>;
}

/**
 * Lists merge suggestions that were matched but NOT auto-merged (a type
 * mismatch, or a same-type match with no corroborating evidence) so a
 * human can approve or reject each one. Never auto-merges anything itself
 * — every row requires an explicit click. Both candidate and matched
 * entity already exist as real, separate nodes in the graph by the time
 * this opens (resolution wrote them that way specifically so there's
 * something concrete here to merge or leave alone).
 *
 * Lives in its own file (not main.ts) so both main.ts and view.ts can
 * import it without a circular dependency.
 */
export class MergeSuggestionsModal extends Modal {
  constructor(
    app: App,
    private host: SettingsHost,
    private suggestions: MergeSuggestion[],
    private onResolved?: () => void
  ) {
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
          const driver = getDriver(this.host.settings);
          try {
            await mergeEntity(driver, {
              dupName: s.candidateName,
              dupType: s.candidateType,
              canonName: s.matchedName,
              canonType: s.matchedType,
              aliases: Array.from(new Set([...s.matchedAliases, s.candidateName])),
            });
            // The exact pair is gone either way, but the duplicate name
            // (s.candidateName) may also be named in OTHER pending
            // suggestions from a different pass — those are stale now too.
            await deleteMergeSuggestionsReferencing(driver, { name: s.candidateName, type: s.candidateType });
          } finally {
            await driver.close();
          }
          status.setText("Merged. Syncing to vault…");

          // Regenerate the vault's entity notes right away so the merge is
          // visible immediately — both in the generated Memory Graph notes
          // and in Obsidian's own Graph view — instead of looking unchanged
          // until a separate manual "Sync to vault" run.
          try {
            const syncResult = await syncToVaultForSettings(this.app, this.host.settings);
            if (syncResult.excludedFolderAdded) {
              await this.host.saveSettings();
            }
            status.setText("Merged and synced to vault.");
          } catch (syncErr) {
            status.setText(
              `Merged, but sync to vault failed: ${syncErr instanceof Error ? syncErr.message : String(syncErr)}`
            );
          }

          this.onResolved?.();
        } catch (err) {
          status.setText(`Failed: ${err instanceof Error ? err.message : String(err)}`);
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
        }
      };

      rejectBtn.onclick = async () => {
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        try {
          const driver = getDriver(this.host.settings);
          try {
            await deleteMergeSuggestion(driver, {
              candidateName: s.candidateName,
              candidateType: s.candidateType,
              matchedName: s.matchedName,
              matchedType: s.matchedType,
            });
          } finally {
            await driver.close();
          }
          status.setText("Rejected — left separate.");
          this.onResolved?.();
        } catch (err) {
          status.setText(`Failed: ${err instanceof Error ? err.message : String(err)}`);
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
        }
      };
    }
  }

  onClose() {
    this.contentEl.empty();
  }
}
