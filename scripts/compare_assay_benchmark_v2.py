#!/usr/bin/env python3
"""Compare the agent's assay registries against the curated benchmark, one-to-one, and render a
review page. **This is the comparison to use**; `compare_assay_benchmark.py` is the matching
library it imports from (tiers, statuses, the OBI graph) and its own report lets a curator row
claim every agent entry on a tier, which is what this script was written to stop.

`data/benchmark_curator_assay/benchmark_assay_v5/` is the curators' latest pass (--benchmark-dir for
another). Three things differ from the shared algorithm:

* Several assay names a curator listed separately map to the same OBI term (four flow-cytometry
  panels in SDY1289, two ELISPOTs in SDY984). Each is matched on its own first; a row left without
  a partner then folds into a row on the same term that was paired with an agent entry on that
  term -- the agent's registry is keyed by OBI label, and scoring four rows against its one would
  read as three misses. Folding before matching instead erased assays a curator filed under a
  generic term (CFSE and ADCC under `flow cytometry assay`) that the agent kept separate.
* Some files are hand-edited JSON with trailing commas or an unclosed brace. They are repaired in
  memory, never on disk, and every repair is reported.
* Each side is used once. A curator row is paired with one agent entry (a shared name outranks
  a shared term), and its status is that pair's. Further agent entries left on the same OBI
  term -- round 5 keeps a BROAD mapping apart from its sibling, so SDY1289 delivers three flow
  cytometry entries against the curator's one -- are listed on the row as `also_on_term` and
  counted as `split`, an annotation; they no longer turn a one-to-one MATCH into a SPLIT status.

Matching tiers and statuses are the ones in `compare_assay_benchmark.py`, imported, not copied.
No LLM call.

`--strict` turns off the two leniencies above that flatter the agent, for a number that can stand
beside other methods' (every baseline arm is scored in both modes):

* no leftover fold: a curated row that found no partner is MISSED, whatever term it carries, and
  the denominator is the raw row count the curators wrote;
* a pair the ontology alone made (same term or parent/child, with no shared name, alias or quote)
  ranks below every pair the names made, so it is taken only when nothing better claims either
  side. The pairs taken that way are counted as `term_only_pairs` in both modes.

Usage:
    python3 scripts/compare_assay_benchmark_v2.py [--only SDY1289] [--benchmark-dir DIR]
                                                  [--registry-dir DIR] [--out-stem NAME] [--strict]

Reads  : data/benchmark_curator_assay/benchmark_assay_v5/*.json
         data/benchmark_agent_assays/assay_result_v1/<pmid>_<SDY>/{assays_benchmark,assays_OBI}.json
         data/OBI/obi.obo
Writes : data/benchmark_curator_assay/comparison/<out-stem>.{json,html} -- or, with --registry-dir,
         <registry-dir>/comparison/<out-stem>.{json,html}, so another result version's report
         never overwrites the default's.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_assay_benchmark import (  # noqa: E402
    MATCHED_STATUSES,
    TIERS,
    ObiGraph,
    _surface_forms,
    bench_evidence,
    bench_obi_id,
    match_tier,
    normalize,
    our_row,
    status_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "data" / "benchmark_curator_assay" / "benchmark_assay_v5"
REGISTRY_DIR = REPO_ROOT / "data" / "benchmark_agent_assays" / "assay_result_v1"
OUT_DIR = REPO_ROOT / "data" / "benchmark_curator_assay" / "comparison"
OUT_STEM = "benchmark_vs_agent"

#: Scores for every comparison arm, rebuilt by `experiment/common/compare_arms.py`. The page
#: embeds the strict-mode columns so the agent's numbers can be read beside the alternatives
#: instead of alone. Read, never written: if the file is absent the section is simply omitted.
BASELINES_PATH = REPO_ROOT / "experiment" / "common" / "comparison" / "arms_table.md"
#: (column in arms_table.md, name on the page, what the arm is). The arms table also carries the
#: Methods-only and full-vocabulary variants; the whole-paper variant is the stronger of each
#: pair, so it is the one shown here.
BASELINE_ARMS = [
    ("agent", "agent (this page)",
     "The pipeline these results come from: six rounds — three extraction calls voted into one "
     "registry, a verifier, a corrector, the OBI mapping, a fold on measurement identity, and a "
     "judge for the folds the rules refused. The mapping step retrieves 30 candidate terms by "
     "embedding and spends one call picking among them, reading their definitions. ~17 model "
     "calls per paper."),
    ("bare LLM ×3 (strict ids)", "bare LLM, ids as given",
     "One call per paper: “list this paper's assays and give each an OBI id”, with no vocabulary "
     "in the prompt. Scored on the ids the model produced, which it has to recall from memory — "
     "this is what an ontology id looks like when nothing checks it. Mean of three runs."),
    ("bare LLM ×3 (labels read)", "bare LLM, labels read",
     "The same three runs, scored more kindly: the model's *labels* are resolved to OBI ids for "
     "it, so the arm is judged on whether it named the right assay rather than on recalling the "
     "number. The gap between this column and the one before it is pure id recall."),
    ("RAG single call ×3", "RAG single call",
     "Retrieval-augmented generation in its simplest form: the same one-call prompt, but the "
     "whole 701-term OBI vocabulary is pasted into the context, so the model picks ids off a list "
     "instead of recalling them. One call per paper — no vote, no verifier, no fold. This is the "
     "“just put the ontology in the prompt” baseline, and the closest arm to the agent. "
     "Mean of three runs."),
    ("OntoGPT", "OntoGPT",
     "The published tool (SPIRES, v1.2.0) for exactly this task, run as it ships on the same "
     "model: the LLM extracts entities, then OAK grounds each string to OBI by lexical lookup. "
     "One call per paper."),
    ("NCBO Annotator, pruned/paper", "NCBO Annotator",
     "BioPortal's concept-recognition web service over OBI — no model at all, pure string "
     "recognition of OBI labels and synonyms in the text. The established non-LLM tool."),
    ("dictionary, pruned/paper", "dictionary",
     "Our own no-model control: OBI labels and synonyms matched against the paper, longest match "
     "first, plurals and a trailing “assay” handled. It exists to show how much of the score is "
     "available from string matching alone."),
    ("agent, old same-term fold", "agent, old fold",
     "The same agent registries under the superseded fold rule (“same OBI term ⇒ same assay”). "
     "Not a competitor — it is here to price the current rule, which keeps one entry per "
     "measurement instead of per technique."),
]
#: (row in arms_table.md, name on the page, tooltip). Only the agent column is live on this page;
#: every number here comes from the arms table.
BASELINE_ROWS = [
    ("entries", "entries delivered", "assay entries the arm produced over the 31 papers"),
    ("matched", "matched of 158", "curated rows the scorer could pair with an entry"),
    ("MISSED", "missed", "curated rows no entry paired with"),
    ("EXTRA", "extra", "entries with no curated row — candidates for review, not errors"),
    ("exact (same OBI term as curator)", "exact OBI term", "same OBI id as the curator"),
    ("OBI ok (same or parent/child)", "OBI ok", "same id, or one a parent/child of the other"),
    ("wrong term (CONFLICT)", "wrong term", "paired, but the two terms disagree"),
    ("no usable term (UNMAPPED)", "no usable term", "paired, but the entry carries no OBI id"),
    ("recall", "recall", "matched ÷ 158"),
    ("precision", "precision", "matched ÷ entries delivered"),
    ("F1", "F1", "harmonic mean of recall and precision"),
    ("obi_recall", "OBI recall", "OBI ok ÷ 158"),
    ("calls", "model calls", "over all 31 papers"),
]


def use_registry_dir(path: Path) -> None:
    """Score another result version. Its report goes beside it, under `<path>/comparison/`."""
    global REGISTRY_DIR, OUT_DIR
    REGISTRY_DIR = Path(path).resolve()
    OUT_DIR = REGISTRY_DIR / "comparison"

#: v2 filenames drop the PMID for the two studies that hold two papers each. Which paper each file
#: covers was read off its content against the v1 files, which did carry the PMID.
PINNED_PMIDS = {
    "SDY1276_1_assays_AS_v2.json": "21357945",
    "SDY1276_2_assays_AS_v2.json": "23878721",
    "SDY1364_Assay_Hailong.json": "23266342",
    "SDY1364_2_assays_AS_v2.json": "23844129",
}

_STUDY = re.compile(r"^(SDY\d+)")


# ── reading hand-edited JSON ─────────────────────────────────────────────────


def _strip_trailing_commas(text: str) -> str:
    """Drop a comma that directly precedes `}` or `]`, outside string literals."""
    out: list[str] = []
    in_str = escape = False
    for i, ch in enumerate(text):
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == ",":
            rest = text[i + 1:].lstrip()
            if rest[:1] in ("}", "]"):
                continue
        out.append(ch)
    return "".join(out)


def _close_open_brackets(text: str) -> str:
    """Append whatever `}`/`]` are still open at the end of the text, innermost first."""
    stack: list[str] = []
    in_str = escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return text.rstrip() + "\n" + "".join(reversed(stack))


def load_lenient(path: Path) -> tuple[dict | None, str | None, str | None]:
    """(data, repair, error). `repair` names what was fixed in memory; the file is left untouched."""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as first:
        original = f"{first.msg} at line {first.lineno} col {first.colno}"
    else:
        # A missing `}` mid-file that an extra one at the end balances still parses, with every
        # later entry nested inside the unclosed one (SDY1669).
        data, hoisted = _hoist_nested_entries(data)
        if not hoisted:
            return data, None, None
        return data, (f"un-nested {len(hoisted)} entries swallowed by an unclosed one "
                      f"({', '.join(hoisted)}); the file parsed, its braces balanced by a stray one"), None
    repairs = [
        ("removed trailing commas", _strip_trailing_commas),
        ("closed unbalanced braces", _close_open_brackets),
        ("removed trailing commas + closed unbalanced braces",
         lambda t: _close_open_brackets(_strip_trailing_commas(t))),
    ]
    for label, fix in repairs:
        try:
            data = json.loads(fix(text))
        except json.JSONDecodeError:
            continue
        data, hoisted = _hoist_nested_entries(data)
        if hoisted:
            label += f"; un-nested {len(hoisted)} entries swallowed by an unclosed one ({', '.join(hoisted)})"
        return data, f"{label} (was: {original})", None
    return None, None, original


def _hoist_nested_entries(data: dict) -> tuple[dict, list[str]]:
    """Lift assay entries that a mid-file missing `}` left nested inside the previous entry.

    Closing the braces at the end of the file makes it parse, but everything after the unclosed
    entry then sits inside it. An assay entry is recognisable by its `name_in_paper` field.
    """
    out: dict = {}
    hoisted: list[str] = []
    for key, entry in data.items():
        if not isinstance(entry, dict):
            out[key] = entry
            continue
        nested = {k: v for k, v in entry.items() if isinstance(v, dict) and "name_in_paper" in v}
        out[key] = {k: v for k, v in entry.items() if k not in nested}
        for k, v in nested.items():
            out[k] = v
            hoisted.append(k)
    return out, hoisted


# ── merging same-OBI benchmark rows ──────────────────────────────────────────


def _names(value) -> list[str]:
    return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v]


def prepare_benchmark(bench: dict, obi: ObiGraph) -> dict:
    """One row per curated entry, carrying its OBI id, its quote and `merged_from: [key]`.

    Nothing is merged here. Merging same-OBI entries before matching erased real assays: curators
    put CFSE labeling (SDY1289) and the NK-mediated ADCC assay (SDY1294) under the generic
    `flow cytometry assay`, so both vanished into immunophenotyping and the agent's own CFSE and
    ADCC entries scored as EXTRA. `compare_paper` folds only the rows that found no partner.
    """
    return {key: {**entry, "obi_id": bench_obi_id(entry) or obi.resolve(key), "merged_from": [key],
                  "quotes": [bench_evidence(entry)]}
            for key, entry in bench.items()}


def fold_rows(members: list[tuple[str, dict]]) -> dict:
    """The first row, carrying every member's names, aliases and quotes.

    The first member is the one that was paired, so its key, OBI id and evidence block stay the
    row's own; the others contribute what they were called and what they quoted.
    """
    if len(members) == 1:
        return members[0][1]
    names: list[str] = []
    aliases: list[str] = []
    quotes: list[dict] = []
    for key, entry in members:
        names += [n for n in dict.fromkeys([key, *_names(entry.get("name_in_paper"))]) if n not in names]
        aliases += [a for a in dict.fromkeys(entry.get("aliases") or []) if a not in aliases]
        quotes += [{**q, "from": key} for q in entry["quotes"]]
    claims = {entry.get("generate_claim") for _, entry in members}
    return {
        **members[0][1],
        "name_in_paper": names,
        "aliases": aliases,
        "generate_claim": True if True in claims else (False if False in claims else None),
        "merged_from": [k for _, entry in members for k in entry["merged_from"]],
        "quotes": quotes,
    }


# ── pairing papers ───────────────────────────────────────────────────────────


def discover_pairs(only: str | None = None, benchmark_dir: Path = BENCHMARK_DIR) -> tuple[list[dict], list[str]]:
    registries = sorted(d for d in REGISTRY_DIR.iterdir()
                        if d.is_dir() and (d / "assays_benchmark.json").exists())
    pairs: list[dict] = []
    skipped: list[str] = []
    for path in sorted(benchmark_dir.glob("*.json")):
        m = _STUDY.match(path.name)
        if not m:
            skipped.append(f"{path.name}: filename does not start with an SDY accession")
            continue
        study = m.group(1)
        if only and study.upper() != only.upper():
            continue
        pmid = PINNED_PMIDS.get(path.name)
        cands = [d for d in registries if re.search(rf"_{study}(_pdf)?$", d.name)
                 and (pmid is None or d.name.startswith(f"{pmid}_"))]
        if len(cands) != 1:
            skipped.append(f"{path.name}: expected one registry for {study}, found {[d.name for d in cands]}")
            continue
        pairs.append({"study": study, "pmid": cands[0].name.split("_")[0],
                      "benchmark": path, "registry": cands[0]})
    return pairs, skipped


# ── comparing one paper ──────────────────────────────────────────────────────


#: The shared tiers, then two weaker ones only this script uses. `short_name` lets an acronym the
#: shared containment rule is too short for ("CFU") match as a whole word. `evidence` pairs two
#: entries that quote the same sentence even when their OBI terms are unrelated -- the shared quote
#: tier refuses that, which turned a real disagreement over the term into a MISSED plus an EXTRA.
PAIR_TIERS = TIERS + ["short_name", "evidence"]

#: Only a second agent entry on the very same term is a split of one assay. A child term is not:
#: SDY984's BD CBA (`antigen detection by cytometric bead array assay`) is a separate assay from
#: the Luminex panel the benchmark lists under `cytometric bead array assay`, and stays EXTRA.
_SPLIT_TIERS = ("obi_exact",)
#: Statuses whose pairing the ontology made, counted by `obi_recall`.
OBI_OK_STATUSES = {"MATCH", "MATCH_GRANULARITY"}

_SHORT = (3, 5)
_SENTENCE_MIN_WORDS = 8
_SENTENCE_OVERLAP = 0.8

_EXTRA_TIER_REASON = {
    "short_name": "paired by a short name",
    "evidence": "paired by a shared evidence sentence",
}

#: Signals that come from what the two sides called the assay. The quote-based ones are not:
#: a Methods sentence often names several assays, so one side's quote naming the other side's
#: assay, or a sentence both quoted, says the assays were described together, not that they are
#: one.
_NAME_SIGNALS = {"same name", "name containment", "short name"}
_TERM_TIERS = ("obi_exact", "obi_ancestry")


def is_term_only(hit: tuple[str, str | None, list[str]]) -> bool:
    """A pair the ontology made with nothing in the names or quotes to confirm it."""
    tier, _, signals = hit
    return tier in _TERM_TIERS and not (_NAME_SIGNALS & set(signals))


def pair_rank(hit: tuple[str, str | None, list[str]], strict: bool) -> tuple:
    """Sort key: smaller is taken first.

    Default: a name both sides use outranks a shared term, then the tier, then how many other
    signals agree. Strict adds one step: a term-only pair ranks below every pair that has a name
    signal, whatever its tier, so a curated row cannot be handed to the wrong agent entry on the
    same term while the entry it names is still free. A pair with no name signal and no shared
    term (a shared sentence alone) ranks below the term-only pair, since one Methods sentence
    often names several assays.
    """
    tier, _, signals = hit
    if not strict or _NAME_SIGNALS & set(signals):
        demote = 0
    elif tier in _TERM_TIERS:
        demote = 1
    else:
        demote = 2  # a shared sentence alone: the weakest evidence there is
    return ("same name" not in signals, demote, PAIR_TIERS.index(tier), -len(signals))


def _words(text: str) -> list[str]:
    return normalize(text or "").split()


def _bench_quote(bench: dict) -> str:
    return bench_evidence(bench).get("quote", "") or ""


def _our_quote(ours: dict) -> str:
    return (ours.get("evidence") or {}).get("quote", "") or ""


def _short_word_hit(forms: list[str], texts: list[str]) -> bool:
    """A 3-5 character form that appears as a whole word in any of `texts`."""
    words = [set(t.split()) for t in texts if t]
    return any(_SHORT[0] <= len(f) <= _SHORT[1] and " " not in f and any(f in w for w in words)
               for f in forms)


def _shared_sentence(a: str, b: str) -> bool:
    """Whether two quotes come from the same sentence: most of the shorter one is in the longer."""
    wa, wb = _words(a), _words(b)
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(short) < _SENTENCE_MIN_WORDS:
        return False
    pool = set(long_)
    return sum(w in pool for w in short) / len(short) >= _SENTENCE_OVERLAP


def pair_signals(bench: dict, ours: dict) -> list[str]:
    """Every independent piece of evidence, besides the OBI terms, that the two are one assay."""
    bench_forms = _surface_forms(bench["name_in_paper"], bench.get("aliases"))
    our_forms = _surface_forms(ours["name_in_paper"], ours.get("aliases"))
    bench_q, our_q = normalize(_bench_quote(bench)), normalize(_our_quote(ours))
    signals = []
    if set(bench_forms) & set(our_forms):
        signals.append("same name")
    if any(len(b) >= 6 and len(o) >= 6 and (b in o or o in b)
           for b in bench_forms for o in our_forms):
        signals.append("name containment")
    if (_short_word_hit(bench_forms, our_forms + [our_q])
            or _short_word_hit(our_forms, bench_forms + [bench_q])):
        signals.append("short name")
    if any(len(o) >= 6 and o in bench_q for o in our_forms) or \
            any(len(b) >= 6 and b in our_q for b in bench_forms):
        signals.append("quote names the other side")
    if _shared_sentence(_bench_quote(bench), _our_quote(ours)):
        signals.append("shared evidence sentence")
    return signals


def pair_score(bench: dict, bench_id: str | None, ours: dict, obi: ObiGraph) -> tuple[str, str | None, list[str]] | None:
    """(tier, detail, signals) for one (benchmark row, agent entry) pair, or None.

    The tier is the shared `match_tier` when it finds one, else one of the two weak tiers. The
    signals are what ranks two pairs on the same tier, so an ancestry match that also shares the
    quote and the name beats one that only shares an ancestor.
    """
    signals = pair_signals(bench, ours)
    hit = match_tier(bench, bench_id, ours, obi)
    if hit:
        return hit[0], hit[1], signals
    if "short name" in signals:
        return "short_name", None, signals
    if "shared evidence sentence" in signals:
        return "evidence", None, signals
    return None


def compare_paper(bench: dict, registry: Path, obi: ObiGraph, strict: bool = False) -> dict:
    """Score one paper, pairing each benchmark row with at most one agent entry.

    Every pair is scored, then pairs are taken strongest first -- by `pair_rank` -- and each side
    is used once. The shared algorithm let every benchmark row claim every agent entry on its
    best tier, so one entry could be counted under two rows while its real partner showed as
    EXTRA. An agent entry left over on the same OBI term as an already-paired row is that row's
    SPLIT; anything else left over is EXTRA.

    `strict` skips the leftover fold and demotes term-only pairs (module docstring).
    """
    ours = json.loads((registry / "assays_benchmark.json").read_text(encoding="utf-8"))
    ours_obi = json.loads((registry / "assays_OBI.json").read_text(encoding="utf-8"))
    our_rows = {key: {**our_row(key, entry, ours_obi.get(key, {})),
                      "generate_claim": entry.get("generate_claim")}
                for key, entry in ours.items()}
    bench_keys, our_keys = list(bench), list(our_rows)

    scored = []
    for bi, bench_key in enumerate(bench_keys):
        for oi, our_key in enumerate(our_keys):
            hit = pair_score(bench[bench_key], bench[bench_key]["obi_id"], our_rows[our_key], obi)
            if hit:
                # A name both sides use outranks a shared term: the curator's "CFSE labeling" is
                # filed under `flow cytometry assay`, and would otherwise take the agent's flow
                # cytometry entry on the term before reaching the agent's own "CFSE labeling".
                scored.append((pair_rank(hit, strict), bi, oi, hit))
    scored.sort(key=lambda t: t[:3])

    assigned: dict[str, list[tuple[str, tuple]]] = {}
    used: set[str] = set()
    for _, bi, oi, hit in scored:
        bench_key, our_key = bench_keys[bi], our_keys[oi]
        if bench_key in assigned or our_key in used:
            continue
        assigned[bench_key] = [(our_key, hit)]
        used.add(our_key)
    for _, bi, oi, hit in scored:
        bench_key, our_key = bench_keys[bi], our_keys[oi]
        if our_key in used or bench_key not in assigned or hit[0] not in _SPLIT_TIERS:
            continue
        assigned[bench_key].append((our_key, hit))
        used.add(our_key)
    term_only = sum(is_term_only(pairs[0][1]) for pairs in assigned.values())

    # A benchmark row left without a partner, on the same curated term as a row that was paired,
    # is one more panel of that assay -- SDY1289's four flow cytometry panels against the agent's
    # one entry, or its two microarray rows against the agent's one array entry on another term --
    # and folds into it rather than reading as MISSED. Only leftovers fold, so a row that found
    # its own partner is never swallowed.
    folded: dict[str, list[str]] = {}
    for bench_key in bench_keys:
        bench_id = bench[bench_key]["obi_id"]
        if strict or bench_key in assigned or not bench_id:
            continue
        host = next((k for k in bench_keys if k in assigned and bench[k]["obi_id"] == bench_id), None)
        if host:
            folded.setdefault(host, []).append(bench_key)
    gone = {k for members in folded.values() for k in members}
    bench = {k: fold_rows([(k, bench[k])] + [(m, bench[m]) for m in folded.get(k, [])])
             for k in bench_keys if k not in gone}

    rows: list[dict] = []
    for bench_key, entry in bench.items():
        bench_id = entry["obi_id"]
        bench_side = {
            "key": bench_key,
            "obi_id": bench_id,
            "obi_label": obi.label_of.get(bench_id) if bench_id else None,
            "name_in_paper": entry["name_in_paper"],
            "aliases": entry.get("aliases", []),
            "merged_from": entry["merged_from"],
            "generate_claim": entry.get("generate_claim"),
            "quotes": entry["quotes"],
        }
        pairs = assigned.get(bench_key)
        if not pairs:
            rows.append({"status": "MISSED", "tier": None, "signals": [],
                         "reason": "no agent entry matches this benchmark assay",
                         "benchmark": bench_side, "ours": []})
            continue
        tier, detail, signals = pairs[0][1]
        matches = [our_rows[k] for k, _ in pairs]
        # The status is the one-to-one pair's. The other agent entries on the same term ride
        # along as `also_on_term`: the evidence still renders, the count is reported, and the
        # pair's own MATCH is no longer hidden behind a SPLIT status.
        status, reason = status_for(tier, detail, bench_id, matches[:1], obi)
        if tier in _EXTRA_TIER_REASON:
            reason = f"{_EXTRA_TIER_REASON[tier]}; {reason}"
        if is_term_only(pairs[0][1]):
            reason += "; term-only pair: no shared name, alias or quote confirms it"
        also = [k for k, _ in pairs[1:]]
        if also:
            reason += f"; {len(also)} more agent entr{'y' if len(also) == 1 else 'ies'} on this term: " \
                      + ", ".join(f"`{k}`" for k in also)
        rows.append({"status": status, "tier": tier, "signals": signals, "reason": reason,
                     "benchmark": bench_side, "ours": matches, "also_on_term": also})

    for key, row in our_rows.items():
        if key not in used:
            rows.append({"status": "EXTRA", "tier": None, "signals": [],
                         "reason": "agent found it in the paper; the benchmark does not list it",
                         "benchmark": None, "ours": [row]})

    matched = sum(r["status"] in MATCHED_STATUSES for r in rows)
    return {
        "metrics": {
            "benchmark_total": len(bench),
            "ours_total": len(ours),
            "matched": matched,
            "exact": sum(r["status"] == "MATCH" for r in rows),
            # Paired by the ontology: the same term, or one an ancestor of the other. A pair the
            # names made (CONFLICT, UNMAPPED) is a found assay on a wrong or missing term.
            "obi_ok": sum(r["status"] in OBI_OK_STATUSES for r in rows),
            "missed": sum(r["status"] == "MISSED" for r in rows),
            "extra": sum(r["status"] == "EXTRA" for r in rows),
            # Rows paired one-to-one that have further agent entries on the same term.
            "split": sum(bool(r.get("also_on_term")) for r in rows),
            # Pairs the ontology alone made (same term or parent/child, no name or quote signal).
            "term_only_pairs": term_only,
            "recall": round(matched / len(bench), 4) if bench else None,
        },
        "merged_groups": [v["merged_from"] for v in bench.values() if len(v["merged_from"]) > 1],
        "rows": rows,
    }


# ── HTML ─────────────────────────────────────────────────────────────────────

STATUS_INFO = {
    "MATCH": ("match", "Same OBI term on both sides"),
    "MATCH_GRANULARITY": ("gran", "Same assay; one OBI term is a parent/child of the other"),
    "MATCH_OBI_CONFLICT": ("conflict", "Paired by name, but the two sides chose different OBI terms"),
    "MATCH_OBI_UNMAPPED": ("unmapped", "Paired by name, but one side has no OBI term"),
    "SPLIT": ("split", "Paired one-to-one, and more agent entries sit on the same term (an annotation on a MATCH row)"),
    "MISSED": ("missed", "In the benchmark, not found by the agent"),
    "EXTRA": ("extra", "Found by the agent, not in the benchmark"),
}

e = html.escape


def _obi(obi_id: str | None, label: str | None) -> str:
    if not obi_id:
        return '<span class="noobi">no OBI term</span>'
    return f'<span class="obi"><code>{e(obi_id)}</code> {e(label or "?")}</span>'


def _claim(v) -> str:
    return {True: "claim ✓", False: "claim ✗"}.get(v, "claim ?")


def _bench_cell(b: dict | None) -> str:
    if not b:
        return '<span class="dash">—</span>'
    parts = [f'<div class="key">{e(b["key"])}</div>', _obi(b["obi_id"], b["obi_label"])]
    if len(b["merged_from"]) > 1:
        chips = "".join(f'<span class="chip">{e(n)}</span>' for n in b["merged_from"])
        parts.append(f'<div class="merged"><span class="tag">merged {len(b["merged_from"])}</span>{chips}</div>')
    else:
        names = [n for n in _names(b["name_in_paper"]) if n != b["key"]]
        if names:
            parts.append(f'<div class="sub">paper: {e("; ".join(names))}</div>')
    if b["aliases"]:
        parts.append(f'<div class="sub">aliases: {e("; ".join(b["aliases"]))}</div>')
    parts.append(f'<div class="sub">{_claim(b.get("generate_claim"))}</div>')
    return "".join(parts)


def _ours_cell(ours: list[dict]) -> str:
    if not ours:
        return '<span class="dash">—</span>'
    blocks = []
    for o in ours:
        parts = [f'<div class="key">{e(o["key"])}</div>', _obi(o["obi_id"], o["obi_label"])]
        names = [n for n in _names(o["name_in_paper"]) if n != o["key"]]
        if names:
            parts.append(f'<div class="sub">paper: {e("; ".join(names))}</div>')
        if o.get("aliases"):
            parts.append(f'<div class="sub">aliases: {e("; ".join(o["aliases"]))}</div>')
        parts.append(f'<div class="sub">{_claim(o.get("generate_claim"))} · source: {e(o.get("source") or "?")}</div>')
        blocks.append(f'<div class="ours-one">{"".join(parts)}</div>')
    return "".join(blocks)


def _evidence_cell(row: dict) -> str:
    items = []
    if row["benchmark"]:
        for q in row["benchmark"]["quotes"]:
            src = f' ({e(q["from"])})' if q.get("from") else ""
            items.append(f'<div class="q"><b>Benchmark{src}</b> · {e(q.get("section") or "?")}'
                         f'<blockquote>{e(q.get("quote") or "")}</blockquote></div>')
    for o in row["ours"]:
        ev = o.get("evidence") or {}
        sids = ", ".join(ev.get("sentence_ids") or [])
        items.append(f'<div class="q"><b>Agent ({e(o["key"])})</b> · {e(ev.get("section") or "?")}'
                     + (f" · {e(sids)}" if sids else "")
                     + f'<blockquote>{e(ev.get("quote") or "")}</blockquote></div>')
    return f'<details><summary>evidence ({len(items)})</summary>{"".join(items)}</details>'


def overall_totals(papers: list[dict]) -> dict:
    """Corpus-wide counts and rates over every scored paper.

    `status_counts` counts comparison rows by status, so MATCH..SPLIT and MISSED are benchmark
    rows and EXTRA is agent rows. Precision is matched / agent assays; `obi_exact_rate` is the
    share of matched assays that landed on the identical OBI term, and `obi_recall` the share of
    benchmark assays the ontology paired (MATCH or MATCH_GRANULARITY): a row the names paired
    carries a different or missing term and does not count. A zero denominator gives 0.0.
    """
    def ratio(num: float, den: float) -> float:
        return num / den if den else 0.0

    totals = {
        "benchmark_raw": sum(p["benchmark_raw_total"] for p in papers),
        **{k: sum(p["metrics"][k] for p in papers)
           for k in ("benchmark_total", "ours_total", "matched", "exact", "obi_ok", "missed", "extra")},
        "status_counts": {s: sum(r["status"] == s for p in papers for r in p["rows"])
                          for s in STATUS_INFO},
    }
    # SPLIT is an annotation now, not a status: the column counts rows that carry one.
    totals["status_counts"]["SPLIT"] = sum(bool(r.get("also_on_term")) for p in papers for r in p["rows"])
    totals["split"] = totals["status_counts"]["SPLIT"]
    # A report written before the counter existed reads as 0.
    totals["term_only_pairs"] = sum(p["metrics"].get("term_only_pairs", 0) for p in papers)
    totals["recall"] = ratio(totals["matched"], totals["benchmark_total"])
    totals["precision"] = ratio(totals["matched"], totals["ours_total"])
    totals["f1"] = ratio(2 * totals["precision"] * totals["recall"],
                         totals["precision"] + totals["recall"])
    totals["obi_exact_rate"] = ratio(totals["exact"], totals["matched"])
    totals["obi_recall"] = ratio(totals["obi_ok"], totals["benchmark_total"])
    return totals


def _obi_recall(m: dict) -> float:
    """Per-paper OBI recall; a report written before `obi_ok` existed falls back to `exact`."""
    ok = m.get("obi_ok", m.get("exact", 0))
    return ok / m["benchmark_total"] if m.get("benchmark_total") else 0.0


def parse_arms_table(text: str, mode: str = "strict") -> dict[str, dict[str, str]]:
    """{row label: {column name: cell}} for one scorer mode's table in `arms_table.md`."""
    head, _, rest = text.partition(f"## Scorer mode: {mode}")
    if not _:
        return {}
    section = rest.split("## Scorer mode")[0]
    columns: list[str] = []
    out: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not columns:
            columns = cells[1:]          # the header row: first cell is "metric"
        else:
            out.setdefault(cells[0], dict(zip(columns, cells[1:])))
    return out


