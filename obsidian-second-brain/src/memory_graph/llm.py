"""Single interface for triple extraction: extract_triples(text) -> list[Triple].

Swapping LLM_BACKEND in .env (ollama -> api) is a one-line config change;
callers never touch the backend directly.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from memory_graph.config import get_settings

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("Person", "Project", "Concept", "Org", "Place", "Event")

EXTRACTION_PROMPT = """You extract structured facts from personal notes.

Read the note text below and return a JSON array of relationship triples.
Each triple has this exact shape:
{{"subject": "<name>", "subject_type": "<one of Person, Project, Concept, Org, Place, Event>",
  "predicate": "<short snake_case relation, e.g. works_on, lives_in, prefers>",
  "object": "<name>", "object_type": "<one of Person, Project, Concept, Org, Place, Event>",
  "confidence": <float 0-1>}}

Rules:
- Only extract facts explicitly stated or clearly implied in the text.
- Use short, consistent snake_case predicates.
- confidence reflects how directly the text states the fact (1.0 = explicit, 0.5 = inferred).
- If there are no facts, return [].
- Return ONLY the JSON array, no prose, no markdown fences.

Note text:
\"\"\"
{text}
\"\"\"
"""


class Triple(BaseModel):
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    confidence: float = Field(ge=0.0, le=1.0)


class LLMBackend:
    def generate_json(self, prompt: str) -> str:
        raise NotImplementedError


class OllamaBackend(LLMBackend):
    def __init__(self, model: str, host: str):
        import ollama

        self._client = ollama.Client(host=host)
        self._model = model

    def generate_json(self, prompt: str) -> str:
        response = self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.0},
        )
        return response["message"]["content"]


class ApiBackend(LLMBackend):
    """Stub for a hosted API backend (Anthropic/OpenAI/etc).

    Kept behind the same interface as OllamaBackend so switching
    LLM_BACKEND=api in .env is the only change needed once implemented.
    """

    def __init__(self, api_key: str | None, model: str | None):
        if not api_key:
            raise RuntimeError(
                "LLM_BACKEND=api requires API_KEY to be set in .env"
            )
        self._api_key = api_key
        self._model = model

    def generate_json(self, prompt: str) -> str:
        raise NotImplementedError(
            "ApiBackend is a stub. Implement a call to your hosted provider "
            "here (e.g. Anthropic Messages API) and return the raw JSON text."
        )


def _get_backend() -> LLMBackend:
    settings = get_settings()
    if settings.llm_backend == "ollama":
        return OllamaBackend(model=settings.ollama_model, host=settings.ollama_host)
    if settings.llm_backend == "api":
        return ApiBackend(api_key=settings.api_key, model=settings.api_model)
    raise ValueError(f"Unknown LLM_BACKEND: {settings.llm_backend!r}")


def extract_triples(text: str, backend: LLMBackend | None = None) -> list[Triple]:
    """Extract entity/relationship triples from a chunk of note text.

    Malformed items are skipped rather than raising, so one bad triple
    doesn't discard an entire chunk's extraction.
    """
    if not text.strip():
        return []

    backend = backend or _get_backend()
    prompt = EXTRACTION_PROMPT.format(text=text)
    raw = backend.generate_json(prompt)

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON, skipping chunk: %r", raw[:200])
        return []

    if not isinstance(items, list):
        # Some models wrap the array in an object like {"triples": [...]}.
        if isinstance(items, dict) and len(items) == 1:
            items = next(iter(items.values()))
        if not isinstance(items, list):
            logger.warning("LLM JSON was not a list, skipping chunk: %r", raw[:200])
            return []

    triples: list[Triple] = []
    for item in items:
        try:
            triples.append(Triple.model_validate(item))
        except ValidationError as exc:
            logger.warning("Skipping malformed triple %r: %s", item, exc)
    return triples
