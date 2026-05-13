"""Drive the AI System Debugger end-to-end with the sample dataset.

Usage:
    python scripts/load_sample_data.py [--base-url http://localhost:8000] [--skip-fix]

For each entry in data/sample_traces.json, this script:
1. POSTs /trace
2. POSTs /analyze
3. If failure detected, POSTs /rca and (unless --skip-fix) /fix

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

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        # Health check
        try:
            health = client.get("/health")
            health.raise_for_status()
        except Exception as e:
            print(f"Backend unreachable at {args.base_url}: {e}", file=sys.stderr)
            return 2

        for i, sample in enumerate(samples, start=1):
            t0 = time.perf_counter()
            print(f"\n[{i}/{len(samples)}] {sample['session_id']}")
            try:
                # Default risk_tier=general unless metadata flags otherwise
                risk_tier = sample.get("metadata", {}).get("risk_tier", "general")
                payload = {
                    "session_id": sample["session_id"],
                    "prompt": sample["prompt"],
                    "response": sample["response"],
                    "model_used": sample["model_used"],
                    "context_documents": sample.get("context_documents", []),
                    "latency_ms": sample.get("latency_ms", 0.0),
                    "token_count_input": sample.get("token_count_input", 0),
                    "token_count_output": sample.get("token_count_output", 0),
                    "metadata": sample.get("metadata", {}),
                    "risk_tier": risk_tier,
                }
                resp = client.post("/trace", json=payload)
                resp.raise_for_status()
                trace = resp.json()
                trace_id = trace["id"]
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

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
