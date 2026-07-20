"""Loads environment variables and exposes a single Settings object."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    llm_backend: str
    ollama_model: str
    ollama_host: str
    api_key: str | None
    api_model: str | None


def get_settings() -> Settings:
    return Settings(
        neo4j_uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD", "changeme123"),
        llm_backend=os.environ.get("LLM_BACKEND", "ollama"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        api_key=os.environ.get("API_KEY"),
        api_model=os.environ.get("API_MODEL"),
    )
