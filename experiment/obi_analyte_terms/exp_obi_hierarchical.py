#!/usr/bin/env python3
"""Arm 2 of the analyte-level OBI term experiment: family term first, then an analyte-specific
child only when the record earns it.

Stage A is today's mapping, read from `<registry_dir>/assays_OBI.json` -- no call. Stage B takes
that family term, lists the compositional (IEDB-style, "... measuring X production by Y cells")
descendants the live prune removed from under it, and asks one judge call
(prompts/hierarchical_pick.txt) whether the record supports exactly one of them: one analyte,
the right responder and specimen, and an epitope-specific stimulation. Otherwise the family
stays. The judge sees the record and the family term, never the paper.

Three gates in code decide which entries get a call at all:
    NO CHILDREN   the family has no compositional descendant (Olink, CyTOF, RNA-seq, ...)
    TOO MANY      the family has more than MAX_CHILDREN of them (the epitope-assay umbrellas:
                  T cell epitope assay 367, B cell epitope assay 94, MHC ligand assay 62)
    NO EVIDENCE   the record carries neither readouts nor sample type
    NO FAMILY     stage A left the entry unmapped
Everything else is one call. `--dry-run` prints the gate per entry and the call count.

Nothing in the production code or under data/ is touched. Output goes to
results/hierarchical/<registry_name>/{hierarchical.json, raw.json} beside this script.

Usage, from the repo root:
    ./.venv/bin/python experiment/obi_analyte_terms/exp_obi_hierarchical.py <registry_dir> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

PROMPT_PATH = HERE / "prompts" / "hierarchical_pick.txt"
RESULTS_DIR = HERE / "results" / "hierarchical"
LIVE_INDEX_PATH = REPO_ROOT / "data" / "OBI" / "obi_assay_pruned_index.json"

#: Families with more compositional children than this are not judged: a prompt listing 367
#: epitope-assay constructs is not a choice the record could inform.
MAX_CHILDREN = 60

GATE_NO_FAMILY = "NO FAMILY"
GATE_NO_CHILDREN = "NO CHILDREN"
GATE_TOO_MANY = "TOO MANY"
GATE_NO_EVIDENCE = "NO EVIDENCE"
GATE_JUDGED = "JUDGED"


# ── the children the prune removed, by family ─────────────────────────────────

@lru_cache(maxsize=1)
def compositional_children(obo_path: Path | None = None,
                           live_index_path: Path = LIVE_INDEX_PATH) -> dict[str, list[dict]]:
    """{family id: [{id, label, definition}, ...]} for every live-index term that has
    compositional descendants in the full assay branch.

    A compositional term (assay_obi_mapper._is_generic_assay_term says no) is walked up its
    `is_a` edges through nodes that are *not* in the live index until a live term is reached;
    each such term is one of its families. Multiple inheritance gives a term several families
    (an ICS child sits under both flow cytometry assay and T cell epitope assay).
    """
    import prune_obi_domain as prune
    from app.agent.assay_obi_mapper import _is_generic_assay_term

    obo = obo_path or prune.OBO_PATH
    terms = prune.read_terms(obo)
    parents = {t["id"]: t["parents"] for t in terms}
    definitions = {t["id"]: t["definition"] for t in terms}
    live = {t["id"] for t in json.loads(live_index_path.read_text(encoding="utf-8"))}

    families: dict[str, list[dict]] = defaultdict(list)
    for term in prune.assay_branch(obo):
        if _is_generic_assay_term(term["id"], term["label"]):
            continue
        stack, seen, found = list(parents.get(term["id"], ())), set(), set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if node in live:
                found.add(node)
            else:
                stack.extend(parents.get(node, ()))
        for family in sorted(found):
            families[family].append({"id": term["id"], "label": term["label"],
                                     "definition": definitions.get(term["id"], "")})
    return dict(families)


# ── gate, prompt, reply ───────────────────────────────────────────────────────

def gate(family_id: str | None, children: list[dict], entry: dict) -> str:
    if not family_id:
        return GATE_NO_FAMILY
    if not children:
        return GATE_NO_CHILDREN
    if len(children) > MAX_CHILDREN:
        return GATE_TOO_MANY
    if not str(entry.get("readouts") or "").strip() and not str(entry.get("sample_type") or "").strip():
        return GATE_NO_EVIDENCE
    return GATE_JUDGED


def _first_name(entry: dict, fallback: str) -> str:
    from app.agent.assay_extractor import paper_names

    names = paper_names(entry)
    return names[0] if names else fallback


def build_prompt(key: str, entry: dict, family: dict, children: list[dict],
                 prompt_path: Path = PROMPT_PATH) -> str:
    from app.agent.assay_extractor import paper_names

    names = paper_names(entry)
    aliases = names[1:] + [a for a in (entry.get("aliases") or []) if isinstance(a, str) and a.strip()]
    quote = str((entry.get("evidence") or {}).get("quote") or "")
    lines = "\n".join(
        f"{i}. {c['id']} | {c['label']} | definition: {' '.join(str(c.get('definition') or '').split())}"
        for i, c in enumerate(children, 1))
    return (
        prompt_path.read_text(encoding="utf-8")
        .replace("{assay_name}", names[0] if names else key)
        .replace("{aliases}", ", ".join(aliases) if aliases else "none given")
        .replace("{standard_technique_name}", str(entry.get("standard_technique_name") or "").strip() or "not given")
        .replace("{sample_type}", str(entry.get("sample_type") or "").strip() or "not specified")
        .replace("{readouts}", str(entry.get("readouts") or "").strip() or "not specified")
        .replace("{evidence_quote}", " ".join(quote.split()) or "none")
        .replace("{family_id}", family["id"])
        .replace("{family_label}", family["label"])
        .replace("{family_definition}", " ".join(str(family.get("definition") or "").split()) or "none")
        .replace("{children}", lines)
    )


class ReplyError(ValueError):
    """The judge's reply named neither a listed child nor `keep`."""


