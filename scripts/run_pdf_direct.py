"""Run the PDF-direct pipeline: send the raw PDF bytes straight to the model
(no local page rendering) and let the API's own PDF handling do the reading.

Assays and claims are extracted independently and concurrently (each claim
self-names its own assay, without seeing the assay registry), then reconciled:
exact/alias string matching first, a single paper-grounded validation call for
whatever's left, then one OBI-enrichment pass over the final registry.

Usage:
    python scripts/run_pdf_direct.py <pdf_path> <out_dir>

Example:
    python scripts/run_pdf_direct.py data/pdf/26papers/SDY1119_26682988.pdf data/claims/SDY1119_26682988_pdf

Output files:
    assays.json                     - independently-discovered, reconciled assay registry
    assays_OBI.json                 - assays.json enriched with OBI ontology mappings
    claims.json                     - independently-extracted claims, linked to assays.json
    claim_filtered.json             - the downstream-actionable subset of claims.json (claim_filter.py)
    invalid_claims.json             - claims the validation pass rejected (only if non-empty)
    abstract_unmatched_findings.json - Abstract findings with no Results/Figure/Table support (only if non-empty)
    claims_validation.json          - closed-book accuracy judgement over claim_filtered.json
    groups.json                     - filtered claims structured into groups + comparisons (classify_groups.txt)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.assay_claim_linker import reconcile_claims_with_assays
from app.agent.assay_obi_mapper import enrich_assays_with_obi
from app.agent.claim_filter import DOWNSTREAM_CLAIM_TYPES, filter_claims_for_downstream
from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.claim_validator import build_report, validate_claims_file
from app.agent.pdf_direct import (
    _pdf_file_content,
    extract_assays_from_pdf_direct,
    extract_claims_from_pdf_direct,
)
from app.config import settings


async def run_group_step(claims: dict, client) -> dict:
    """Structure each claim into comparison_strategy + groups + comparison via classify_groups.txt."""
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Step 3: structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key].get("sources", [])}}
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
        groups[key] = val
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Extracting assays and claims concurrently with {settings.OPENAI_MODEL}...")
    assays, (claims, abstract_unmatched) = await asyncio.gather(
        extract_assays_from_pdf_direct(pdf_bytes, pdf_path.name, client),
        extract_claims_from_pdf_direct(pdf_bytes, pdf_path.name, client),
    )
    print(f"  assays found: {list(assays.keys())}")
    print(f"  claims found: {len(claims)}")

    print("Reconciling claims against the assay registry...")
    paper_content = [
        _pdf_file_content(pdf_bytes, pdf_path.name),
        {"type": "text", "text": "Validate the candidate assay-claim pairings against this paper as instructed."},
    ]
    resolved, merged_assays, invalid_claims = await reconcile_claims_with_assays(
        claims, assays, paper_content, client
    )
    print(f"  {len(resolved)}/{len(claims)} claims resolved, {len(invalid_claims)} rejected")
    if len(merged_assays) > len(assays):
        added = set(merged_assays) - set(assays)
        print(f"  validation added {len(added)} assay(s) missed by discovery: {sorted(added)}")

    final_claims: dict = {}
    for claim_key, registry_key in resolved.items():
        entry = merged_assays.get(registry_key, {})
        claim = claims[claim_key]
        claim["assay"] = {"name_in_paper": entry.get("name_in_paper", registry_key)}
        final_claims[claim_key] = claim

    (out_dir / "assays.json").write_text(json.dumps(merged_assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays.json")

    # Persist the extraction output before OBI enrichment: everything above this
    # point costs several full-paper LLM calls, so a failure in the (cheaper,
    # independent) OBI step must not discard it.
    (out_dir / "claims.json").write_text(json.dumps(final_claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims.json")

    # claims.json stays the complete extraction record; everything downstream runs on the
    # actionable subset only, so the unreproducible types cost no further LLM calls.
    filtered_claims, dropped = filter_claims_for_downstream(final_claims)
    (out_dir / "claim_filtered.json").write_text(
        json.dumps(filtered_claims, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  saved claim_filtered.json ({len(filtered_claims)}/{len(final_claims)} kept)")
    if dropped:
        print(f"    dropped: {dict(sorted(dropped.items()))}")

    invalid_path = out_dir / "invalid_claims.json"
    if invalid_claims:
        invalid_path.write_text(json.dumps(invalid_claims, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  saved invalid_claims.json ({len(invalid_claims)} rejected)")
    elif invalid_path.exists():
        invalid_path.unlink()

    unmatched_path = out_dir / "abstract_unmatched_findings.json"
    if abstract_unmatched:
        unmatched_path.write_text(json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  saved abstract_unmatched_findings.json")
    elif unmatched_path.exists():
        unmatched_path.unlink()

    print("Enriching final assay registry with OBI terms...")
    final_assays = enrich_assays_with_obi(merged_assays)
    (out_dir / "assays_OBI.json").write_text(json.dumps(final_assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays_OBI.json")

    if not filtered_claims:
        # Every extraction output is already on disk. Running the group step on nothing would
        # overwrite an existing groups.json / claims_validation.json with an empty object.
        print(
            "\nWARNING: no claim carried a downstream claim_type "
            f"({', '.join(DOWNSTREAM_CLAIM_TYPES)}) - skipping the group and validation steps."
        )
        print(f"\nDone. Files written to {out_dir}")
        return

    # Audit before structuring, not after: a claim that fails here is caught without ever
    # paying a classify_groups call on it. Everything it reads is already persisted, so a
    # failure in the judge cannot cost any of the extraction above it.
    report = build_report(await validate_claims_file(filtered_claims, client))
    (out_dir / "claims_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = report["summary"]
    print(
        f"  saved claims_validation.json - {summary['accurate']}/{summary['total']} accurate, "
        f"{summary['needs_revision']} need revision, "
        f"{summary['inconclusive']} inconclusive, {summary['errors']} errors"
    )

    groups = await run_group_step(filtered_claims, client)
    (out_dir / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/run_pdf_direct.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
