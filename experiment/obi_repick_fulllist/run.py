"""Round 5's BROAD re-pick over the whole vocabulary, run alone on the finished v3 registries.

Answers one question: handed all 701 terms minus its category, does any of the corpus's BROAD
mappings move to a descendant? The 2026-10-27 full-list A/B says no (0 of 27), so the expected
table is all "unchanged"; a change is a finding to read, not a success.

Nothing is written in place. Each registry's `assays.json` and `assays_OBI.json` are copied
under runs/<registry>/ and `repick_broad` is run on the copies; the model replies land in
runs/<registry>/assays_raw.json under `repick`, with `rejected` on any answer the descendant
guard refused.

    python3 experiment/obi_repick_fulllist/run.py --dry-run     # which entries would be asked
    python3 experiment/obi_repick_fulllist/run.py               # one call per listed entry
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "apps" / "api"))

from app.agent import assay_trace  # noqa: E402
from app.agent.assay_obi_mapper import FULLLIST_RESOURCE, repick_broad, repick_can_help  # noqa: E402

SOURCE = _REPO / "data" / "31paper_assays" / "assay_result_v3"
RUNS = Path(__file__).resolve().parent / "runs"


def _broad_entries(obi: dict) -> list[tuple[str, dict, bool]]:
    return [(key, mapping, repick_can_help(mapping)) for key, mapping in obi.items()
            if str(mapping.get("obi_granularity") or "").upper() == "BROAD"
            and mapping.get("resource") != FULLLIST_RESOURCE]


def main(dry_run: bool) -> None:
    asked = skipped = changed = 0
    for registry in sorted(p for p in SOURCE.iterdir() if (p / "assays_OBI.json").exists()):
        obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
        broad = _broad_entries(obi)
        if not broad:
            continue
        print(f"\n{registry.name}")
        for key, mapping, can_help in broad:
            label = mapping.get("obi_label")
            if not can_help:
                skipped += 1
                print(f"  SKIP      {key}: {label} has no descendant in the vocabulary")
            else:
                asked += 1
                print(f"  {'WOULD ASK' if dry_run else 'ASK':9} {key}: {label}")
        if dry_run:
            continue
        target = RUNS / registry.name
        target.mkdir(parents=True, exist_ok=True)
        for name in ("assays.json", "assays_OBI.json"):
            shutil.copy(registry / name, target / name)
        assays = json.loads((target / "assays.json").read_text(encoding="utf-8"))
        trace = assay_trace.start()
        try:
            new_obi, repicked, attempts = repick_broad(assays, obi)
        finally:
            assay_trace.stop()
        trace.write(target / assay_trace.RAW_FILE)
        (target / "assays_OBI.json").write_text(
            json.dumps(new_obi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        raw = json.loads((target / assay_trace.RAW_FILE).read_text(encoding="utf-8"))
        for key, record in (raw.get("repick") or {}).items():
            if key in repicked:
                changed += 1
                print(f"  REPICKED  {key}: {repicked[key]['from']} → {repicked[key]['to']}")
            elif record.get("rejected"):
                print(f"  REJECTED  {key}: picked {record['rejected']}, not under "
                      f"{record.get('broad_label')}; kept")
            else:
                print(f"  unchanged {key}: {record.get('reply')}")
        print(f"  {attempts} call(s)")
    verb = "would be asked" if dry_run else "asked"
    print(f"\n{asked} BROAD entr{'y' if asked == 1 else 'ies'} {verb}, {skipped} skipped "
          f"(no descendant), {changed} changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list the entries; call nothing")
    main(parser.parse_args().dry_run)
