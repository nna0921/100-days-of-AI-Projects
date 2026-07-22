import { ItemView, Notice, WorkspaceLeaf, setIcon } from "obsidian";
import type MemoryGraphPlugin from "./main";
import {
  getDriver,
  getCounts,
  getRelationStatusCounts,
  getDisputedGroups,
  getSupersededEntries,
  getPendingMergeSuggestions,
  type DisputedGroup,
  type SupersededEntry,
  type PendingMergeSuggestion,
} from "./graph";
import { MergeSuggestionsModal } from "./mergeModal";

export const VIEW_TYPE_MEMORY_GRAPH = "memory-graph-panel";

interface PanelData {
  entities: number;
  statusCounts: { active: number; superseded: number; disputed: number; rejected: number };
  disputedGroups: DisputedGroup[];
  supersededEntries: SupersededEntry[];
  pendingMerges: PendingMergeSuggestion[];
}

function formatDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "unknown date";
}

/**
 * Sidebar panel for the memory-graph plugin. Reads straight from Neo4j on
 * open and on refresh — nothing here is cached across sessions, so what's
 * shown always reflects the live graph. Renders plain HTML via Obsidian's
 * DOM helpers (createDiv/createSpan/createEl), no external UI library, and
 * relies entirely on Obsidian's CSS custom properties so it matches
 * light/dark and any custom theme automatically.
 */
export class MemoryGraphView extends ItemView {
  private plugin: MemoryGraphPlugin;
  private bodyEl!: HTMLElement;
  private loading = false;

  constructor(leaf: WorkspaceLeaf, plugin: MemoryGraphPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return VIEW_TYPE_MEMORY_GRAPH;
  }

  getDisplayText(): string {
    return "Memory Graph";
  }

  getIcon(): string {
    return "network";
  }

  async onOpen() {
    this.addAction("refresh-cw", "Refresh", () => this.refresh());

    const root = this.contentEl;
    root.empty();
    root.addClass("memory-graph-view");

    root.createEl("h4", { text: "Memory Graph", cls: "memory-graph-title" });
    this.bodyEl = root.createDiv({ cls: "mg-body" });

    await this.refresh();
  }

  async onClose() {
    this.contentEl.empty();
  }

  /** Re-fetches everything from Neo4j and re-renders. Safe to call while a
   * previous refresh is still in flight — a second call just races to set
   * the same loading/rendered state, no queuing needed since this view has
   * no local mutable state that a stale response could corrupt. */
  async refresh() {
    if (this.loading) return;
    this.loading = true;
    this.bodyEl.empty();
    this.bodyEl.createDiv({ cls: "mg-loading", text: "Loading from Neo4j…" });

    try {
      const data = await this.fetchData();
      this.loading = false;
      this.render(data);
    } catch (err) {
      this.loading = false;
      this.renderError(err);
    }

    this.plugin.refreshBadge();
  }

  private async fetchData(): Promise<PanelData> {
    const driver = getDriver(this.plugin.settings);
    try {
      const [counts, statusCounts, disputedGroups, supersededEntries, pendingMerges] = await Promise.all([
        getCounts(driver),
        getRelationStatusCounts(driver),
        getDisputedGroups(driver),
        getSupersededEntries(driver),
        getPendingMergeSuggestions(driver),
      ]);
      return { entities: counts.entities, statusCounts, disputedGroups, supersededEntries, pendingMerges };
    } finally {
      await driver.close();
    }
  }

  private renderError(err: unknown) {
    this.bodyEl.empty();
    const banner = this.bodyEl.createDiv({ cls: "mg-error-banner" });
    banner.createEl("strong", { text: "Couldn't reach Neo4j." });
    banner.createEl("div", {
      cls: "mg-row-muted",
      text: err instanceof Error ? err.message : String(err),
    });
    const retry = banner.createEl("button", { text: "Retry" });
    retry.onclick = () => this.refresh();
  }