def baselines_html(agent_live: dict | None = None, path: Path = BASELINES_PATH,
                   mode: str = "default") -> str:
    """The comparison-arms table, with one line on what each arm is. "" if the scores are absent.

    `mode` follows the page's own scorer mode, so the arms are always scored the way the rows
    above them were. The two modes rank the arms identically and differ by at most 0.3 points of
    F1 on any of them; what differs is one curated row for the agent (SDY1669, where the curators
    wrote one flow measurement as two rows — `docs/benchmark_v5_vs_agent_v1_adjudication.md`).

    `agent_live` is the running report's `totals`. The arms table's agent column is built from the
    same report, so the two normally agree; when they do not, the page says so rather than show a
    stale column beside fresh per-paper rows.
    """
    try:
        table = parse_arms_table(path.read_text(encoding="utf-8"), mode)
    except OSError:
        return ""
    if not table:
        return ""

    stale = ""
    if agent_live is not None:
        want = str(agent_live.get("exact", ""))
        got = (table.get("exact (same OBI term as curator)") or {}).get("agent")
        if got and got != want:
            stale = ('<p class="note warn">The arms table\'s agent column reads '
                     f'{e(got)} exact where this run scored {e(want)}. Rebuild it with '
                     '<code>experiment/common/compare_arms.py</code>.</p>')

    heads = "".join(f'<th{" class=self" if col == "agent" else ""}>{e(name)}</th>'
                    for col, name, _ in BASELINE_ARMS)
    # The denominator is the mode's own row count, not a constant: default folds leftovers away.
    denom = (table.get("curated rows") or {}).get("agent", "158")
    body = []
    for key, label, tip in BASELINE_ROWS:
        row = table.get(key)
        if not row:
            continue
        label, tip = label.replace("158", denom), tip.replace("158", denom)
        cells = "".join(
            f'<td class="n{" self" if col == "agent" else ""}">{e(row.get(col, "—"))}</td>'
            for col, _, _ in BASELINE_ARMS)
        body.append(f'<tr><th title="{e(tip)}">{e(label)}</th>{cells}</tr>')
    arms = "".join(f'<dt>{e(name)}</dt><dd>{e(what)}</dd>' for _, name, what in BASELINE_ARMS)
    try:
        source = str(path.relative_to(REPO_ROOT))
    except ValueError:
        source = str(path)
    rows_label = "158 curated rows" if mode == "strict" else "157 curated rows (raw 158)"
    same = ('A curated row left without a partner is MISSED whatever term it carries, and a pair '
            'the ontology alone made is taken only when nothing better claims either side.'
            if mode == "strict" else
            'A curated row left without a partner folds into a paired row on the same OBI term, '
            'as in the rows above. The two modes rank these arms identically and differ by at '
            'most 0.3 points of F1 on any of them.')
    return (
        '<h2 style="margin-top:28px">Against other tools '
        f'<span class="sub">{mode} scorer · 31 papers · {rows_label}</span></h2>'
        '<p class="sub">Every arm writes the same two registry files per paper and is scored by '
        f'this same code, in the mode this page uses. {same} Source: '
        f'<code>{e(source)}</code>, rebuilt by '
        '<code>experiment/common/compare_arms.py</code>; write-up: '
        '<code>docs/assay_agent_vs_baselines.md</code>.</p>'
        f'{stale}'
        f'<div class="wrap"><table class="arms"><thead><tr><th>metric</th>{heads}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
        f'<details class="arms-what"><summary>What each arm is</summary><dl>{arms}</dl></details>'
    )


