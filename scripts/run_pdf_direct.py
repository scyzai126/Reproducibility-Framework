"""Run the PDF-direct pipeline: send the raw PDF bytes straight to the model
(no local page rendering) and let the API's own PDF handling do the reading.

One extraction call: each claim names the assay that generated it. The assay
registry is folded up from those names and then OBI-enriched.

Usage:
    python scripts/run_pdf_direct.py <pdf_path> <out_dir>

Example:
    python scripts/run_pdf_direct.py data/pdf/26papers/SDY1119_26682988.pdf data/claims/SDY1119_26682988_pdf

Output files:
    assays.json                     - the assay registry, folded up from the assay each claim named
    assays_OBI.json                 - assays.json enriched with OBI ontology mappings
    claims.json                     - the extracted claims, each carrying the assay it named
    claim_filtered.json             - the downstream-actionable subset of claims.json (claim_filter.py)
    abstract_unmatched_findings.json - Abstract findings with no Results/Figure/Table support (only if non-empty)
    claims_groups.json              - filtered claims structured into groups + comparisons (classify_groups.txt)

The closed-book accuracy judge is not part of this run - it costs one LLM call per claim
and gates nothing. Run it on demand with `python scripts/run_claim_validate.py <out_dir>`.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.assay_obi_mapper import enrich_assays_with_obi
from app.agent.assay_registry import registry_from_claims
from app.agent.claim_filter import DOWNSTREAM_CLAIM_TYPES, filter_claims_for_downstream
from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import extract_claims_from_pdf_direct
from app.config import settings


async def run_group_step(claims: dict, client) -> dict:
    """Structure each claim into comparison_strategy + groups + comparison via classify_groups.txt."""
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Step 3: structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {
            key: {
                "claim": claims[key]["claim"],
                "claim_type": claims[key].get("claim_type"),
                "sources": claims[key].get("sources", []),
            }
        }
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        val = result.get(key, {})
        val.setdefault("claim", claims[key]["claim"])
        val.setdefault("sources", claims[key].get("sources", []))
        # claim_type is carried through from the input claims rather than asked of the
        # model: claim_filter already selected on this value, so a re-derived one could
        # disagree with the filter that let the claim through. The model now SEES the field
        # in its input, so it may echo one back — discard that before merging, or `**val`
        # would override the inherited value and quietly break the chain.
        val.pop("claim_type", None)
        groups[key] = {"claim_type": claims[key].get("claim_type"), **val}
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Extracting claims with {settings.OPENAI_MODEL}...")
    final_claims, abstract_unmatched = await extract_claims_from_pdf_direct(
        pdf_bytes, pdf_path.name, client
    )
    print(f"  claims found: {len(final_claims)}")

    assays = registry_from_claims(final_claims)
    print(f"  assays named by those claims: {list(assays.keys())}")

    (out_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays.json")

    # Persist the extraction output before OBI enrichment: everything above this
    # point costs several full-paper LLM calls, so a failure in the (cheaper,
    # independent) OBI step must not discard it.
    (out_dir / "claims.json").write_text(json.dumps(final_claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims.json")

    # claims.json stays the complete extraction record; everything downstream runs on the
    # actionable subset only, so the unreproducible types cost no further LLM calls.
    filtered_claims, dropped, kept_polarity = filter_claims_for_downstream(final_claims)
    (out_dir / "claim_filtered.json").write_text(
        json.dumps(filtered_claims, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  saved claim_filtered.json ({len(filtered_claims)}/{len(final_claims)} kept)")
    if dropped:
        print(f"    dropped: {dict(sorted(dropped.items()))}")
    if kept_polarity:
        print(f"    polarity: {dict(sorted(kept_polarity.items()))}")

    # Nothing can be left unlinked now that the registry comes from the claims themselves.
    # Clear any unlinked_claims.json a previous two-pass run left in this directory, so a
    # re-parse in place doesn't leave a stale diagnostic beside fresh output.
    (out_dir / "unlinked_claims.json").unlink(missing_ok=True)

    unmatched_path = out_dir / "abstract_unmatched_findings.json"
    if abstract_unmatched:
        unmatched_path.write_text(json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  saved abstract_unmatched_findings.json")
    elif unmatched_path.exists():
        unmatched_path.unlink()

    print("Enriching final assay registry with OBI terms...")
    final_assays = enrich_assays_with_obi(assays)
    (out_dir / "assays_OBI.json").write_text(json.dumps(final_assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays_OBI.json")

    if not filtered_claims:
        # Every extraction output is already on disk. Running the group step on nothing would
        # overwrite an existing claims_groups.json with an empty object.
        print(
            "\nWARNING: no claim carried a downstream claim_type "
            f"({', '.join(DOWNSTREAM_CLAIM_TYPES)}) - skipping the group step."
        )
        print(f"\nDone. Files written to {out_dir}")
        return

    # The closed-book accuracy judge is deliberately NOT run here. It costs one LLM call per
    # claim and only ever reported - it never gated anything downstream - so it belongs on
    # demand rather than in every parse. Run it separately when you want it:
    #     python scripts/run_claim_validate.py <out_dir>
    groups = await run_group_step(filtered_claims, client)
    (out_dir / "claims_groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims_groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/run_pdf_direct.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