  private render(data: PanelData) {
    this.bodyEl.empty();

    const attentionCount = data.statusCounts.disputed + data.pendingMerges.length;
    const summary = this.bodyEl.createDiv({ cls: "mg-summary" });
    if (attentionCount > 0) {
      summary.createSpan({ cls: "mg-badge", text: String(attentionCount) });
      summary.createSpan({ text: ` need${attentionCount === 1 ? "s" : ""} your attention` });
    } else {
      summary.createSpan({ cls: "mg-row-muted", text: "Nothing needs attention right now." });
    }

    this.renderNeedsReview(data.disputedGroups);
    this.renderPendingMerges(data.pendingMerges);
    this.renderRecentlySuperseded(data.supersededEntries);
    this.renderStats(data);
  }

  // --- entity / note linking -------------------------------------------

  /** Opens an entity's generated note if one exists; otherwise tells the
   * user rather than letting Obsidian silently create a blank note for a
   * broken link (entities with only disputed/superseded edges — like a
   * disputed birthplace — never get a generated note, since vault sync only
   * writes one per entity with an active edge). */
  private openEntity(name: string) {
    const dest = this.app.metadataCache.getFirstLinkpathDest(name, "");
    if (!dest) {
      new Notice(`Memory Graph: no generated note for "${name}" yet — run "Sync to vault".`);
      return;
    }
    this.app.workspace.openLinkText(name, "", false);
  }

  private openSourceNote(path: string) {
    const linktext = path.replace(/\.md$/, "");
    const dest = this.app.metadataCache.getFirstLinkpathDest(linktext, "");
    if (!dest) {
      new Notice(`Memory Graph: source note "${path}" not found in this vault.`);
      return;
    }
    this.app.workspace.openLinkText(linktext, "", false);
  }

  private entityLink(container: HTMLElement, name: string): HTMLElement {
    const el = container.createSpan({ cls: "mg-link mg-entity-link", text: name });
    el.onclick = (evt) => {
      evt.stopPropagation();
      this.openEntity(name);
    };
    return el;
  }

  private sourceLink(container: HTMLElement, path: string, title: string | null): HTMLElement {
    const el = container.createSpan({ cls: "mg-link mg-source-link", text: title || path });
    el.onclick = (evt) => {
      evt.stopPropagation();
      this.openSourceNote(path);
    };
    return el;
  }

  // --- collapsible section shell ----------------------------------------

  private renderSection(
    title: string,
    count: number | null,
    defaultOpen: boolean,
    build: (body: HTMLElement) => void
  ): HTMLElement {
    const section = this.bodyEl.createDiv({ cls: "mg-section" });
    if (!defaultOpen) section.addClass("mg-collapsed");

    const header = section.createDiv({ cls: "mg-section-header" });
    const chevron = header.createSpan({ cls: "mg-chevron" });
    setIcon(chevron, "chevron-down");
    header.createSpan({ cls: "mg-section-title", text: title });
    if (count !== null) header.createSpan({ cls: "mg-section-count", text: String(count) });

    const body = section.createDiv({ cls: "mg-section-body" });
    header.onclick = () => section.toggleClass("mg-collapsed", !section.hasClass("mg-collapsed"));

    build(body);
    return section;
  }

  private renderEmpty(body: HTMLElement, text: string) {
    body.createDiv({ cls: "mg-empty", text });
  }

  // --- sections -----------------------------------------------------------

  private renderNeedsReview(groups: DisputedGroup[]) {
    this.renderSection("Needs review", groups.length, true, (body) => {
      if (groups.length === 0) {
        this.renderEmpty(body, "No disputed facts — nothing conflicting right now.");
        return;
      }
      for (const g of groups) {
        const row = body.createDiv({ cls: "mg-row" });

        const headline = row.createDiv({ cls: "mg-row-title" });
        this.entityLink(headline, g.subject);
        headline.createSpan({ text: ` ${g.predicate} ` });
        g.objects.forEach((o, i) => {
          if (i > 0) headline.createSpan({ cls: "mg-row-muted", text: " vs " });
          this.entityLink(headline, o.object);
        });

        const reasoning = g.objects.find((o) => o.reasoning)?.reasoning;
        if (reasoning) {
          row.createDiv({ cls: "mg-row-muted", text: reasoning });
        }

        const sources = row.createDiv({ cls: "mg-row-sources" });
        g.objects.forEach((o, i) => {
          if (i > 0) sources.createSpan({ text: " · " });
          sources.createSpan({ cls: "mg-row-muted", text: `${o.object}: ` });
          this.sourceLink(sources, o.sourceNotePath, o.sourceNoteTitle);
        });
      }
    });
  }

