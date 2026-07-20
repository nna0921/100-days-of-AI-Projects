import { App, TFile } from "obsidian";

export interface Note {
  path: string;
  title: string;
  mtime: number; // epoch ms, from TFile.stat.mtime
  body: string; // frontmatter stripped
}

export interface Chunk {
  notePath: string;
  noteTitle: string;
  mtime: number;
  heading: string;
  text: string;
}

// Rough chunk budget: ~600 tokens ≈ ~450 words.
const CHUNK_WORD_BUDGET = 450;
const HEADING_LINE_RE = /^(#{1,6})\s+(.*)$/gm;

// Matches [[target]], [[target#heading]], [[target|alias]], and the ![[...]]
// embed form. Captures: 1=target, 2=optional #heading, 3=optional alias.
const WIKILINK_RE = /!?\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]+))?\]\]/g;

function basename(linkTarget: string): string {
  const idx = linkTarget.lastIndexOf("/");
  return idx === -1 ? linkTarget : linkTarget.slice(idx + 1);
}

/** Replaces wikilink/embed syntax with its display text, so entities read
 * from prose (e.g. "Anna") match entities read from links (e.g. "[[Anna]]")
 * instead of ending up as separate nodes with literal brackets in the name. */
export function stripWikilinks(text: string): string {
  return text.replace(WIKILINK_RE, (_match, target: string, _heading, alias?: string) => {
    return (alias ?? basename(target)).trim();
  });
}

export function isExcluded(path: string, excludedFolders: string[]): boolean {
  return excludedFolders.some((folder) => {
    const normalized = folder.replace(/^\/+|\/+$/g, "");
    if (!normalized) return false;
    return path === normalized || path.startsWith(normalized + "/");
  });
}

function stripFrontmatter(app: App, file: TFile, raw: string): string {
  const fmPos = app.metadataCache.getFileCache(file)?.frontmatterPosition;
  if (!fmPos) return raw;
  return raw.slice(fmPos.end.offset).replace(/^\r?\n/, "");
}

function titleFor(app: App, file: TFile): string {
  const headings = app.metadataCache.getFileCache(file)?.headings;
  const firstH1 = headings?.find((h) => h.level === 1);
  const title = firstH1 ? firstH1.heading.trim() : file.basename;
  return stripWikilinks(title);
}

export async function loadNotes(app: App, excludedFolders: string[]): Promise<Note[]> {
  const files = app.vault
    .getMarkdownFiles()
    .filter((f) => !isExcluded(f.path, excludedFolders))
    .sort((a, b) => a.path.localeCompare(b.path));

  const notes: Note[] = [];
  for (const file of files) {
    const raw = await app.vault.cachedRead(file);
    const body = stripWikilinks(stripFrontmatter(app, file, raw));
    notes.push({
      path: file.path,
      title: titleFor(app, file),
      mtime: file.stat.mtime,
      body,
    });
  }
  return notes;
}

/** Returns [heading, sectionText][]. Text before the first heading gets heading ''. */
function splitByHeading(body: string): Array<[string, string]> {
  const matches = [...body.matchAll(HEADING_LINE_RE)];
  if (matches.length === 0) {
    const trimmed = body.trim();
    return trimmed ? [["", trimmed]] : [];
  }

  const sections: Array<[string, string]> = [];
  const firstStart = matches[0].index ?? 0;
  const preamble = body.slice(0, firstStart).trim();
  if (preamble) sections.push(["", preamble]);

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const headingText = match[2].trim();
    const start = (match.index ?? 0) + match[0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index ?? body.length : body.length;
    const sectionText = body.slice(start, end).trim();
    if (sectionText) sections.push([headingText, sectionText]);
  }
  return sections;
}

function splitByWords(text: string, budget: number): string[] {
  const paragraphs = text.split("\n\n").filter((p) => p.trim().length > 0);
  const chunks: string[] = [];
  let current: string[] = [];
  let currentWords = 0;

  for (const para of paragraphs) {
    const paraWords = para.split(/\s+/).filter(Boolean).length;
    if (current.length > 0 && currentWords + paraWords > budget) {
      chunks.push(current.join("\n\n"));
      current = [];
      currentWords = 0;
    }
    current.push(para);
    currentWords += paraWords;
  }
  if (current.length > 0) chunks.push(current.join("\n\n"));
  return chunks.length > 0 ? chunks : [text];
}

export function chunkNote(note: Note): Chunk[] {
  const chunks: Chunk[] = [];
  for (const [heading, sectionText] of splitByHeading(note.body)) {
    for (const piece of splitByWords(sectionText, CHUNK_WORD_BUDGET)) {
      chunks.push({
        notePath: note.path,
        noteTitle: note.title,
        mtime: note.mtime,
        heading,
        text: piece,
      });
    }
  }
  return chunks;
}

export async function loadAndChunkVault(app: App, excludedFolders: string[]): Promise<Chunk[]> {
  const notes = await loadNotes(app, excludedFolders);
  const chunks: Chunk[] = [];
  for (const note of notes) {
    chunks.push(...chunkNote(note));
  }
  return chunks;
}
