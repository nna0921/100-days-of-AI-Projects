"""
ai.py
-----
Single module for all LLM calls, so the model/provider is easy to swap.

Provider: Google Gemini (free tier via Google AI Studio).
Setup:
    pip install google-genai
    Get a free key at https://aistudio.google.com/apikey
    Put it in .env as GOOGLE_API_KEY=...
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = "gemini-2.0-flash"

_api_key = os.getenv("GOOGLE_API_KEY")
_client = genai.Client(api_key=_api_key) if _api_key else None


def is_configured() -> bool:
    return _client is not None


def generate(prompt: str, system: str | None = None) -> str:
    """Send a prompt to Gemini and return the text response.

    Returns a clear error string instead of raising, so the UI can display
    it inline rather than crashing the demo.
    """
    if not is_configured():
        return "[AI not configured: set GOOGLE_API_KEY in .env]"

    try:
        config = {"system_instruction": system} if system else None
        response = _client.models.generate_content(
            model=MODEL_NAME, contents=prompt, config=config
        )
        return (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the UI
        return f"[AI error: {exc}]"
