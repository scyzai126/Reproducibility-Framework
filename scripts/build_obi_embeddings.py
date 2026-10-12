"""Build and cache embeddings for all OBI assay terms.

Reads  : data/OBI/obi_generic_index.json
Writes : data/OBI/obi_generic_embeddings.json

Each entry in the output:
  {
    "id":          "OBI:0000916",
    "label":       "flow cytometry assay",
    "text":        "flow cytometry assay | FACS",          # shown to the pick LLM
    "embed_input": "flow cytometry assay | FACS | A cytometry assay in which ...",
    "embedding":   [0.023, -0.041, ...]   # 1536-dim text-embedding-3-small of embed_input
  }

`text` stays label + synonyms because the mapper splits it on "|" to list a candidate's synonyms;
the definition is embedded but kept out of it. The output always holds exactly the index's terms
in index order. A row is re-embedded only when its `embed_input` changed, so a rerun is free.

Usage:
  python scripts/build_obi_embeddings.py
"""

import json
import sys
import time
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
OBI_DIR = REPO_ROOT / "data" / "OBI"
OBI_TERMS_PATH = OBI_DIR / "obi_generic_index.json"
OUTPUT_PATH = OBI_DIR / "obi_generic_embeddings.json"

EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100  # texts per API call


def build_text(term: dict) -> str:
    """Concatenate label and synonyms — the wording the pick prompt shows for a candidate."""
    parts = [term["label"]] + [s for s in term.get("synonyms", []) if s]
    return " | ".join(parts)


def build_embed_input(term: dict) -> str:
    """The string actually embedded: label, synonyms and the OBO definition."""
    text = build_text(term)
    definition = term.get("definition", "")
    return f"{text} | {definition}" if definition else text


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    # API returns items sorted by index
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]


def main() -> None:
    terms = json.loads(OBI_TERMS_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(terms)} OBI terms from {OBI_TERMS_PATH.name}")

    # Reuse a cached vector only when it was embedded from the same input string
    old_rows: list[dict] = []
    if OUTPUT_PATH.exists():
        old_rows = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    cached = {
        (r["id"], r["embed_input"]): r["embedding"] for r in old_rows if "embed_input" in r
    }

    rows = [
        {
            "id": t["id"],
            "label": t["label"],
            "text": build_text(t),
            "embed_input": build_embed_input(t),
        }
        for t in terms
    ]
    to_embed = [r for r in rows if (r["id"], r["embed_input"]) not in cached]
    print(f"{len(rows) - len(to_embed)} reused, {len(to_embed)} to embed via {EMBED_MODEL}")

    if to_embed:
        client = OpenAI()
        batches = [to_embed[i : i + BATCH_SIZE] for i in range(0, len(to_embed), BATCH_SIZE)]
        for i, batch in enumerate(batches, 1):
            print(f"  Batch {i}/{len(batches)} ({len(batch)} texts)…", end=" ", flush=True)
            t0 = time.time()
            embeddings = embed_batch(client, [r["embed_input"] for r in batch])
            print(f"{time.time() - t0:.1f}s")
            for row, embedding in zip(batch, embeddings):
                cached[(row["id"], row["embed_input"])] = embedding

    results = [{**r, "embedding": cached[(r["id"], r["embed_input"])]} for r in rows]
    if not to_embed and len(results) == len(old_rows):
        print("Nothing to do.")
        return

    OUTPUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(results)} embeddings → {OUTPUT_PATH}")
    print(f"Dimensions: {len(results[0]['embedding'])}")


if __name__ == "__main__":
    main()
