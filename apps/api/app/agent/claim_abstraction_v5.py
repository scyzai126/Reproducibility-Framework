"""Five-pass panel claim abstraction (prompts/claim_abstraction_prompt_v6.md).

The prompt document is the single source of truth: its fenced blocks are the system
prompts, parsed out at call time rather than copied into this module, so editing the
markdown changes the run. v5 (the original design doc) and v6 (the same architecture
carrying extract_claims_pdf.txt's content) share this module — they differ only in prompt
text, and either can be named via `prompt_file`.

    passes 1-3   per panel   prose -> draft, draft+legend -> claims, provenance audit
    passes 4-5   per paper   abstract coverage audit, cross-panel de-duplication

Passes 1 and 2 are self-consistency sampled: `runs` samples at temperature 1.0, keep the
sample whose claim count is the mode. Passes 3-5 are single deterministic calls.

Panels come from the paper's JATS XML: each <fig>/<table-wrap> is one panel, its legend is
the caption, and its prose is every Results paragraph that cross-references it.
"""

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree
from openai import AsyncOpenAI

from app.agent.claim_parser import CLAIM_TYPES_PLACEHOLDER, _load_prompt, _strip_fences

PROMPT_FILE = "claim_abstraction_prompt_v6.md"

#: The shared claim_type vocabulary, substituted per block — see load_v5_prompts.
CLAIM_TYPES_FILE = "claim_types.txt"

SAMPLED_TEMPERATURE = 1.0

# 79 calls fired at once would be rate-limited, and a 429 late in a panel discards the
# samples already paid for. Cap in-flight calls instead.
MAX_CONCURRENT_CALLS = 8

_HEADING_KEYS = {
    "SHARED PREAMBLE": "preamble",
    "PASS 1": "pass1",
    "PASS 2": "pass2",
    "PASS 3": "pass3",
    "PASS 4": "pass4",
    "PASS 5": "pass5",
}


def load_v5_prompts(filename: str = PROMPT_FILE) -> dict[str, str]:
    """Return {preamble, pass1..pass5} — the first fenced block under each `## ` heading.

    The claim_type vocabulary is substituted into each block AFTER the split, never before:
    claim_types.txt contains its own ``` fence around the precedence ladder, which would
    close the enclosing block early and silently truncate the preamble at that point. A
    document with no placeholder is used as-is — v5 carries its vocabulary inline.

    Raises if a heading or its block is missing: a silently absent pass role would still
    produce a runnable prompt (the preamble alone), and the run would look successful.
    """
    text = _load_prompt(filename)
    blocks: dict[str, str] = {}
    current: str | None = None
    fence: list[str] | None = None

    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = next((k for h, k in _HEADING_KEYS.items() if heading.startswith(h)), None)
            fence = None
            continue
        if current is None or current in blocks:
            continue
        if line.startswith("```"):
            if fence is None:
                fence = []
            else:
                blocks[current] = "\n".join(fence).strip()
                fence = None
            continue
        if fence is not None:
            fence.append(line)

    missing = [k for k in _HEADING_KEYS.values() if k not in blocks]
    if missing:
        raise ValueError(f"{filename}: no fenced prompt block for {', '.join(missing)}")

    if CLAIM_TYPES_PLACEHOLDER in text:
        vocabulary = _load_prompt(CLAIM_TYPES_FILE)
        blocks = {k: v.replace(CLAIM_TYPES_PLACEHOLDER, vocabulary) for k, v in blocks.items()}
        unresolved = [k for k, v in blocks.items() if CLAIM_TYPES_PLACEHOLDER in v]
        if unresolved:
            raise ValueError(f"{filename}: {CLAIM_TYPES_PLACEHOLDER} survived substitution")
    return blocks


def system_prompts(blocks: dict[str, str]) -> dict[str, str]:
    """Assemble the per-pass system prompts. Passes 1-2 carry the shared preamble; the
    audit passes (3-5) deliberately do not — they judge claims, they do not extract."""
    return {
        "pass1": blocks["preamble"] + "\n\n" + blocks["pass1"],
        "pass2": blocks["preamble"] + "\n\n" + blocks["pass2"],
        "pass3": blocks["pass3"],
        "pass4": blocks["pass4"],
        "pass5": blocks["pass5"],
    }


# ── JATS -> panels ────────────────────────────────────────────────────────────


@dataclass
class Panel:
    """One figure or table: its legend, and the Results prose that cites it."""

    panel_id: str
    label: str
    legend: str
    prose_paragraphs: list[str] = field(default_factory=list)

    @property
    def prose(self) -> str:
        return "\n\n".join(self.prose_paragraphs)


@dataclass
class PaperPanels:
    panels: list[Panel]
    abstract: str
    methods: str