_REPLY = re.compile(r"^#?\s*(keep|\d+)\s*(?:[.):]\s*)?(?:\|\s*(.*))?$", re.IGNORECASE | re.DOTALL)


def parse_reply(reply: str, n_children: int) -> tuple[int | None, str]:
    """(0-based child index or None for keep, reason). Raises ReplyError otherwise."""
    text = reply.strip().strip("*`'\"").strip()
    match = _REPLY.match(text)
    if not match:
        raise ReplyError(f"reply not understood: {reply[:80]!r}")
    choice, reason = match.group(1).lower(), (match.group(2) or "").strip()
    if choice == "keep":
        return None, reason
    index = int(choice) - 1
    if not 0 <= index < n_children:
        raise ReplyError(f"reply names candidate {choice} of {n_children}")
    return index, reason


def judge(prompt: str) -> str:
    """One chat call, shaped like assay_obi_mapper._llm_pick."""
    from openai import OpenAI

    from app.agent.assay_extractor import EXTRACTION_SEED
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        seed=EXTRACTION_SEED,
    )
    return (resp.choices[0].message.content or "").strip()


# ── the run ───────────────────────────────────────────────────────────────────

def run(registry_dir: Path, dry_run: bool, results_dir: Path = RESULTS_DIR,
        judge_fn=judge, families: dict[str, list[dict]] | None = None) -> list[dict]:
    assays = json.loads((registry_dir / "assays.json").read_text(encoding="utf-8"))
    obi = json.loads((registry_dir / "assays_OBI.json").read_text(encoding="utf-8"))
    families = compositional_children() if families is None else families
    live = {t["id"]: t for t in json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))}

    rows: list[dict] = []
    raw: dict[str, dict] = {}
    for key, entry in assays.items():
        mapped = obi.get(key) or {}
        family_id = mapped.get("obi_id")
        children = families.get(family_id, []) if family_id else []
        decision = gate(family_id, children, entry)
        row = {
            "key": key,
            "name_in_paper": _first_name(entry, key),
            "family": {"id": family_id, "label": mapped.get("obi_label"),
                       "granularity": mapped.get("obi_granularity"),
                       "resource": mapped.get("resource")},
            "n_children": len(children),
            "gate": decision,
            "reply": None,
            "specific": None,
            "reason": None,
        }
        rows.append(row)
        if decision != GATE_JUDGED or dry_run:
            continue
        family = {"id": family_id, "label": mapped.get("obi_label"),
                  "definition": (live.get(family_id) or {}).get("definition", "")}
        prompt = build_prompt(key, entry, family, children)
        reply = judge_fn(prompt)
        raw[key] = {"reply": reply, "children": [f"{i}. {c['id']} | {c['label']}"
                                                 for i, c in enumerate(children, 1)],
                    "prompt": prompt}
        row["reply"] = reply
        try:
            index, reason = parse_reply(reply, len(children))
        except ReplyError as exc:
            row["gate"] = "JUDGE FAILED"
            row["reason"] = str(exc)
            continue
        row["reason"] = reason
        if index is not None:
            row["specific"] = {"id": children[index]["id"], "label": children[index]["label"]}

    calls = sum(1 for r in rows if r["gate"] == GATE_JUDGED)
    print(f"{registry_dir.name}: {len(rows)} entries, {calls} judged")
    for r in rows:
        fam = f"{r['family']['id']} {r['family']['label']}" if r["family"]["id"] else "(unmapped)"
        line = f"  {r['gate']:12} children={r['n_children']:<3} {r['name_in_paper']}\n      family: {fam}"
        if r["reply"] is not None:
            chosen = (f"{r['specific']['id']} {r['specific']['label']}" if r["specific"] else "keep")
            line += f"\n      judge:  {chosen}\n      reason: {r['reason']}"
        print(line)
    if dry_run:
        print("--dry-run: nothing called")
        return rows

    out_dir = results_dir / registry_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hierarchical.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "raw.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_dir / 'hierarchical.json'} and raw.json")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("registry_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.registry_dir, args.dry_run)


if __name__ == "__main__":
    main()
