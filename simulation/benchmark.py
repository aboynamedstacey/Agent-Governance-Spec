"""Measure local governance proxy overhead; not a production SLA result.

Run: python simulation/benchmark.py --actions 2000 --preload 10000

This measures the reference fixture's SQLite tool call, local policy evaluation,
audit canonicalization, and bookkeeping. It does not include LLM inference,
remote APIs, authentication, distributed revocation, or durable cloud storage.
"""
import argparse
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from integration_tests import GovernanceStack
from workflow import LocalExecutionBoundary, draft_scope


def percentile(samples, pct):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * pct / 100 + 0.999) - 1))]


def benchmark(actions=2000, preload=0):
    if actions < 1 or preload < 0:
        raise ValueError("Require positive actions and nonnegative preload")
    gov = GovernanceStack()
    scope = draft_scope()
    grant = gov.create_grant("bench-agent", scope, scope["authorized_actions"],
                             86400, "human:benchmark",
                             rate_limits=[{"action_pattern": "mail.draft",
                                           "max_count": actions + preload + 100,
                                           "window": "1h", "scope": "INSTANCE"}],
                             damage_budgets=[{"metric": "recipient_count", "accumulator": "recipients",
                                              "threshold": actions + preload + 100,
                                              "window": "1h", "scope": "INSTANCE",
                                              "on_exceed": "DENY", "evaluation_tier": 2}])
    agent = gov.create_root_identity(grant)
    params = {"body": "bounded governance overhead sample", "recipients": 1}

    with TemporaryDirectory() as directory:
        boundary = LocalExecutionBoundary(gov, Path(directory) / "tools.db")
        durations = []
        try:
            for i in range(preload + actions):
                start = perf_counter_ns()
                result = boundary.execute(agent.instance_id, "mail.draft", params)
                elapsed_ms = (perf_counter_ns() - start) / 1_000_000
                if result["decision"] != "ALLOW":
                    raise RuntimeError(f"Benchmark denied action {i}: {result}")
                if i >= preload:
                    durations.append(elapsed_ms)
            audit_bytes = sum(len(json.dumps(e, separators=(",", ":")).encode())
                              for e in gov.chain)
            storage = Path(directory, "tools.db").stat().st_size
            full_start = perf_counter_ns()
            if not boundary.verify_audit_full():
                raise RuntimeError("Audit verification failed")
            full_verify_ms = (perf_counter_ns() - full_start) / 1_000_000
            return {
                "measured_actions": actions, "prior_actions": preload,
                "audit_entries": len(gov.chain),
                "action_latency_ms": {
                    "mean": round(mean(durations), 4),
                    "p50": round(percentile(durations, 50), 4),
                    "p95": round(percentile(durations, 95), 4),
                    "p99": round(percentile(durations, 99), 4)},
                "full_audit_check_ms_off_path": round(full_verify_ms, 4),
                "audit_json_bytes": audit_bytes,
                "audit_bytes_per_action": round(audit_bytes / (preload + actions), 1),
                "sqlite_file_bytes": storage,
                "diagnostic_sample_maximum": gov.action_log.maxlen,
                "limitations": "Local Python/SQLite fixture only; not production throughput."
            }
        finally:
            boundary.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", type=int, default=2000)
    parser.add_argument("--preload", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.actions, args.preload), indent=2))
