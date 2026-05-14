#!/usr/bin/env python3
"""
HuskyAI PEI evaluator benchmark runner.

Runs one of the PEI evaluators (v1/v2/v3) against the held-out judge benchmark
cases in backend/tests/judge_benchmark/cases.json, computes per-case and summary
metrics (MAE per dimension, classification accuracy, stddev across repeats, etc.)
and writes a JSON report to backend/tests/judge_benchmark/reports/.

CLI:
    python backend/scripts/run_eval_benchmark.py --evaluator v1 --repeats 3

Module API (importable from FastAPI later):
    async def run_benchmark(evaluator: str, repeats: int) -> dict
    def list_reports() -> list[dict]
    def load_report(report_id: str) -> dict | None
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# --- sys.path bootstrap (mirrors scripts/verify_external_ai.py) -----------------
_backend = Path(__file__).resolve().parents[1]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Optional .env load — harmless if dotenv isn't installed (e.g., during tests).
try:  # pragma: no cover — environment-dependent
    from dotenv import load_dotenv

    load_dotenv(_backend / ".env")
    load_dotenv()
except Exception:
    pass


# --- Paths ----------------------------------------------------------------------
BENCHMARK_DIR = _backend / "tests" / "judge_benchmark"
CASES_PATH = BENCHMARK_DIR / "cases.json"
REPORTS_DIR = BENCHMARK_DIR / "reports"

# PEI sub-dimensions whose deltas we track per run.
DIMENSIONS = ("PSQ", "CCM", "TSI", "CLM", "RAS", "PEI")

# Max in-flight evaluator calls. Default 1 (sequential) to stay under OpenAI Tier-1
# 30k TPM on gpt-4.1. Override via BENCHMARK_CONCURRENCY=N when your account has
# higher limits and you want to speed runs up.
def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


CONCURRENCY = _env_int("BENCHMARK_CONCURRENCY", 1)
# Floor sleep AFTER each evaluator call (still holding the semaphore slot) so
# we space token bursts across the TPM window. 0 = no extra pacing.
PACE_SECONDS = _env_float("BENCHMARK_PACE_SECONDS", 0.0)


# --- Helpers --------------------------------------------------------------------
def _resolve_evaluator(name: str):
    """Map 'v1'|'v2'|'v3' to the matching async evaluator function."""
    key = (name or "").strip().lower()
    if key == "v1":
        from evaluator import evaluate_conversation

        return evaluate_conversation
    if key == "v2":
        from evaluator_v2 import evaluate_conversation_v2

        return evaluate_conversation_v2
    if key == "v3":
        from evaluator_v3 import evaluate_conversation_v3

        return evaluate_conversation_v3
    raise ValueError(f"Unknown evaluator {name!r}; expected one of: v1, v2, v3")


def _load_cases() -> list[dict]:
    """Load cases.json with a tolerant parser that strips trailing commas."""
    raw = CASES_PATH.read_text(encoding="utf-8")
    cleaned = re.sub(r",(\s*[}\]])", r"\1", raw)
    data = json.loads(cleaned)
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"cases.json malformed: expected top-level 'cases' list, got {type(cases).__name__}")
    return cases


def _round2(x: float) -> float:
    """Round to 2 decimals, returning a float (not Decimal)."""
    return round(float(x), 2)


def _safe_float(v) -> float | None:
    """Coerce to float, returning None for missing/non-numeric values."""
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _utc_iso(ts: float | None = None) -> str:
    """UTC ISO-8601 timestamp with trailing Z (e.g. 2026-05-14T10:30:22Z)."""
    if ts is not None:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _modal(values: list) -> object | None:
    """Most common value across a list (ties broken by first-seen order)."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


# --- Per-case execution ---------------------------------------------------------
async def _run_one(
    evaluator_fn,
    history: list[dict],
    semaphore: asyncio.Semaphore,
) -> tuple[dict | None, int, str | None]:
    """Invoke the evaluator once. Returns (result_dict, latency_ms, error_str)."""
    async with semaphore:
        t0 = time.perf_counter()
        try:
            result = await evaluator_fn(history)
            latency_ms = int(round((time.perf_counter() - t0) * 1000))
            if PACE_SECONDS > 0:
                await asyncio.sleep(PACE_SECONDS)
            return result, latency_ms, None
        except Exception as e:  # noqa: BLE001 — we capture every failure mode
            latency_ms = int(round((time.perf_counter() - t0) * 1000))
            if PACE_SECONDS > 0:
                await asyncio.sleep(PACE_SECONDS)
            return None, latency_ms, f"{type(e).__name__}: {e}"


