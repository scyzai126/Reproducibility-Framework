"""Build and cache embeddings for all OBI assay terms.

Reads  : data/OBI/obi_generic_index.json
Writes : data/OBI/obi_generic_embeddings.json

Each entry in the output:
  {
    "id":        "OBI:0000916",
    "label":     "flow cytometry assay",
    "text":      "flow cytometry assay | FACS",
    "embedding": [0.023, -0.041, ...]   # 1536-dim text-embedding-3-small
  }

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
    """Concatenate label and synonyms into a single embeddable string."""
    parts = [term["label"]] + [s for s in term.get("synonyms", []) if s]
    return " | ".join(parts)


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    # API returns items sorted by index
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]


def main() -> None:
    terms = json.loads(OBI_TERMS_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(terms)} OBI terms from {OBI_TERMS_PATH.name}")

    # Skip terms that are already embedded (resume support)
    existing: dict[str, list[float]] = {}
    if OUTPUT_PATH.exists():
        for entry in json.loads(OUTPUT_PATH.read_text(encoding="utf-8")):
            existing[entry["id"]] = entry["embedding"]
        print(f"Resuming — {len(existing)} terms already embedded")

    to_embed = [t for t in terms if t["id"] not in existing]
    print(f"{len(to_embed)} terms to embed via {EMBED_MODEL}")

    if not to_embed:
        print("Nothing to do.")
        return

    client = OpenAI()

    results: list[dict] = [
        {"id": t["id"], "label": t["label"], "text": build_text(t), "embedding": existing[t["id"]]}
        for t in terms
        if t["id"] in existing
    ]

    batches = [to_embed[i : i + BATCH_SIZE] for i in range(0, len(to_embed), BATCH_SIZE)]
    for i, batch in enumerate(batches, 1):
        texts = [build_text(t) for t in batch]
        print(f"  Batch {i}/{len(batches)} ({len(texts)} texts)…", end=" ", flush=True)
        t0 = time.time()
        embeddings = embed_batch(client, texts)
        print(f"{time.time() - t0:.1f}s")
        for term, embedding in zip(batch, embeddings):
            results.append({
                "id": term["id"],
                "label": term["label"],
                "text": build_text(term),
                "embedding": embedding,
            })

    # Restore original term order
    order = {t["id"]: i for i, t in enumerate(terms)}
    results.sort(key=lambda r: order.get(r["id"], 9999))

    OUTPUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(results)} embeddings → {OUTPUT_PATH}")
    print(f"Dimensions: {len(results[0]['embedding'])}")


if __name__ == "__main__":
    main()