def render_html(report: dict) -> str:
    t = report["totals"]
    strict = report.get("mode") == "strict"
    summary_rows = []
    sections = []
    for p in report["papers"]:
        m = p["metrics"]
        anchor = f'{p["study"]}_{p["pmid"]}'
        flags = []
        if p["merged_groups"]:
            flags.append(f'<span class="tag">merged {sum(len(g) for g in p["merged_groups"])}→{len(p["merged_groups"])}</span>')
        if p["repair"]:
            flags.append('<span class="tag warn" title="%s">JSON repaired</span>' % e(p["repair"]))
        counts = {s: sum(r["status"] == s for r in p["rows"]) for s in STATUS_INFO}
        counts["SPLIT"] = sum(bool(r.get("also_on_term")) for r in p["rows"])
        summary_rows.append(
            f'<tr onclick="location.hash=\'{anchor}\'"><td><a href="#{anchor}">{p["study"]}</a></td><td>{p["pmid"]}</td>'
            f'<td class="n">{m["benchmark_total"]}</td><td class="n">{m["ours_total"]}</td>'
            + "".join(f'<td class="n {STATUS_INFO[s][0]}-c">{counts[s] or ""}</td>' for s in STATUS_INFO)
            + f'<td class="n"><b>{m["recall"]:.0%}</b></td>'
            + f'<td class="n">{_obi_recall(m):.0%}</td><td>{" ".join(flags)}</td></tr>'
        )
        body = []
        for r in p["rows"]:
            cls = STATUS_INFO[r["status"]][0]
            body.append(
                f'<tr class="row" data-status="{r["status"]}">'
                f'<td><span class="badge {cls}">{r["status"].replace("_", " ")}</span>'
                + (f'<div class="sub"><span class="tag">split {len(r["also_on_term"])}</span></div>'
                   if r.get("also_on_term") else "")
                + f'<div class="sub">{e(r["tier"] or "")}</div>'
                + (f'<div class="sub">{e("; ".join(r.get("signals") or []))}</div>' if r.get("signals") else "")
                + '</td>'
                f'<td>{_bench_cell(r["benchmark"])}</td><td>{_ours_cell(r["ours"])}</td>'
                f'<td class="reason">{e(r["reason"])}</td><td>{_evidence_cell(r)}</td></tr>'
            )
        note = f'<p class="note warn">Benchmark JSON was invalid; {e(p["repair"])}. File not modified.</p>' if p["repair"] else ""
        sections.append(
            f'<section class="paper" id="{anchor}"><h2>{p["study"]} <span class="pmid">PMID {p["pmid"]}</span></h2>'
            f'<p class="meta">benchmark <b>{m["benchmark_total"]}</b> (after merge) · agent <b>{m["ours_total"]}</b> · '
            f'matched <b>{m["matched"]}</b> (exact OBI {m["exact"]}) · missed <b>{m["missed"]}</b> · '
            f'extra <b>{m["extra"]}</b> · recall <b>{m["recall"]:.0%}</b> · '
            f'OBI recall <b>{_obi_recall(m):.0%}</b></p>'
            f'<p class="files"><code>{e(p["benchmark_file"])}</code> vs <code>{e(p["registry_dir"])}</code></p>{note}'
            f'<table class="cmp"><thead><tr><th>Status</th><th>Benchmark assay</th><th>Agent assay</th>'
            f'<th>Why</th><th>Evidence</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>'
        )

    legend = "".join(f'<label><input type="checkbox" class="flt" value="{s}" {"" if s == "MATCH" else "checked"}>'
                     f'<span class="badge {c}">{s.replace("_", " ")}</span> <span class="sub">{e(d)}</span></label>'
                     for s, (c, d) in STATUS_INFO.items())
    notes = "".join(f"<li>{e(s)}</li>" for s in t["skipped"])
    nobench = ", ".join(t["registries_without_benchmark"]) or "none"
    label = Path(report["benchmark_dir"]).name
    # A report written before status_counts existed is recounted from its rows.
    status_counts = t.get("status_counts") or {
        s: sum(r["status"] == s for p in report["papers"] for r in p["rows"]) for s in STATUS_INFO}
    status_counts["SPLIT"] = sum(bool(r.get("also_on_term")) for p in report["papers"] for r in p["rows"])
    # The two rate tiles, written out as the sum they are. Both denominators are the benchmark,
    # so what separates them is only which statuses the numerator admits.
    obi_ok_n = t.get("obi_ok", t["exact"])
    gap = t["matched"] - obi_ok_n
    rates = (
        '<div class="rates">'
        f'<p><b>recall</b> = matched &divide; benchmark assays = '
        f'<code>{t["matched"]} / {t["benchmark_total"]}</code> = <b>{t["recall"]:.1%}</b>'
        '<br><span class="sub">A benchmark row counts as matched once the scorer pairs it with an '
        'agent entry on any tier, whether or not the two agree on a term: '
        f'MATCH ({status_counts["MATCH"]}) + MATCH GRANULARITY ({status_counts["MATCH_GRANULARITY"]})'
        f' + MATCH OBI CONFLICT ({status_counts["MATCH_OBI_CONFLICT"]})'
        f' + MATCH OBI UNMAPPED ({status_counts["MATCH_OBI_UNMAPPED"]}) = {t["matched"]}. '
        'Only MISSED, a row no tier could pair, lowers it.</span></p>'
        f'<p><b>OBI recall</b> = ontology-paired &divide; benchmark assays = '
        f'<code>({status_counts["MATCH"]} + {status_counts["MATCH_GRANULARITY"]})'
        f' / {t["benchmark_total"]}</code> = <code>{obi_ok_n} / {t["benchmark_total"]}</code>'
        f' = <b>{t["obi_recall"]:.1%}</b>'
        '<br><span class="sub">Only a pairing the ontology itself made counts: the same term '
        '(MATCH), or one term a parent or child of the other (MATCH GRANULARITY). A row paired by '
        'a shared name or quote carries a different or missing term, so CONFLICT and UNMAPPED '
        f'count toward recall and not here &mdash; that gap is the {gap} '
        f'{"row" if gap == 1 else "rows"} between the two tiles.</span></p>'
        + (f'<p class="sub">Strict mode: both denominators are the {t["benchmark_raw"]} rows the '
           'curators wrote. A curated row left without a partner is MISSED even when another row on '
           f'the same term was paired, and the {t.get("term_only_pairs", 0)} pairs the ontology '
           'alone made were taken only after every pair the names made.</p>'
           if strict else
           f'<p class="sub">Both denominators are {t["benchmark_total"]}, not the '
           f'{t["benchmark_raw"]} rows the curators wrote: a curated row left without a partner '
           'folds into a paired row on the same OBI id within the paper. '
           f'{t.get("term_only_pairs", 0)} pairs were made by the ontology alone, with no shared '
           'name, alias or quote.</p>')
        + '</div>'
    )
    baselines = baselines_html(t, mode="strict" if strict else "default")
    total_row = (
        f'<tr><td>Total</td><td>{t["papers"]} papers</td>'
        f'<td class="n">{t["benchmark_total"]}</td><td class="n">{t["ours_total"]}</td>'
        + "".join(f'<td class="n {c}-c">{status_counts[s] or ""}</td>' for s, (c, _) in STATUS_INFO.items())
        + f'<td class="n">{t["recall"]:.0%}</td><td class="n">{t.get("obi_recall", 0):.0%}</td><td></td></tr>'
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assay Benchmark Review</title>
<style>
:root{{--bg:#fbfaf8;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e2dc;--code:#f3f1ec;
--match:#1a7f37;--gran:#0969da;--conflict:#bc4c00;--unmapped:#8250df;--split:#9a6700;--missed:#cf222e;--extra:#57606a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e}}}}
:root[data-theme="dark"]{{--bg:#16181c;--fg:#e6e6e6;--muted:#9aa0a6;--card:#1e2126;--line:#2e3238;--code:#262a30;
--match:#3fb950;--gran:#58a6ff;--conflict:#f0883e;--unmapped:#bc8cff;--split:#d29922;--missed:#ff7b72;--extra:#8b949e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:24px 16px 80px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:18px;margin:0 0 4px}}
.pmid,.sub,.meta,.files{{color:var(--muted);font-size:12px}} .meta{{font-size:13px}}
code{{background:var(--code);padding:0 4px;border-radius:4px;font-size:12px}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:120px}}
.kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--muted);font-size:12px}}
.rates{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:0 0 16px}}
.rates p{{margin:6px 0;font-size:13px;line-height:1.5}}
.rates code{{background:var(--code);padding:1px 5px;border-radius:4px}}
.rates .sub{{color:var(--muted)}}
.toolbar{{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}}
.toolbar label{{display:inline-flex;gap:4px;align-items:center;cursor:pointer}}
.toolbar label .sub{{display:none}}
.toolbar input[type=search]{{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);min-width:220px}}
.toolbar button{{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}}
.wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:8px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
th{{font-size:12px;color:var(--muted);font-weight:600;background:var(--code)}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.summary tbody tr{{cursor:pointer}} .summary tbody tr:hover{{background:var(--code)}}
.summary tfoot td{{font-weight:700;border-top:2px solid var(--line);background:var(--code)}}
.paper{{margin-top:36px;scroll-margin-top:60px}}
.cmp td:nth-child(1){{width:120px}} .cmp td:nth-child(2),.cmp td:nth-child(3){{width:26%}} .cmp td:nth-child(4){{width:18%}}
.badge{{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff;white-space:nowrap}}
.match{{background:var(--match)}}.gran{{background:var(--gran)}}.conflict{{background:var(--conflict)}}.unmapped{{background:var(--unmapped)}}
.split{{background:var(--split)}}.missed{{background:var(--missed)}}.extra{{background:var(--extra)}}
.match-c{{color:var(--match)}}.gran-c{{color:var(--gran)}}.conflict-c{{color:var(--conflict)}}.unmapped-c{{color:var(--unmapped)}}
.split-c{{color:var(--split)}}.missed-c{{color:var(--missed)}}.extra-c{{color:var(--extra)}}
tr[data-status=MISSED]{{box-shadow:inset 3px 0 var(--missed)}} tr[data-status=EXTRA]{{box-shadow:inset 3px 0 var(--extra)}}
tr[data-status=MATCH_OBI_CONFLICT]{{box-shadow:inset 3px 0 var(--conflict)}}
.key{{font-weight:600}} .obi{{font-size:12px}} .noobi{{font-size:12px;color:var(--missed);font-style:italic}}
.ours-one+.ours-one{{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}}
.tag{{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--line);margin-right:4px;background:var(--code)}}
.tag.warn,.note.warn{{color:var(--conflict)}}
.merged{{margin-top:4px}} .chip{{display:inline-block;font-size:11px;background:var(--code);border-radius:4px;padding:1px 6px;margin:2px 3px 0 0}}
.dash{{color:var(--muted)}} .reason{{font-size:13px}}
details summary{{cursor:pointer;color:var(--gran);font-size:12px}}
blockquote{{margin:4px 0 8px;padding:4px 8px;border-left:3px solid var(--line);color:var(--muted);font-size:12px;max-height:180px;overflow:auto}}
.q b{{font-size:12px}}
.hidden{{display:none}}
.arms th:first-child{{text-align:left;font-weight:600;color:var(--fg);background:var(--card);white-space:nowrap}}
.arms thead th{{background:var(--code);white-space:nowrap}}
.arms th.self,.arms td.self{{background:color-mix(in srgb,var(--match) 12%,transparent);font-weight:700}}
.arms thead th.self{{color:var(--match)}}
.arms td{{white-space:nowrap}}
.arms-what{{margin-top:10px}}
.arms-what dl{{margin:8px 0 0}} .arms-what dt{{font-weight:700;margin-top:10px}}
.arms-what dd{{margin:2px 0 0;color:var(--muted);max-width:90ch}}
</style></head><body><main>
<h1>Assay benchmark {e(label)} vs. agent{" — strict" if strict else ""}</h1>
<p class="sub">Benchmark: <code>{e(report["benchmark_dir"])}</code> · Agent: <code>{e(report["registry_dir"])}</code> ·
{"strict mode: no leftover fold, term-only pairs taken last" if strict else
 "a curated row left unpaired folds into a paired row on the same OBI id within the paper"}.</p>