def _build_run_record(
    run_index: int,
    raw: dict | None,
    latency_ms: int,
    error: str | None,
    golden_scores: dict,
) -> dict:
    """Translate a raw evaluator result into the report's per-run shape."""
    if error is not None or raw is None:
        return {
            "run_index": run_index,
            "predicted": None,
            "deltas": None,
            "latency_ms": latency_ms,
            "error": error or "evaluator returned None",
        }

    scores = raw.get("scores") or {}
    predicted = {dim: _safe_float(scores.get(dim)) for dim in DIMENSIONS}
    predicted["classification"] = raw.get("classification")
    predicted["leading_status"] = raw.get("leading_status")

    deltas: dict[str, float | None] = {}
    for dim in DIMENSIONS:
        gold = _safe_float(golden_scores.get(dim))
        pred = predicted[dim]
        if gold is None or pred is None:
            deltas[dim] = None
        else:
            deltas[dim] = _round2(pred - gold)

    return {
        "run_index": run_index,
        "predicted": predicted,
        "deltas": deltas,
        "latency_ms": latency_ms,
        "error": None,
    }


def _aggregate_case(runs: list[dict], golden_pei: float | None, golden_classification: str | None) -> dict:
    """Compute per-case aggregate: predicted_pei_mean/stddev, pei_delta, match rate."""
    successful = [r for r in runs if r.get("error") is None and r.get("predicted")]
    pei_values = [
        r["predicted"]["PEI"]
        for r in successful
        if r["predicted"].get("PEI") is not None
    ]
    if pei_values:
        pei_mean = _mean(pei_values)
        pei_stddev = statistics.pstdev(pei_values) if len(pei_values) >= 2 else 0.0
    else:
        pei_mean = 0.0
        pei_stddev = 0.0

    if pei_values and golden_pei is not None:
        pei_delta = abs(pei_mean - golden_pei)
    else:
        pei_delta = 0.0

    if successful and golden_classification is not None:
        matches = sum(
            1 for r in successful if r["predicted"].get("classification") == golden_classification
        )
        match_rate = matches / len(successful)
    else:
        match_rate = 0.0

    return {
        "predicted_pei_mean": _round2(pei_mean),
        "predicted_pei_stddev": _round2(pei_stddev),
        "pei_delta": _round2(pei_delta),
        "classification_match_rate": _round2(match_rate),
        "successful_runs": len(successful),
    }


def _summarize(cases_report: list[dict], total_runs: int, failed_runs: int) -> dict:
    """Compute the top-level `summary` block over all cases."""
    # Per-dimension MAE: mean over cases of |case_mean - golden|, where the case mean
    # uses only successful runs. Cases with zero successful runs are skipped.
    per_dim_abs: dict[str, list[float]] = {dim: [] for dim in DIMENSIONS}
    pei_stddevs: list[float] = []
    cls_correct = 0
    cls_total = 0
    leading_correct = 0
    leading_total = 0
    by_domain_buckets: dict[str, dict] = {}

    for c in cases_report:
        golden = c["golden"]
        runs = c["runs"]
        successful = [r for r in runs if r.get("error") is None and r.get("predicted")]
        domain = c.get("domain") or "unknown"
        bucket = by_domain_buckets.setdefault(
            domain,
            {"case_count": 0, "pei_abs": [], "cls_correct": 0, "cls_total": 0},
        )
        bucket["case_count"] += 1

        # Per-dimension MAE contribution
        for dim in DIMENSIONS:
            gold_v = _safe_float(golden.get(dim))
            preds = [
                r["predicted"][dim]
                for r in successful
                if r["predicted"].get(dim) is not None
            ]
            if gold_v is None or not preds:
                continue
            mean_pred = _mean(preds)
            per_dim_abs[dim].append(abs(mean_pred - gold_v))
            if dim == "PEI":
                bucket["pei_abs"].append(abs(mean_pred - gold_v))

        # Stddev tracking (only meaningful with >=2 successful runs)
        if len(successful) >= 2:
            pei_values = [
                r["predicted"]["PEI"]
                for r in successful
                if r["predicted"].get("PEI") is not None
            ]
            if len(pei_values) >= 2:
                pei_stddevs.append(statistics.pstdev(pei_values))

        # Modal-classification accuracy
        gold_cls = golden.get("classification")
        if successful and gold_cls is not None:
            modal_cls = _modal([r["predicted"].get("classification") for r in successful])
            cls_total += 1
            bucket["cls_total"] += 1
            if modal_cls == gold_cls:
                cls_correct += 1
                bucket["cls_correct"] += 1

        gold_lead = golden.get("leading_status")
        if successful and gold_lead is not None:
            modal_lead = _modal([r["predicted"].get("leading_status") for r in successful])
            leading_total += 1
            if modal_lead == gold_lead:
                leading_correct += 1

    by_domain: dict[str, dict] = {}
    for domain, bucket in by_domain_buckets.items():
        by_domain[domain] = {
            "case_count": bucket["case_count"],
            "pei_mae": _round2(_mean(bucket["pei_abs"])) if bucket["pei_abs"] else 0.0,
            "classification_accuracy": (
                _round2(bucket["cls_correct"] / bucket["cls_total"])
                if bucket["cls_total"]
                else 0.0
            ),
        }

    summary = {
        "pei_mae": _round2(_mean(per_dim_abs["PEI"])) if per_dim_abs["PEI"] else 0.0,
        "psq_mae": _round2(_mean(per_dim_abs["PSQ"])) if per_dim_abs["PSQ"] else 0.0,
        "ccm_mae": _round2(_mean(per_dim_abs["CCM"])) if per_dim_abs["CCM"] else 0.0,
        "tsi_mae": _round2(_mean(per_dim_abs["TSI"])) if per_dim_abs["TSI"] else 0.0,
        "clm_mae": _round2(_mean(per_dim_abs["CLM"])) if per_dim_abs["CLM"] else 0.0,
        "ras_mae": _round2(_mean(per_dim_abs["RAS"])) if per_dim_abs["RAS"] else 0.0,
        "classification_accuracy": _round2(cls_correct / cls_total) if cls_total else 0.0,
        "leading_status_accuracy": _round2(leading_correct / leading_total) if leading_total else 0.0,
        "mean_pei_stddev": _round2(_mean(pei_stddevs)) if pei_stddevs else 0.0,
        "max_pei_stddev": _round2(max(pei_stddevs)) if pei_stddevs else 0.0,
        "error_rate": _round2(failed_runs / total_runs) if total_runs else 0.0,
        "by_domain": by_domain,
    }
    return summary