  private renderPendingMerges(suggestions: PendingMergeSuggestion[]) {
    this.renderSection("Pending merges", suggestions.length, true, (body) => {
      if (suggestions.length === 0) {
        this.renderEmpty(body, "No merge suggestions waiting on review.");
        return;
      }
      for (const s of suggestions) {
        const row = body.createDiv({ cls: "mg-row mg-row-clickable" });
        row.setAttr("role", "button");
        row.onclick = () => {
          new MergeSuggestionsModal(this.app, this.plugin, [
            {
              candidateName: s.candidateName,
              candidateType: s.candidateType,
              matchedName: s.matchedName,
              matchedType: s.matchedType,
              matchedAliases: s.matchedAliases,
              tier: s.tier,
              typeMismatch: s.typeMismatch,
              sharedContext: { found: s.sharedContextFound, evidence: s.sharedContextEvidence },
              similarity: s.similarity ?? undefined,
            },
          ], () => this.refresh()).open();
        };

        row.createDiv({
          cls: "mg-row-title",
          text: `"${s.candidateName}" (${s.candidateType})  ⟷  "${s.matchedName}" (${s.matchedType})`,
        });
        row.createDiv({
          cls: "mg-row-muted",
          text: `Match tier: ${s.tier}${s.similarity != null ? ` (similarity ${s.similarity.toFixed(2)})` : ""}`,
        });
        if (s.typeMismatch) {
          row.createDiv({
            cls: "mg-warning",
            text: `⚠ TYPE MISMATCH: ${s.candidateType} ≠ ${s.matchedType} — evidence against merging`,
          });
        }
        row.createDiv({
          cls: "mg-row-muted",
          text: s.sharedContextFound ? `Evidence: ${s.sharedContextEvidence.join("; ")}` : "No shared context found.",
        });
      }
    });
  }

  private renderRecentlySuperseded(entries: SupersededEntry[]) {
    this.renderSection("Recently superseded", entries.length, false, (body) => {
      if (entries.length === 0) {
        this.renderEmpty(body, "Nothing has changed yet — no superseded facts.");
        return;
      }
      for (const e of entries) {
        const row = body.createDiv({ cls: "mg-row" });

        const headline = row.createDiv({ cls: "mg-row-title" });
        this.entityLink(headline, e.subject);
        headline.createSpan({ text: ` was ` });
        this.entityLink(headline, e.object);
        headline.createSpan({ text: ` until ${formatDate(e.untilDate)}, now ` });
        if (e.currentObject) {
          this.entityLink(headline, e.currentObject);
        } else {
          headline.createSpan({ cls: "mg-row-muted", text: "unset" });
        }

        row.createDiv({ cls: "mg-row-muted", text: `via ${e.predicate}` });

        const sources = row.createDiv({ cls: "mg-row-sources" });
        this.sourceLink(sources, e.sourceNotePath, e.sourceNoteTitle);
      }
    });
  }

  private renderStats(data: PanelData) {
    this.renderSection("Stats", null, false, (body) => {
      const stat = (label: string, value: number) => {
        const row = body.createDiv({ cls: "mg-stat-row" });
        row.createSpan({ text: label });
        row.createSpan({ cls: "mg-stat-value", text: String(value) });
      };
      stat("Entities", data.entities);
      stat("Active relations", data.statusCounts.active);
      stat("Superseded", data.statusCounts.superseded);
      stat("Disputed", data.statusCounts.disputed);
      stat("Pending merges", data.pendingMerges.length);
    });
  }
}
