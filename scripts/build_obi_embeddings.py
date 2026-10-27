"""Build and cache embeddings for an OBI assay vocabulary.

Reads  : data/OBI/obi_assay_pruned_index.json        (--terms)
Writes : data/OBI/obi_assay_pruned_embeddings.json   (--out)
Reuses : vectors from --reuse files (default: the output itself) whenever a row's
         (id, embed_input) is unchanged, so a rerun is free and a nested vocabulary is
         derived from a larger one's file with no API call at all: the three lists in
         data/OBI (full 1794 ⊃ noncompositional 1249 ⊃ pruned 701) share entries byte for
         byte, so one paid run over the full list feeds the other two.

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
  python scripts/build_obi_embeddings.py                       # pruned 701, in place
  python scripts/build_obi_embeddings.py --terms data/OBI/obi_assay_full_index.json \
      --out data/OBI/obi_assay_full_embeddings.json            # one paid run
  python scripts/build_obi_embeddings.py --reuse data/OBI/obi_assay_full_embeddings.json
                                                               # pruned 701 from it, free
"""

import argparse
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
OBI_DIR = REPO_ROOT / "data" / "OBI"
OBI_TERMS_PATH = OBI_DIR / "obi_assay_pruned_index.json"
OUTPUT_PATH = OBI_DIR / "obi_assay_pruned_embeddings.json"

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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--terms", type=Path, default=OBI_TERMS_PATH, help="vocabulary to embed")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH, help="embeddings file to write")
    parser.add_argument("--reuse", type=Path, nargs="*", default=None,
                        help="embeddings files to reuse vectors from (default: --out itself)")
    args = parser.parse_args()
    terms_path, output_path = args.terms, args.out
    reuse_paths = args.reuse if args.reuse is not None else [output_path]

    terms = json.loads(terms_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(terms)} OBI terms from {terms_path.name}")

    # Reuse a cached vector only when it was embedded from the same input string
    old_rows: list[dict] = []
    if output_path.exists():
        old_rows = json.loads(output_path.read_text(encoding="utf-8"))
    cached: dict[tuple[str, str], list[float]] = {}
    for path in reuse_paths:
        if not path.exists():
            continue
        rows_in = old_rows if path == output_path else json.loads(path.read_text(encoding="utf-8"))
        for r in rows_in:
            if "embed_input" in r:
                cached.setdefault((r["id"], r["embed_input"]), r["embedding"])
        print(f"  reusable vectors from {path.name}: {len(rows_in)}")

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
    if not to_embed and results == old_rows:
        print("Nothing to do.")
        return

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(results)} embeddings → {output_path}")
    print(f"Dimensions: {len(results[0]['embedding'])}")


if __name__ == "__main__":
    main()
