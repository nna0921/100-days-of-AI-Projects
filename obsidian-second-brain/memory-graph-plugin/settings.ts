import { App, PluginSettingTab, Setting } from "obsidian";
import type MemoryGraphPlugin from "./main";

export interface MemoryGraphSettings {
  neo4jUri: string;
  neo4jUser: string;
  neo4jPassword: string;
  ollamaUrl: string;
  ollamaModel: string;
  ollamaEmbeddingModel: string;
  excludedFolders: string[];
  syncFolder: string;
}

export const DEFAULT_SETTINGS: MemoryGraphSettings = {
  neo4jUri: "bolt://localhost:7687",
  neo4jUser: "neo4j",
  neo4jPassword: "",
  ollamaUrl: "http://localhost:11434",
  ollamaModel: "llama3.1:8b",
  ollamaEmbeddingModel: "nomic-embed-text",
  excludedFolders: [],
  syncFolder: "Memory Graph/",
};

export class MemoryGraphSettingTab extends PluginSettingTab {
  plugin: MemoryGraphPlugin;

  constructor(app: App, plugin: MemoryGraphPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl("h2", { text: "Memory Graph" });

    containerEl.createEl("h3", { text: "Neo4j" });

    new Setting(containerEl)
      .setName("Neo4j URI")
      .setDesc("Bolt connection URI, e.g. bolt://localhost:7687")
      .addText((text) =>
        text
          .setPlaceholder("bolt://localhost:7687")
          .setValue(this.plugin.settings.neo4jUri)
          .onChange(async (value) => {
            this.plugin.settings.neo4jUri = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Neo4j user")
      .addText((text) =>
        text.setValue(this.plugin.settings.neo4jUser).onChange(async (value) => {
          this.plugin.settings.neo4jUser = value.trim();
          await this.plugin.saveSettings();
        })
      );

    new Setting(containerEl)
      .setName("Neo4j password")
      .setDesc("Stored in this plugin's data.json inside your vault, in plain text.")
      .addText((text) => {
        text.inputEl.type = "password";
        text.setValue(this.plugin.settings.neo4jPassword).onChange(async (value) => {
          this.plugin.settings.neo4jPassword = value;
          await this.plugin.saveSettings();
        });
      });

    containerEl.createEl("h3", { text: "Ollama" });

    new Setting(containerEl)
      .setName("Ollama URL")
      .setDesc("Base URL, e.g. http://localhost:11434")
      .addText((text) =>
        text
          .setPlaceholder("http://localhost:11434")
          .setValue(this.plugin.settings.ollamaUrl)
          .onChange(async (value) => {
            this.plugin.settings.ollamaUrl = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Ollama model")
      .addText((text) =>
        text
          .setPlaceholder("llama3.1:8b")
          .setValue(this.plugin.settings.ollamaModel)
          .onChange(async (value) => {
            this.plugin.settings.ollamaModel = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Ollama embedding model")
      .setDesc("Used to map predicates the extraction model invents onto the controlled vocabulary.")
      .addText((text) =>
        text
          .setPlaceholder("nomic-embed-text")
          .setValue(this.plugin.settings.ollamaEmbeddingModel)
          .onChange(async (value) => {
            this.plugin.settings.ollamaEmbeddingModel = value.trim();
            await this.plugin.saveSettings();
          })
      );

    containerEl.createEl("h3", { text: "Ingestion" });

    new Setting(containerEl)
      .setName("Excluded folders")
      .setDesc("One folder path per line, relative to vault root. Notes under these are skipped.")
      .addTextArea((text) => {
        text
          .setPlaceholder("templates\narchive/old")
          .setValue(this.plugin.settings.excludedFolders.join("\n"))
          .onChange(async (value) => {
            this.plugin.settings.excludedFolders = value
              .split("\n")
              .map((s) => s.trim())
              .filter((s) => s.length > 0);
            await this.plugin.saveSettings();
          });
        text.inputEl.rows = 4;
      });

    containerEl.createEl("h3", { text: "Vault sync" });

    new Setting(containerEl)
      .setName("Sync folder")
      .setDesc(
        "Where 'Sync to vault' writes one generated note per entity. Fully regenerated on every " +
          "sync, so treat it as disposable — automatically added to excluded folders so the plugin " +
          "never ingests its own generated notes."
      )
      .addText((text) =>
        text
          .setPlaceholder("Memory Graph/")
          .setValue(this.plugin.settings.syncFolder)
          .onChange(async (value) => {
            this.plugin.settings.syncFolder = value.trim();
            await this.plugin.saveSettings();
          })
      );
  }
}
