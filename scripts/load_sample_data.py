"""Drive the AI System Debugger end-to-end with the sample dataset.

Usage:
    python scripts/load_sample_data.py [--base-url http://localhost:8000] [--skip-fix]

For each entry in data/sample_traces.json, this script:
1. POSTs /trace (with full cost, latency_breakdown, task_type, complexity_score)
2. POSTs /analyze
3. If failure detected, POSTs /rca and (unless --skip-fix) /fix
4. Labels all review queue items with ground-truth
5. Recalibrates evaluators from human labels

It prints a brief summary to stdout. The backend must be running and reachable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_FILE = REPO_ROOT / "data" / "sample_traces.json"

# Ground-truth labels for review queue items based on the sample data expectations
REVIEW_LABELS = {
    # session_id -> expected failure type label
    "demo-session-002": "prompt_failure",       # Empty refusal response
    "demo-session-005": "hallucination",        # Fabricated facts
    "demo-session-006": "hallucination",        # Hallucinated details
    "demo-session-004": "none",                 # Correct but medical risk tier
    "demo-session-008": "none",                 # Correct but financial risk tier
    "demo-session-010": "reasoning_failure",    # Flawed reasoning
    "demo-session-011": "retrieval_failure",    # Wrong docs retrieved
    "demo-session-012": "none",                 # Correct but legal risk tier
    "demo-session-015": "context_loss",         # Lost context
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-fix", action="store_true", help="Skip /fix calls")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not SAMPLE_FILE.exists():
        print(f"sample data not found: {SAMPLE_FILE}", file=sys.stderr)
        return 1

    samples = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    print(f"Loading {len(samples)} sample traces against {args.base_url}")

    # Track session_id -> trace_id for labeling
    session_trace_map: dict[str, str] = {}

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        # Health check
        try:
            health = client.get("/health")
            health.raise_for_status()
        except Exception as e:
            print(f"Backend unreachable at {args.base_url}: {e}", file=sys.stderr)
            return 2

        # ── Phase 1: Load traces through the pipeline ────────────────
        for i, sample in enumerate(samples, start=1):
            t0 = time.perf_counter()
            print(f"\n[{i}/{len(samples)}] {sample['session_id']}")
            try:
                risk_tier = sample.get("metadata", {}).get("risk_tier", "general")
                cost_data = sample.get("cost")
                payload = {
                    "session_id": sample["session_id"],
                    "prompt": sample["prompt"],
                    "response": sample["response"],
                    "model_used": sample["model_used"],
                    "context_documents": sample.get("context_documents", []),
                    "latency_ms": sample.get("latency_ms", 0.0),
                    "latency_breakdown": sample.get("latency_breakdown"),
                    "token_count_input": sample.get("token_count_input", 0),
                    "token_count_output": sample.get("token_count_output", 0),
                    "cost": cost_data,
                    "task_type": sample.get("task_type"),
                    "complexity_score": sample.get("complexity_score"),
                    "metadata": sample.get("metadata", {}),
                    "risk_tier": risk_tier,
                }
                resp = client.post("/trace", json=payload)
                resp.raise_for_status()
                trace = resp.json()
                trace_id = trace["id"]
                session_trace_map[sample["session_id"]] = trace_id
                print(f"  trace_id={trace_id}")

                resp = client.post("/analyze", json={"trace_id": trace_id})
                resp.raise_for_status()
                ev = resp.json()
                print(
                    f"  evaluate: passed={ev['passed']} score={ev['overall_score']} "
                    f"failure_type={ev['failure_type']} severity={ev['severity']}"
                )

                if ev["failure_detected"]:
                    resp = client.post(
                        "/rca",
                        json={"trace_id": trace_id, "evaluation_id": ev["id"]},
                    )
                    resp.raise_for_status()
                    rca = resp.json()
                    print(f"  rca: primary_source={rca['primary_source']}")

                    if not args.skip_fix:
                        resp = client.post(
                            "/fix", json={"trace_id": trace_id, "rca_id": rca["id"]},
                        )
                        resp.raise_for_status()
                        fix = resp.json()
                        print(
                            f"  fix: strategy={fix['strategy']} "
                            f"regression_passed={fix['regression_passed']} "
                            f"improvement={fix['improvement_score']:.4f} "
                            f"escalated={fix['escalated_to_openai']}"
                        )
            except httpx.HTTPStatusError as e:
                print(f"  HTTP error: {e.response.status_code} {e.response.text[:200]}", file=sys.stderr)
            except Exception as e:
                print(f"  error: {e}", file=sys.stderr)
            finally:
                print(f"  elapsed: {(time.perf_counter() - t0):.2f}s")

        # ── Phase 2: Label review queue items ─────────────────────────
        print("\n--- Labeling review queue items ---")
        try:
            resp = client.get("/review/queue")
            resp.raise_for_status()
            queue = resp.json()
            print(f"Found {len(queue)} items in review queue")

            for item in queue:
                trace_id = item["trace_id"]
                # Find session_id for this trace
                session_id = None
                for sid, tid in session_trace_map.items():
                    if tid == trace_id:
                        session_id = sid
                        break

                label = "none"
                if session_id and session_id in REVIEW_LABELS:
                    label = REVIEW_LABELS[session_id]

                try:
                    resp = client.post(
                        f"/review/{item['id']}/label",
                        json={
                            "label": label,
                            "notes": f"Seeded ground-truth label for {session_id or 'unknown'}",
                            "reviewer": "seed_script",
                        },
                    )
                    resp.raise_for_status()
                    print(f"  labeled {item['id'][:8]}... -> {label} ({item['reason']}, {item['risk_tier']})")
                except httpx.HTTPStatusError as e:
                    print(f"  label error: {e.response.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"  review queue error: {e}", file=sys.stderr)

        # ── Phase 3: Recalibrate evaluators ───────────────────────────
        print("\n--- Recalibrating evaluators ---")
        try:
            resp = client.post("/evaluator-health/recalibrate")
            resp.raise_for_status()
            evaluators = resp.json()
            for ev in evaluators:
                print(
                    f"  {ev['evaluator_type']}: "
                    f"accuracy={ev['accuracy']:.1%} precision={ev['precision']:.1%} "
                    f"recall={ev['recall']:.1%} f1={ev['f1_score']:.1%} "
                    f"agreement={ev['agreement_rate']:.1%}"
                )
        except Exception as e:
            print(f"  recalibration error: {e}", file=sys.stderr)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