def _text(node) -> str:
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _section_by_title(root, *wanted: str):
    """Return the first <sec> whose <title> starts with one of `wanted` (case-insensitive)."""
    for sec in root.iter("sec"):
        title = sec.find("title")
        if title is None:
            continue
        text = _text(title).lower().lstrip("0123456789. ")
        if any(text.startswith(w.lower()) for w in wanted):
            return sec
    return None


def split_panels(xml_text: str) -> PaperPanels:
    """Split a JATS article into panels, plus the abstract and Methods text.

    A Results paragraph is attached to every panel it cross-references, so a paragraph
    discussing two figures feeds both — the prompt reads one panel at a time and the
    paragraph is evidence for each.
    """
    root = etree.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)

    panels: dict[str, Panel] = {}
    for tag in ("fig", "table-wrap"):
        for node in root.iter(tag):
            pid = node.get("id")
            if not pid:
                continue
            label_node = node.find("label")
            caption = node.find("caption")
            legend_parts = []
            if label_node is not None:
                legend_parts.append(_text(label_node))
            if caption is not None:
                legend_parts.append(_text(caption))
            for foot in node.iter("table-wrap-foot"):
                legend_parts.append(_text(foot))
            panels[pid] = Panel(
                panel_id=pid,
                label=_text(label_node) if label_node is not None else pid,
                legend=" ".join(p for p in legend_parts if p),
            )

    results = _section_by_title(root, "results")
    if results is not None:
        for para in results.iter("p"):
            # A <p> inside a figure caption is the legend, not prose about the panel.
            if any(a.tag in ("fig", "table-wrap", "caption") for a in para.iterancestors()):
                continue
            cited = []
            for xref in para.iter("xref"):
                if xref.get("ref-type") not in ("fig", "table"):
                    continue
                for rid in (xref.get("rid") or "").split():
                    if rid in panels and rid not in cited:
                        cited.append(rid)
            text = _text(para)
            for rid in cited:
                panels[rid].prose_paragraphs.append(text)

    abstract_node = root.find(".//abstract")
    methods = _section_by_title(root, "methods", "on-line methods", "online methods", "materials and methods")

    return PaperPanels(
        panels=[p for p in panels.values()],
        abstract=_text(abstract_node) if abstract_node is not None else "",
        methods=_text(methods) if methods is not None else "",
    )


def build_pass1_user_message(panel: Panel, methods: str = "") -> str:
    """`RESULTS TEXT:\\n{prose}`, with Methods prepended when available.

    The preamble lets Methods fill the five provenance fields and nothing else, so it is
    labelled as such rather than merged into the results text. It leads rather than
    trails because it is byte-identical across every panel: ahead of the panel-specific
    prose it extends the cacheable prompt prefix, behind it caches nothing.
    """
    if not methods:
        return f"RESULTS TEXT:\n{panel.prose}"
    return (
        "METHODS (provenance fields only — assay, sample_type, cohort_n, timeframe, method; "
        f"never a finding and never a quote source):\n{methods}"
        f"\n\nRESULTS TEXT:\n{panel.prose}"
    )


# ── token accounting ──────────────────────────────────────────────────────────


@dataclass
class UsageTracker:
    """Per-pass token totals across a run.

    `cached` is the prefix-cache hit portion of `prompt` (already counted in it, billed at
    a discount) — reported separately so the caching change above is visible rather than
    assumed. Mutation happens between awaits on one event loop, so no lock is needed.
    """

    by_pass: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, label: str, usage) -> None:
        bucket = self.by_pass.setdefault(
            label, {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "total": 0}
        )
        bucket["calls"] += 1
        if usage is None:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        bucket["prompt"] += getattr(usage, "prompt_tokens", 0) or 0
        bucket["cached"] += getattr(details, "cached_tokens", 0) or 0
        bucket["completion"] += getattr(usage, "completion_tokens", 0) or 0
        bucket["total"] += getattr(usage, "total_tokens", 0) or 0

    def summary(self) -> dict:
        totals = {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "total": 0}
        for bucket in self.by_pass.values():
            for key in totals:
                totals[key] += bucket[key]
        return {"by_pass": dict(sorted(self.by_pass.items())), "total": totals}


# ── LLM passes ────────────────────────────────────────────────────────────────


async def _call_json(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float,
    tracker: UsageTracker | None = None,
    label: str = "",
    semaphore: asyncio.Semaphore | None = None,
) -> dict:
    async def _go():
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )
        # Record before parsing: a call whose JSON is malformed still cost its tokens.
        if tracker is not None:
            tracker.record(label, getattr(resp, "usage", None))
        return json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))

    if semaphore is None:
        return await _go()
    async with semaphore:
        return await _go()


