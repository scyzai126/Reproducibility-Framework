#!/usr/bin/env python3
"""Build the corpus assay table the /assays Corpus tab renders, from the finished registries.

The rows are built by app.agent.assay_table (moved there so the Extract tab's per-paper table is
built by the same code); this script walks every registry and writes the file.

One row per final assay: every entry of every `<registry_dir>/assays_OBI.json` under
`assay_service.REGISTRY_ROOT`. Round 5 has already keyed those entries by OBI term and folded
duplicates, so a row is one assay the paper performed, with every wording the paper used for it
joined into `assay`. **It calls nothing** -- the OBI term is already on disk.

The rows keep the schema `GET /agent/assay-obi` serves and `AssayObiRow` (apps/web/src/lib/types.ts)
renders -- study, assay, normalized_name, sample_type, readouts, obi_id, obi_label, resource,
obi_confidence -- so the route, its stats and the ImmPort sweep read the table unchanged.
`study` is `<pmid>_<SDY>` with the `_pdf` marker dropped, the spelling
`assay_immport.study_accession_of` parses.

Each row also carries the curator's matching assay from `data/benchmark_assay/`, paired by
`compare_assay_benchmark.py` -- the same pairing the benchmark report scores, so the table and the
report cannot disagree: `benchmark_assay` (the curator's name for it), `benchmark_obi_label` and
`benchmark_obi_id`, " / "-joined where several curator assays pair with one of ours, null where
none does. A curator assay that pairs with nothing of ours is added as its own row with
`benchmark_only: true` and only those fields filled; the API leaves such rows out of every
count, the ImmPort sweep included.

`benchmark_items` carries the same pairing structured, one entry per curator assay with its
`key` (unique within the paper, so a curator assay paired with two of our entries counts once) and
`obi_match` -- how our OBI term compares with the curator's: `same`, `related` (one is an is_a
ancestor of the other), `differs`, `ours_unmapped`, `curator_unmapped`, or `missed`. The Corpus
tab's accuracy bars count from it.

`paper_url` / `paper_source` link the row's paper for review: its PMC page when the JATS XML the
agent read names the paper's PMCID (in `<article-meta>`, never the reference list), else PubMed.

Rerun it after a paper is added or re-run; the table is derived and never hand-edited.

Usage:
    python3 scripts/build_assay_table.py [--dry-run]

Reads  : <REGISTRY_ROOT>/*/assays_OBI.json, data/benchmark_assay/*.json (via compare_assay_benchmark.py)
Writes : <REGISTRY_ROOT>/all_assays_OBI.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_service import REGISTRY_ROOT  # noqa: E402
# The builder lives in the app so GET /agent/assays/table builds one paper's rows with the same
# code; re-exported here for callers (and tests) that load this script.
from app.agent.assay_table import (  # noqa: E402,F401
    BENCHMARK_DIR,
    _obi_match,
    benchmark_pairing,
    paper_link,
    table_rows,
)

TABLE_NAME = "all_assays_OBI.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the counts, write nothing")
    args = parser.parse_args()

    rows = table_rows(REGISTRY_ROOT)
    ours = [row for row in rows if not row.get("benchmark_only")]
    mapped = sum(1 for row in ours if row["obi_id"])
    papers = len({row["study"] for row in ours})
    print(f"{len(ours)} assays across {papers} papers; {mapped} mapped to OBI, {len(ours) - mapped} unresolved")
    with_bench = sum(1 for row in ours if row["benchmark_assay"])
    print(f"benchmark: {with_bench} of our assays paired with a curator assay, "
          f"{len(ours) - with_bench} unpaired, {len(rows) - len(ours)} curator assays we missed "
          f"added as benchmark-only rows")

    out = REGISTRY_ROOT / TABLE_NAME
    if args.dry_run:
        print(f"dry run: would write {out}")
        return 0
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
