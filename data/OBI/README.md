# OBI assay vocabularies

The assay vocabulary and vectors used by `apps/api/app/agent/assay_obi_mapper.py`.
**`obi_generic_index.json` is the live vocabulary the mapper searches**; the unfiltered list
is kept beside it so the prune stays inspectable.

| file | terms | size | role |
|---|---|---|---|
| `obi_generic_index.json` | 1262 | 150 KB | **Live vocabulary.** Exact matching + the candidate pool for semantic search. |
| `obi_generic_embeddings.json` | 1262 | 51 MB | **Live vectors.** `text-embedding-3-small`, 1536-dim, same row order as the index. |
| `obi_assay_terms_full.json` | 1794 | 261 KB | Original unfiltered list — the source the other two are derived from. |
| `obi_compositional_dropped.json` | 532 | 111 KB | The terms removed, for review. |

`obi_generic_index.json` + `obi_compositional_dropped.json` == `obi_assay_terms_full.json`.

## Why the prune

The dropped 532 are IEDB-style **compositional** labels — *"… assay measuring epitope specific
X production by Y cells"* — plus IEDB MHC-binding constructs like *"radioactivity detection
assay measuring half maximal inhibitory concentration [IC50] …"*. Everything matching
`/\bmeasuring\b/` is removed.

They are ~30% of the assay branch and they outrank the plain family terms in similarity search:
43 of the 45 ELISPOT-ish labels are compositional, so an "IFN-γ ELISPOT" query buried
`OBI:0600031 enzyme-linked immunospot assay` beneath cytokine-specific variants. This was
producing wrong mappings in committed output until 2026-08-19.

## Rebuilding

The index and the vectors must be regenerated together — `_load_embeddings()` relies on them
being row-aligned.

```bash
# 1. Re-derive the pruned lists from the source vocabulary
./.venv/bin/python - <<'PY'
import json, sys; sys.path.insert(0, "apps/api")
from pathlib import Path
from app.agent.assay_obi_mapper import _is_generic_assay_label
terms = json.loads(Path("data/OBI/obi_assay_terms_full.json").read_text())
for name, data in [
    ("obi_generic_index.json", [t for t in terms if _is_generic_assay_label(t["label"])]),
    ("obi_compositional_dropped.json", [t for t in terms if not _is_generic_assay_label(t["label"])]),
]:
    Path("data/OBI", name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
PY

# 2. Embed anything new (resumable; skips ids already in the output — no cost if unchanged)
./.venv/bin/python scripts/build_obi_embeddings.py
```

## Notes

- **The load-time filter is still applied** on top of this pre-pruned index, so it is a no-op
  for the default vocabulary. It stays because `run_obi_map.py --terms` can point the mapper at
  any term list, including `obi_assay_terms_full.json`.
- This folder is the **only** location for OBI vocabularies. The former copies under
  `.claude/skills/extract-assay-methods/references/` were deleted on 2026-08-19; the skill's
  `obi_enrich_file.py` imports the mapper and so reads these files transparently. Recover the
  old ones from git history if ever needed.
- `obi.obo` — full OBI release 2026-05-08 (5218 terms), the upstream ontology. Not read by any
  code; kept here as the provenance for `obi_assay_terms_full.json` and for regenerating the
  assay branch against a newer OBI release.

## Known gap

Two common assays have **no** generic term left: the plain `intracellular cytokine staining
assay` (`OBI:0000665`) and `MHC multimer staining assay` (`OBI:0000667`) are **obsolete** in OBI
and absent from the source list. They deliberately fall back to broader parents
(`OBI:0002766 cytokine assay`, `OBI:0001632 immuno staining assay`) rather than being pinned by
an override map.

A smaller sibling family — `assay detecting X` (e.g. `OBI:1110207 assay detecting IFN-gamma
production`) — survives the prune; only 14 such terms remain and most are legitimate
(insecticide-resistance assays), so `\bdetecting\b` was **not** added to the filter.