def pick_modal(results: list[dict]) -> tuple[dict, dict, bool]:
    """Pick the sample whose claim count is the mode.

    Returns (sample, {count: n_samples}, decisive). Ties break toward the count seen first,
    and within a count toward the first sample — an arbitrary but reproducible choice,
    recorded in the returned tally either way.

    `decisive` is False when the winning count beat its runner-up by fewer than two samples.
    "More than half" is the wrong bar here: SDY1260 Figure 2 returned {2: 3, 10: 2}, a
    strict majority that nonetheless let a one-sample swing decide between 2 claims and 10.
    The mode is still used; the flag records that the panel's count was not determinate.
    """
    if not results:
        raise ValueError("no successful samples to choose from")
    counts = [len(r.get("claims", [])) for r in results]
    tally = Counter(counts)
    ranked = sorted(tally.values(), reverse=True)
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else 0
    modal_count = next(c for c in counts if tally[c] == best)
    chosen = next(r for r in results if len(r.get("claims", [])) == modal_count)
    return chosen, dict(sorted(tally.items())), best - runner_up >= 2


async def _sampled_pass(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    runs: int,
    tracker: UsageTracker | None = None,
    label: str = "",
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[dict, dict, list[str], bool]:
    """Run `runs` samples concurrently and keep the modal-claim-count one.

    A sample that comes back unparseable is dropped rather than aborting the panel: the
    mode is taken over whatever parsed, and the failures are returned for the run record.
    """
    temperature = SAMPLED_TEMPERATURE if runs > 1 else 0
    settled = await asyncio.gather(
        *(
            _call_json(client, model, system, user, temperature, tracker, label, semaphore)
            for _ in range(runs)
        ),
        return_exceptions=True,
    )
    parsed = [r for r in settled if not isinstance(r, BaseException)]
    errors = [f"{type(r).__name__}: {r}" for r in settled if isinstance(r, BaseException)]
    if not parsed:
        raise RuntimeError(f"all {runs} samples failed: {'; '.join(errors)}")
    chosen, tally, decisive = pick_modal(parsed)
    return chosen, tally, errors, decisive


async def run_panel(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    panel: Panel,
    methods: str = "",
    runs: int = 5,
    tracker: UsageTracker | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> dict:
    """Passes 1-3 for one panel. Returns {claims, not_a_claim, verdicts, run_record}."""
    pass1_user = build_pass1_user_message(panel, methods)
    draft, tally1, errors1, decisive1 = await _sampled_pass(
        client, model, prompts["pass1"], pass1_user, runs, tracker, "pass1", semaphore
    )

    pass2_user = (
        "DRAFT CLAIMS (from the results text alone):\n"
        f"{json.dumps(draft, indent=2, ensure_ascii=False)}\n\n"
        f"FIGURE LEGEND (not seen in pass 1):\n{panel.legend}"
    )
    final, tally2, errors2, decisive2 = await _sampled_pass(
        client, model, prompts["pass2"], pass2_user, runs, tracker, "pass2", semaphore
    )

    claims = final.get("claims", [])
    not_a_claim = final.get("not_a_claim", [])

    verdicts: list = []
    audit_error = None
    if claims:
        pass3_user = (
            f"CLAIMS:\n{json.dumps(claims, indent=2, ensure_ascii=False)}\n\n"
            f"FIGURE LEGEND:\n{panel.legend}"
        )
        try:
            audit = await _call_json(
                client, model, prompts["pass3"], pass3_user, 0, tracker, "pass3", semaphore
            )
            verdicts = audit.get("verdicts", [])
        except Exception as exc:  # the panel's claims are already extracted; keep them
            audit_error = f"{type(exc).__name__}: {exc}"

    return {
        "claims": claims,
        "not_a_claim": not_a_claim,
        "verdicts": verdicts,
        "run_record": {
            "panel": panel.label,
            "panel_id": panel.panel_id,
            "prose_paragraphs": len(panel.prose_paragraphs),
            "pass1_claim_counts": tally1,
            "pass2_claim_counts": tally2,
            # False means the winning claim count beat its runner-up by fewer than two
            # samples, so this panel's count turned on a near-tie rather than on agreement.
            "pass1_decisive": decisive1,
            "pass2_decisive": decisive2,
            "draft_claims": len(draft.get("claims", [])),
            "final_claims": len(claims),
            "sample_errors": errors1 + errors2,
            "audit_error": audit_error,
        },
    }


def apply_verdicts(claims: list[dict], verdicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Attach each pass-3 verdict to its claim and act on it.

    Only `demote_to_not_a_claim` is mechanical — it moves the claim out. `narrow_to_
    data_derived_part` needs a rewrite the audit pass is explicitly forbidden to make, so
    the claim stays and carries the verdict as a flag for a human.
    """
    by_text = {v.get("claim", ""): v for v in verdicts}
    kept: list[dict] = []
    demoted: list[dict] = []
    for claim in claims:
        verdict = by_text.get(claim.get("claim", ""))
        if verdict:
            claim["provenance_audit"] = verdict
        if verdict and verdict.get("action") == "demote_to_not_a_claim":
            demoted.append(
                {
                    "text": claim.get("claim", ""),
                    "reason": "external-import",
                    "identifiers": claim.get("targets", []),
                    "verifiable_alternative": None,
                    "from_provenance_audit": verdict,
                }
            )
            continue
        kept.append(claim)
    return kept, demoted


async def run_coverage_audit(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    abstract: str,
    claims: dict,
    tracker: UsageTracker | None = None,
) -> dict:
    """Pass 4 — abstract recall check over the pooled claim set."""
    listing = {k: v.get("claim", "") for k, v in claims.items()}
    user = (
        f"ABSTRACT:\n{abstract}\n\n"
        f"EXTRACTED CLAIMS:\n{json.dumps(listing, indent=2, ensure_ascii=False)}"
    )
    return await _call_json(client, model, prompts["pass4"], user, 0, tracker, "pass4")


async def run_dedup_audit(
    client: AsyncOpenAI,
    model: str,
    prompts: dict[str, str],
    claims: dict,
    tracker: UsageTracker | None = None,
) -> dict:
    """Pass 5 — cross-panel reconciliation. Reports merges and naming normalisations; it
    never applies either.

    `polarity` and `sample_type` are in the listing because the pass reasons about both: a
    positive claim and its null-polarity counterpart must never be merged, and sample_type
    is one of the two fields whose spelling it normalises across panels.
    """
    listing = {
        k: {
            "claim": v.get("claim", ""),
            "claim_type": v.get("claim_type"),
            "polarity": v.get("polarity"),
            "assay": v.get("assay"),
            "sample_type": v.get("sample_type"),
            "targets": v.get("targets", []),
            "timepoints": v.get("timepoints", []),
            "contrast": v.get("contrast"),
            "panel": v.get("panel"),
        }
        for k, v in claims.items()
    }
    user = f"CLAIM SET:\n{json.dumps(listing, indent=2, ensure_ascii=False)}"
    return await _call_json(client, model, prompts["pass5"], user, 0, tracker, "pass5")


async def abstract_claims_from_jats(
    xml_text: str,
    client: AsyncOpenAI,
    model: str,
    runs: int = 5,
    include_methods: bool = True,
    panel_ids: list[str] | None = None,
    prompt_file: str = PROMPT_FILE,
) -> tuple[dict, dict]:
    """Run all five passes over a JATS article. Returns (claims, audit).

    `claims` is keyed claim_1..N in panel order — the shape the rest of the pipeline reads
    (claim_filter, classify_groups). `audit` holds everything the passes reported that is
    not itself a claim: demotions, provenance verdicts, coverage, proposed merges, and the
    per-panel sampling record.
    """
    prompts = system_prompts(load_v5_prompts(prompt_file))
    paper = split_panels(xml_text)

    panels = [p for p in paper.panels if p.prose_paragraphs]
    skipped = [p.label for p in paper.panels if not p.prose_paragraphs]
    if panel_ids:
        panels = [p for p in panels if p.panel_id in panel_ids or p.label in panel_ids]

    tracker = UsageTracker()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    methods = paper.methods if include_methods else ""
    results = await asyncio.gather(
        *(run_panel(client, model, prompts, p, methods, runs, tracker, semaphore) for p in panels)
    )

    claims: dict = {}
    not_a_claim: list = []
    run_records: list = []
    for panel, result in zip(panels, results):
        kept, demoted = apply_verdicts(result["claims"], result["verdicts"])
        for claim in kept:
            claim["panel"] = panel.label
            claims[f"claim_{len(claims) + 1}"] = claim
        for entry in result["not_a_claim"] + demoted:
            entry["panel"] = panel.label
            not_a_claim.append(entry)
        result["run_record"]["demoted_by_audit"] = len(demoted)
        run_records.append(result["run_record"])

    coverage, dedup = {}, {}
    if claims:
        coverage, dedup = await asyncio.gather(
            run_coverage_audit(client, model, prompts, paper.abstract, claims, tracker),
            run_dedup_audit(client, model, prompts, claims, tracker),
        )

    audit = {
        "not_a_claim": not_a_claim,
        "abstract_coverage": coverage,
        "cross_panel_dedup": dedup,
        "panels": run_records,
        "panels_skipped_no_prose": skipped,
        "token_usage": tracker.summary(),
        "settings": {"model": model, "runs_per_pass": runs, "methods_included": bool(methods)},
    }
    return claims, audit
