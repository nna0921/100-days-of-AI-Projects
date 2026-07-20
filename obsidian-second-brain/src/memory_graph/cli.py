"""typer CLI: `python -m memory_graph.cli ingest <vault_path>`."""

from __future__ import annotations

import logging

import typer

from memory_graph.extract import extract_from_chunks
from memory_graph.graph import ensure_constraints, get_counts, get_driver, upsert_relations
from memory_graph.ingest import load_and_chunk_vault

app = typer.Typer(help="Memory graph CLI")

logging.basicConfig(level=logging.INFO, format="%(message)s")


@app.command()
def ingest(vault_path: str = typer.Argument(..., help="Path to the Obsidian vault")):
    """Read markdown notes, extract triples with the local LLM, write to Neo4j."""
    chunks = load_and_chunk_vault(vault_path)
    typer.echo(f"Loaded {len(chunks)} chunks from {vault_path}")

    relations = extract_from_chunks(chunks)
    typer.echo(f"Extracted {len(relations)} relations")

    driver = get_driver()
    try:
        ensure_constraints(driver)
        upsert_relations(driver, relations)
        counts = get_counts(driver)
        typer.echo(
            "Graph now has "
            f"{counts['entities']} entities, {counts['notes']} notes, "
            f"{counts['relations']} relations, {counts['mentions']} mentions."
        )
    finally:
        driver.close()


if __name__ == "__main__":
    app()
