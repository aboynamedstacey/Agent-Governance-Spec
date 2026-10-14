# Performance and storage profile

This is an optional engineering profile for implementers of the Agent Governance
Specification. Core authorization guarantees are unchanged. The numerical
targets below are pilot acceptance targets, **not verified measurements** or
claims of production readiness.

## Routine authorization path

Local effective-authority validation, cached ordered policy evaluation,
bounded-window usage counters, a trusted execution proxy, and an incremental
audit append are the only expected routine synchronous governance steps.
Signature and authorization verification must include expiry, delegation lineage,
policy version, and revocation freshness. Do not memoize an ALLOW result past a
change in these inputs. Production revocation/identity state may require a
synchronous lookup for consequential writes; safety takes precedence over a
latency target.

Do not put any of the following on the routine path:

- Full verification of all historical audit hashes.
- O(number of historical actions) sliding-window/budget scans.
- An LLM call solely for deterministic policy evaluation.
- Repeated serialization/storage of an unchanged full policy or entire context.
- Retrieval of unbounded trust history or cold audit records.

The reference harness demonstrates rolling indexes, content-addressed policy
snapshots, and incremental audit-head checks. It is intentionally single-process
and does **not** supply distributed counter atomicity or a production event sink.

## Deployment targets

| Measurement | Initial target | Notes |
| --- | --- | --- |
| Added routine governance latency, p95 | < 20 ms | Excludes model inference and downstream tool/API time |
| Added routine governance latency, p99 | < 50 ms | Same exclusions; report cold and warm separately |
| History sensitivity | No material growth with audit length | Test 0, 10k, 100k, and 1m prior events |
| Authorization failures | Fail closed | Test revocation, policy drift, ledger/backpressure, clock boundaries |
| Audit overhead | Report encoded bytes per event/action | Include indexes, replication, checkpoints, and retention classes |
| Resource use | Report CPU, memory, I/O and queue depth | Measure under concurrency and burst load |

Targets apply only to the **governance-added** component of a real agent
workflow. Record baseline and governed latency distributions separately with
identical tools, request parameters, concurrency, and underlying data. Report
tool calls/s, peak and steady-state CPU, p50/p95/p99, error rate, and timeouts.
Do not infer performance from the reference Python/SQLite benchmark alone.

## Rate and budget accounting

Maintain keyed rolling windows, exact window boundaries, and indexed aggregates,
not repeated log scans. TYPE limits must aggregate across all grants with the
same agent type; DELEGATION_TREE limits count ancestors and descendants without
including unrelated siblings. New policy activation and raised limits require
correct counter rehydration or fail-closed behavior.

In production, counters and damage budgets MUST be
atomically reserved with execution intent before admitting concurrent writes,
reconciled with confirmed outcomes, and recoverable after restart. A local
deque is not sufficient in a multi-worker deployment. Sharding must not allow
a child agent or another region to evade shared grant or delegation-tree limits.

Keep only the active window and enough data for correct expiry or distinct event
reservation semantics. Batch/off-path sweeping is appropriate to release idle
keys. Never replace an exact safety limit with an approximate estimator.

## Audit and durable intent

The reference `AuditHeadGuard` checks the previously pinned head and validates
only newly appended entries during a routine action. The entire chain can be
checked separately via `verify_audit_full()`, which quarantines the guard if
verification fails. A historical mutation outside the recent suffix may be
invisible until the deep verifier runs. This is an explicitly documented
limitation, not a guarantee of immediate comprehensive tamper detection.

A production deployment needs independently protected, durable chain-head
checkpoints, append-only access controls, recovery after crash, and verified
checkpoint advancement. A locally mutable list or hash variable is not such
a trust anchor. In particular, local incremental verification does not protect
against an attacker with write access to both the ledger and the checkpoint.

For consequential external effects, append durable **execution intent** before
the effect and record completion or an uncertain outcome afterward. Use
idempotency keys and reconciliation for APIs that cannot participate in the
same transaction. An asynchronous buffer may be used only if its durability,
capacity, overflow behavior, and permitted action classes are explicit.
Do not acknowledge an unaudited consequential write as successful.

## Storage design

Persist immutable authority grants, policy versions, and large context
snapshots once by content digest, with digest references in each audit event.
Retain enough information to reconstruct the original policy, action parameters,
human grantor, decision and evidence chain. A detached digest without the
authenticated source content does not meet the traceability guarantee.

The reference workflow stores one `PolicySnapshotStored` event for each policy
digest per boundary instance, and attaches that digest to subsequent requests.
Across restarts, durable snapshot catalogs and deduplication need a trusted
storage service.

Recommended organization-specific retention tiers:

- Hot: indexed, recent data required for incident response and replay controls.
- Warm: searchable audit summaries and policy/evidence metadata.
- Cold: compressed, immutable records with access-controlled context retrieval.

Actual retention durations are jurisdiction- and purpose-specific. Project
storage from measured **encoded bytes/action**, tool payload size, index
amplification, replication, backups, and write rate. Full model contexts should
not be duplicated in routine audit entries. Avoid putting raw secrets, large
customer documents, or unrestricted responses in an always-on hot index.

## Reproducible local benchmark

```sh
python simulation/benchmark.py --actions 2000
python simulation/benchmark.py --actions 2000 --preload 10000
```

Results include local action latency distribution, audit bytes per action,
an off-path full-chain verification measurement, and SQLite file size. These
are diagnostic and machine-dependent. The benchmark does not simulate network,
independent identity proofs, real concurrent workers, or crash consistency.

## Acceptance gate for production pilots

Verify no unsupported bypass routes; run adversarial revocation during
execution, policy replacement, concurrent budget exhaustion, lost acknowledgments,
queue saturation, checkpoint replacement, and corruption of older audit entries.
A performance optimization is not acceptable if it increases unauthorized
side effects, audit loss, or unbounded memory use, even if p99 latency improves.