<div class="kpis">
<div class="kpi"><b>{t["papers"]}</b><span>papers scored</span></div>
<div class="kpi"><b>{t["benchmark_total"]}</b><span>benchmark assays (raw {t["benchmark_raw"]})</span></div>
<div class="kpi"><b>{t["ours_total"]}</b><span>agent assays</span></div>
<div class="kpi"><b>{t["matched"]}</b><span>matched (exact OBI {t["exact"]})</span></div>
<div class="kpi"><b>{t["missed"]}</b><span>missed</span></div>
<div class="kpi"><b>{t["extra"]}</b><span>extra</span></div>
<div class="kpi" title="matched / benchmark assays — every matched tier counts; only MISSED lowers it"><b>{t["recall"]:.1%}</b><span>recall</span></div>
<div class="kpi" title="(MATCH + MATCH GRANULARITY) / benchmark assays — only a pairing the ontology made"><b>{t.get("obi_recall", 0):.1%}</b><span>OBI recall (same or parent/child term)</span></div>
</div>
{rates}
<details><summary>Status legend &amp; notes</summary>
<ul>{"".join(f'<li><span class="badge {c}">{s.replace("_", " ")}</span> {e(d)}</li>' for s, (c, d) in STATUS_INFO.items())}</ul>
<p>Agent registries with no {e(label)} benchmark (not scored): {e(nobench)}</p>
{f"<p>Skipped benchmark files:</p><ul>{notes}</ul>" if notes else ""}
<p>The benchmark is a recall reference, not an exhaustive list, so EXTRA rows are candidates for curator review rather than errors.</p>
</details>
{baselines}
<h2 style="margin-top:28px">Per paper</h2>
<div class="wrap"><table class="summary"><thead><tr><th>Study</th><th>PMID</th><th>Bench</th><th>Agent</th>
{"".join(f'<th class="{c}-c">{s.replace("MATCH_", "").replace("_", " ")}</th>' for s, (c, _) in STATUS_INFO.items())}
<th>Recall</th><th title="same or parent/child OBI term">OBI recall</th><th>Notes</th></tr></thead><tbody>{"".join(summary_rows)}</tbody>
<tfoot>{total_row}</tfoot></table></div>
<div class="toolbar">{legend}
<input type="search" id="q" placeholder="Search assay, OBI, quote…">
<button id="exp">Expand evidence</button><button id="theme">Theme</button>
<span class="sub" id="cnt"></span></div>
{"".join(sections)}
</main>
<script>
const rows=[...document.querySelectorAll('tr.row')];
function apply(){{
  const on=new Set([...document.querySelectorAll('.flt:checked')].map(x=>x.value));
  const q=document.getElementById('q').value.trim().toLowerCase();
  let n=0;
  rows.forEach(r=>{{const ok=on.has(r.dataset.status)&&(!q||r.textContent.toLowerCase().includes(q));r.classList.toggle('hidden',!ok);if(ok)n++;}});
  document.querySelectorAll('section.paper').forEach(s=>s.classList.toggle('hidden',!s.querySelector('tr.row:not(.hidden)')));
  document.getElementById('cnt').textContent=n+' rows shown';
}}
document.querySelectorAll('.flt').forEach(x=>x.addEventListener('change',apply));
document.getElementById('q').addEventListener('input',apply);
let open=false;
document.getElementById('exp').onclick=e=>{{open=!open;document.querySelectorAll('.cmp details').forEach(d=>d.open=open);e.target.textContent=open?'Collapse evidence':'Expand evidence';}};
document.getElementById('theme').onclick=()=>{{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';}};
apply();
</script></body></html>
"""


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="Restrict to one study accession, e.g. SDY1289")
    parser.add_argument("--benchmark-dir", type=Path, default=BENCHMARK_DIR,
                        help="Folder of curated benchmark JSON files (default: Benchmark_assays_v2)")
    parser.add_argument("--out-stem", default=OUT_STEM, help="Output filename stem under comparison/")
    parser.add_argument("--registry-dir", type=Path, default=None,
                        help="Score the registries under this folder instead of the default "
                             f"({REGISTRY_DIR.relative_to(REPO_ROOT)}); the report then goes to "
                             "<registry-dir>/comparison/")
    parser.add_argument("--strict", action="store_true",
                        help="No leftover fold and term-only pairs taken last (module docstring); "
                             "the report stem gets a `_strict` suffix unless --out-stem is given")
    args = parser.parse_args()
    if args.registry_dir is not None:
        use_registry_dir(args.registry_dir)
    benchmark_dir = args.benchmark_dir.resolve()
    out_stem = args.out_stem
    if args.strict and out_stem == OUT_STEM:
        out_stem = f"{OUT_STEM}_strict"

    obi = ObiGraph()
    pairs, skipped = discover_pairs(args.only, benchmark_dir)
    papers = []
    for pair in pairs:
        raw, repair, error = load_lenient(pair["benchmark"])
        if raw is None:
            skipped.append(f"{pair['benchmark'].name}: unparseable JSON ({error})")
            continue
        result = compare_paper(prepare_benchmark(raw, obi), pair["registry"], obi, strict=args.strict)
        papers.append({
            "study": pair["study"],
            "pmid": pair["pmid"],
            "benchmark_file": str(pair["benchmark"].relative_to(REPO_ROOT)),
            "registry_dir": str(pair["registry"].relative_to(REPO_ROOT)),
            "repair": repair,
            "benchmark_raw_total": len(raw),
            **result,
        })

    scored = {p["registry_dir"].rsplit("/", 1)[-1] for p in papers}
    all_regs = sorted(d.name for d in REGISTRY_DIR.iterdir() if d.is_dir())
    totals = {
        "papers": len(papers),
        "skipped": skipped,
        "registries_without_benchmark": [] if args.only else [r for r in all_regs if r not in scored],
        **overall_totals(papers),
    }
    report = {
        "mode": "strict" if args.strict else "default",
        "benchmark_dir": str(benchmark_dir.relative_to(REPO_ROOT)),
        "registry_dir": str(REGISTRY_DIR.relative_to(REPO_ROOT)),
        "totals": totals,
        "papers": papers,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{out_stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT_DIR / f"{out_stem}.html").write_text(render_html(report), encoding="utf-8")

    print(f"scored {len(papers)}/{len(list(benchmark_dir.glob('*.json')))} benchmark files"
          f" [{report['mode']}]")
    for s in skipped:
        print(f"  SKIPPED  {s}")
    for p in papers:
        if p["repair"]:
            print(f"  REPAIRED {Path(p['benchmark_file']).name}: {p['repair']}")
        for g in p["merged_groups"]:
            print(f"  MERGED   {p['study']}: {' + '.join(g)}")
    print(f"benchmark {totals['benchmark_total']} (raw {totals['benchmark_raw']}) | agent {totals['ours_total']} | "
          f"matched {totals['matched']} (exact {totals['exact']}) | missed {totals['missed']} | "
          f"extra {totals['extra']} | split {totals['split']} | term-only {totals['term_only_pairs']} | "
          f"recall {totals['recall']:.1%} | precision {totals['precision']:.1%} | "
          f"obi exact {totals['obi_exact_rate']:.1%}")
    for p in papers:
        m = p["metrics"]
        print(f"  {p['study']:<8} {p['pmid']}  bench {m['benchmark_total']:>2} agent {m['ours_total']:>2} "
              f"matched {m['matched']:>2} exact {m['exact']:>2} missed {m['missed']} extra {m['extra']:>2}"
              + (f" split {m['split']}" if m['split'] else ""))
    print(f"\nwrote {(OUT_DIR / out_stem).relative_to(REPO_ROOT)}.{{json,html}}")


if __name__ == "__main__":
    main()
