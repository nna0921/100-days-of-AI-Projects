import { requestUrl } from "obsidian";

/**
 * Calls Ollama's /api/chat via requestUrl() (routes through Electron's main
 * process, not the renderer's fetch) so no CORS/OLLAMA_ORIGINS setup is
 * needed on the host machine.
 */
export async function callOllamaChat(
  ollamaUrl: string,
  model: string,
  prompt: string
): Promise<string> {
  const url = `${ollamaUrl.replace(/\/+$/, "")}/api/chat`;
  const response = await requestUrl({
    url,
    method: "POST",
    contentType: "application/json",
    body: JSON.stringify({
      model,
      messages: [{ role: "user", content: prompt }],
      format: "json",
      stream: false,
      options: { temperature: 0.0 },
    }),
    throw: false,
  });

  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Ollama HTTP ${response.status}: ${response.text.slice(0, 500)}`);
  }

  const content = response.json?.message?.content;
  if (typeof content !== "string") {
    throw new Error(`Unexpected Ollama response shape: ${response.text.slice(0, 200)}`);
  }
  return content;
}

/**
 * Calls Ollama's /api/embed. Accepts one or many inputs in a single request
 * (used to embed the whole controlled-predicate vocabulary in one round trip)
 * and returns one embedding vector per input, in the same order.
 */
export async function callOllamaEmbed(
  ollamaUrl: string,
  model: string,
  input: string | string[]
): Promise<number[][]> {
  const url = `${ollamaUrl.replace(/\/+$/, "")}/api/embed`;
  const response = await requestUrl({
    url,
    method: "POST",
    contentType: "application/json",
    body: JSON.stringify({ model, input }),
    throw: false,
  });

  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Ollama HTTP ${response.status}: ${response.text.slice(0, 500)}`);
  }

  const embeddings = response.json?.embeddings;
  if (!Array.isArray(embeddings)) {
    throw new Error(`Unexpected Ollama embed response shape: ${response.text.slice(0, 200)}`);
  }
  return embeddings;
}
