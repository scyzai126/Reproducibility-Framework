#!/usr/bin/env python3
"""Re-run round 4 (OBI mapping) over the ImmPort corpus with the current vocabulary.

The 1,100 corpus registries under `/Volumes/Extreme SSD/HIPC result/` were mapped with the
701-term pruned vocabulary at TOP_K=20. Production switched to the 1249-term noncompositional
list at TOP_K=30 on 2026-11-10 (experiment/obi_topk_1249/FINDINGS.md), so the corpus no longer
matches what the mapper would produce today. This re-runs **round 4 only**, plus round 5 (free)
and round 6 (paid, ~1 call per fold refused on readouts or sample type). Rounds 1-3 are left
alone: they carry most of the cost and nothing in them depends on the OBI vocabulary.

Nothing here re-implements the mapping. Each paper goes through the same two functions
`scripts/run_assay_merge.py` exposes, in-process so the 48 MB vector file loads once:

    dry_run(registry_dir, remap=True, judge=True) -> int     # free, counts calls
    canonicalize_one(registry_dir, remap=True, judge=True)   # round 4 + 5 + 6

Before touching a paper, the four files round 4/5 rewrite are **copied** (not moved) into
`<registry>/obi_701_k20/`. Round 4 reads `assays_corrected.json` and round 5 reads
`assays.json`, so both must stay in place. That folder is also the resume marker: a paper that
has one is skipped unless --force.

    python3 scripts/remap_corpus_obi.py --dry-run
    python3 scripts/remap_corpus_obi.py --limit 2 --parallel 2
    python3 scripts/remap_corpus_obi.py --parallel 4 --max-usd 80
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import importlib.util
import io
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

RESULT_DIR = Path("/Volumes/Extreme SSD/HIPC result")
BACKUP_NAME = "obi_701_k20"
#: Rewritten by round 4/5; snapshot them before the first pass over a paper.
BACKED_UP = ("assays_OBI.json", "assays_benchmark.json", "assays_merges.json", "assays.json")
LEDGER = _REPO_ROOT / "data" / "assay_usage_ledger.csv"
#: Lines worth surfacing verbatim, per CLAUDE.md — never summarised away.
REPORT_PREFIXES = ("MERGED", "REVIEW", "JUDGED", "UNMAPPED", "OBI ERROR", "ERROR", "WARNING")


class _PerThreadStdout:
    """A stdout that routes each thread's writes to that thread's own buffer.

    `contextlib.redirect_stdout` swaps the *global* `sys.stdout`, so with two workers one
    thread's redirect captures the other's output and restoring it clobbers the other's --
    observed as a paper's banner landing inside a different paper's captured text. Installed
    once for the whole run; a thread with no buffer set (the main one) writes through.
    """

    def __init__(self, real) -> None:
        self._real = real
        self._local = threading.local()

    def _target(self):
        return getattr(self._local, "buffer", None) or self._real

    def set_buffer(self, buffer) -> None:
        self._local.buffer = buffer

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        with contextlib.suppress(Exception):
            self._target().flush()

    def isatty(self) -> bool:
        return False


def _load_merge_module():
    """scripts/ is not a package — same loader shim the tests use."""
    path = _REPO_ROOT / "scripts" / "run_assay_merge.py"
    spec = importlib.util.spec_from_file_location("run_assay_merge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registries(result_dir: Path) -> list[Path]:
    """Every corpus registry, in PMID order. Backup folders are not registries."""
    return sorted(
        d for d in result_dir.iterdir()
        if d.is_dir() and d.name != "logs" and d.name != BACKUP_NAME
        and (d / "assays.json").exists()
    )


def spent_since(start: dt.datetime) -> float:
    """USD on ledger rows written since this run began. 0.0 if the ledger is unreadable."""
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    try:
        with LEDGER.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                stamp = row.get("date") or ""
                try:
                    when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when.replace(tzinfo=None) >= start:
                    with contextlib.suppress(TypeError, ValueError):
                        total += float(row.get("usd") or 0)
    except OSError:
        return 0.0
    return total


def backup(registry: Path) -> bool:
    """Copy the files round 4/5 rewrite into <registry>/obi_701_k20/. True if it was created."""
    target = registry / BACKUP_NAME
    fresh = not target.exists()
    target.mkdir(exist_ok=True)
    for name in BACKED_UP:
        source = registry / name
        if source.exists() and not (target / name).exists():
            shutil.copyfile(source, target / name)
    return fresh


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Only the first N pending papers")
    parser.add_argument("--parallel", type=int, default=4, help="Papers in flight (default 4)")
    parser.add_argument("--only", nargs="+", default=None, help="PMIDs to run, nothing else")
    parser.add_argument("--force", action="store_true", help="Re-run papers already remapped")
    parser.add_argument("--dry-run", action="store_true", help="Count calls; call nothing")
    parser.add_argument("--max-usd", type=float, default=None,
                        help="Stop launching new papers once this run's ledger spend crosses it")
    parser.add_argument("--no-judge", action="store_true", help="Skip round 6")
    args = parser.parse_args()

    if not args.result_dir.is_dir():
        raise SystemExit(f"result dir not found: {args.result_dir}")

    merge = _load_merge_module()
    judge = not args.no_judge

    queue = registries(args.result_dir)
    total_found = len(queue)
    if args.only:
        wanted = set(args.only)
        queue = [d for d in queue if d.name.split("_")[0] in wanted]
    if not args.force:
        queue = [d for d in queue if not (d / BACKUP_NAME).exists()]
    skipped = total_found - len(queue)
    if args.limit:
        queue = queue[:args.limit]

    print(f"registries: {total_found} found, {skipped} already remapped, {len(queue)} to do")

    if args.dry_run:
        # `merge.dry_run` returns the fold count and only *prints* the call estimate when
        # remapping, so count with the same two helpers it uses rather than parse its output.
        calls = entries = free = chat = 0
        for registry in queue:
            assays, _ = merge._load(registry, True)
            missed = merge.obi_misses(assays)
            calls += sum(merge.obi_query_calls(key, assays[key]) for key in missed)
            entries += len(assays)
            free += len(assays) - len(missed)
            chat += len(missed)  # one picker call per miss; the rest of the budget is embeddings
        # obi_query_calls bills the embedding queries too (2 = 1 embed + 1 pick, 3 = 2 + 1).
        # Only the picks cost real money: embeddings are text-embedding-3-small at $0.02/M.
        print(f"{len(queue)} paper(s), {entries} entry(ies), {free} answered free by an exact "
              f"vocabulary hit")
        print(f"  ~{chat} picker call(s) + ~{calls - chat} embedding call(s) = {calls} total")
        if judge:
            print("round 6 is not countable up front — its calls depend on the folds the new "
                  "mapping produces. The 701/K=20 corpus spent 421.")
        print("--dry-run: nothing called")
        return

    started = dt.datetime.now()
    log_dir = args.result_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"remap_{started:%Y%m%d_%H%M%S}.txt"
    lock = threading.Lock()
    done: list[Path] = []
    failed: list[tuple[Path, str]] = []
    stopped: list[Path] = []
    seconds: list[float] = []

    real_stdout = sys.stdout
    router = _PerThreadStdout(real_stdout)

    def one(registry: Path) -> tuple[str, Path, str, float]:
        if args.max_usd is not None and spent_since(started) >= args.max_usd:
            return ("stopped", registry, "", 0.0)
        begin = time.monotonic()
        buffer = io.StringIO()
        # Captured per paper, per thread, so two papers' lines can never interleave.
        router.set_buffer(buffer)
        try:
            backup(registry)
            merge.canonicalize_one(registry, True, judge)
        except Exception as exc:  # noqa: BLE001 — one bad paper must not stop the run
            return ("failed", registry, f"{type(exc).__name__}: {exc}", time.monotonic() - begin)
        finally:
            router.set_buffer(None)
        return ("done", registry, buffer.getvalue(), time.monotonic() - begin)

    sys.stdout = router
    try:
        with open(log_path, "w", encoding="utf-8") as log, \
                ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [pool.submit(one, registry) for registry in queue]
            for future in as_completed(futures):
                status, registry, text, took = future.result()
                with lock:
                    if status == "stopped":
                        stopped.append(registry)
                        continue
                    banner = f"=== {registry.name}  ({status}, {took:.0f}s)"
                    print(banner, file=real_stdout, flush=True)
                    log.write(banner + "\n")
                    if status == "failed":
                        failed.append((registry, text))
                        print(f"  ERROR  {text}", file=real_stdout, flush=True)
                        log.write(f"  ERROR  {text}\n")
                        continue
                    done.append(registry)
                    seconds.append(took)
                    for line in text.splitlines():
                        if line.strip().startswith(REPORT_PREFIXES):
                            print(line, file=real_stdout, flush=True)
                        log.write(line + "\n")
    finally:
        sys.stdout = real_stdout

    seconds.sort()
    median = seconds[len(seconds) // 2] if seconds else 0.0
    summary = [
        "",
        f"{len(done)} done, {len(failed)} failed, {len(stopped)} not started "
        f"({skipped} skipped as already remapped)",
        f"${spent_since(started):.2f} this run (ledger), "
        f"{median:.0f}s/paper median at --parallel {args.parallel}",
        f"log: {log_path}",
    ]
    for registry, error in failed:
        summary.append(f"  FAILED  {registry.name}: {error}")
    text = "\n".join(summary)
    print(text)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(text + "\n")


if __name__ == "__main__":
    main()