# --- Public API -----------------------------------------------------------------
async def run_benchmark_stream(evaluator: str, repeats: int):
    """Async generator: runs the benchmark and yields progress events as cases finish.

    Event shapes (all dicts with a `type` key):
      - {type: "started", evaluator, repeats, case_count, total_runs, started_at}
      - {type: "progress", completed, total, case_id, case_index, run_index,
                           ok, error, latency_ms, predicted_pei, elapsed_seconds}
      - {type: "done", report_id, report, elapsed_seconds}

    The final report is also written to disk before the `done` event is yielded.
    """
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError(f"repeats must be a positive int, got {repeats!r}")

    evaluator_fn = _resolve_evaluator(evaluator)
    cases = _load_cases()
    started_perf = time.perf_counter()
    started_at = _utc_iso()

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _tagged(ci: int, ri: int, history: list[dict]):
        raw, latency_ms, err = await _run_one(evaluator_fn, history, semaphore)
        return ci, ri, raw, latency_ms, err

    async def _tagged_synthetic(ci: int, ri: int, err_msg: str):
        return ci, ri, None, 0, err_msg

    tasks: list[asyncio.Task] = []
    for ci, case in enumerate(cases):
        idx = case.get("evaluated_turn_index")
        conversation = case.get("conversation") or []
        if not isinstance(idx, int) or idx < 0 or idx >= len(conversation):
            for r in range(repeats):
                tasks.append(asyncio.create_task(
                    _tagged_synthetic(ci, r, f"invalid evaluated_turn_index={idx!r}")
                ))
            continue
        history = conversation[: idx + 1]
        for r in range(repeats):
            tasks.append(asyncio.create_task(_tagged(ci, r, history)))

    total_tasks = len(tasks)
    yield {
        "type": "started",
        "evaluator": evaluator,
        "repeats": repeats,
        "case_count": len(cases),
        "total_runs": total_tasks,
        "started_at": started_at,
    }

    per_case_runs: list[list[dict]] = [[None] * repeats for _ in cases]  # type: ignore[list-item]
    total_runs = 0
    failed_runs = 0
    completed = 0

    for fut in asyncio.as_completed(tasks):
        ci, ri, raw, latency_ms, err = await fut
        golden_scores = (cases[ci].get("golden") or {}).get("scores") or {}
        record = _build_run_record(ri, raw, latency_ms, err, golden_scores)
        per_case_runs[ci][ri] = record
        total_runs += 1
        if record["error"] is not None:
            failed_runs += 1
        completed += 1

        predicted = record.get("predicted") or {}
        yield {
            "type": "progress",
            "completed": completed,
            "total": total_tasks,
            "case_id": cases[ci].get("id"),
            "case_index": ci,
            "case_domain": cases[ci].get("domain"),
            "run_index": ri,
            "ok": record["error"] is None,
            "error": record["error"],
            "latency_ms": record["latency_ms"],
            "predicted_pei": predicted.get("PEI"),
            "failed_so_far": failed_runs,
            "elapsed_seconds": round(time.perf_counter() - started_perf, 2),
        }

    # Build per-case report and final summary.
    cases_report: list[dict] = []
    for ci, case in enumerate(cases):
        golden = case.get("golden") or {}
        gold_scores = golden.get("scores") or {}
        flat_golden = {dim: _safe_float(gold_scores.get(dim)) for dim in DIMENSIONS}
        flat_golden["classification"] = golden.get("classification")
        flat_golden["leading_status"] = golden.get("leading_status")

        runs = per_case_runs[ci]
        agg = _aggregate_case(runs, flat_golden["PEI"], flat_golden["classification"])
        cases_report.append(
            {
                "id": case.get("id"),
                "domain": case.get("domain"),
                "tier": case.get("tier"),
                "turn_type": case.get("turn_type"),
                "golden": flat_golden,
                "runs": runs,
                "aggregate": agg,
            }
        )

    summary = _summarize(cases_report, total_runs, failed_runs)
    ended_at = _utc_iso()
    report_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{evaluator}-r{repeats}"

    report = {
        "report_id": report_id,
        "evaluator": evaluator,
        "repeats": repeats,
        "case_count": len(cases),
        "started_at": started_at,
        "ended_at": ended_at,
        "summary": summary,
        "cases": cases_report,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{report_id}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    elapsed = round(time.perf_counter() - started_perf, 2)
    yield {
        "type": "done",
        "report_id": report_id,
        "report": report,
        "elapsed_seconds": elapsed,
    }


async def run_benchmark(evaluator: str, repeats: int) -> dict:
    """Run the benchmark and return the final report dict (non-streaming wrapper
    around run_benchmark_stream)."""
    final_report: dict | None = None
    final_elapsed: float = 0.0
    async for event in run_benchmark_stream(evaluator, repeats):
        if event.get("type") == "done":
            final_report = event["report"]
            final_elapsed = event.get("elapsed_seconds") or 0.0
    if final_report is None:
        raise RuntimeError("benchmark stream ended without 'done' event")
    # Stash wall-clock for the CLI summary line (not part of saved report).
    final_report["_elapsed_seconds"] = final_elapsed
    return final_report


def list_reports() -> list[dict]:
    """Return compact metadata for every report on disk, newest first."""
    if not REPORTS_DIR.exists():
        return []
    out: list[dict] = []
    for path in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        full_summary = data.get("summary") or {}
        compact = {
            "pei_mae": full_summary.get("pei_mae"),
            "classification_accuracy": full_summary.get("classification_accuracy"),
            "mean_pei_stddev": full_summary.get("mean_pei_stddev"),
        }
        out.append(
            {
                "report_id": data.get("report_id") or path.stem,
                "evaluator": data.get("evaluator"),
                "repeats": data.get("repeats"),
                "case_count": data.get("case_count"),
                "started_at": data.get("started_at"),
                "ended_at": data.get("ended_at"),
                "summary": compact,
            }
        )
    out.sort(key=lambda r: r.get("report_id") or "", reverse=True)
    return out


def load_report(report_id: str) -> dict | None:
    """Load a single report by id. Returns None if missing or invalid JSON."""
    if not report_id:
        return None
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# --- CLI ------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the HuskyAI PEI evaluator benchmark and write a JSON report.",
    )
    parser.add_argument(
        "--evaluator",
        required=True,
        choices=("v1", "v2", "v3"),
        help="Which evaluator variant to benchmark.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Number of repeats per case (>=1). Default: 1.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.repeats < 1:
        print(f"FAIL: --repeats must be >= 1 (got {args.repeats})", file=sys.stderr)
        return 2
    try:
        report = asyncio.run(run_benchmark(args.evaluator, args.repeats))
    except Exception as e:  # noqa: BLE001 — top-level CLI guard
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    s = report.get("summary") or {}
    elapsed = report.get("_elapsed_seconds")
    print(
        f"OK: {report.get('report_id')} "
        f"cases={report.get('case_count')} repeats={report.get('repeats')} "
        f"pei_mae={s.get('pei_mae')} cls_acc={s.get('classification_accuracy')} "
        f"err_rate={s.get('error_rate')} elapsed_s={elapsed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
