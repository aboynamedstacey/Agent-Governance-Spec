# Implementation status

Revision **0.7.0-draft**. GitHub Actions verification passed on Python 3.10 and 3.12 on 2026-10-14.

## Verification

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Reference algorithms | 86 | 0 | 13 |
| Integration harness | 30 | 0 | 0 |
| Adversarial and contract regressions | 61 | 0 | 0 |
| **Total** | **177** | **0** | **13** |

The 13 skips are retained stateful vector definitions; related lifecycle behavior
runs in the integration suite. They are not counted as passing. The repository
contains 53 published conformance vectors, including 14 delegation cases.
Schema checks cover structure and concrete payloads for the new outcome-evidence
and lexical-assessment contracts.

The local workflow and illustrative demo complete successfully. The workflow
creates one draft, sends zero messages, blocks over-cap and revoked-child requests,
and verifies the audit chain. CI is configured for Python 3.10 and 3.12.

## Delivered

- First-match authority refinement covering rule decisions, exceptions, caps,
  failure branches, resource permissions, and output controls.
- Identity creation bound to validated execution rules and live parent authority.
- Verified-outcome trust updates with evidence binding and replay protection.
- Explicit authority and tool-effect inputs to Tier 3 scrutiny routing.
- Lexical output assessment and a channel-sensitive delivery gate.
- Full-payload audit hashing with RFC 8785 canonicalization.
- Executable SQLite workflow, regression suites, schemas, and migration notes.
- Single-use escalation lifecycle checks: current grant and ancestor authority,
  timeout boundaries, policy snapshots, global and rule-level constraints,
  and non-executing approvals. Twelve adversarial regression tests added.

## Fast-path optimization

- Rate and damage checks use keyed rolling windows instead of history-wide scans.
  The in-memory action log is now a 256-entry diagnostic sample, not the
  authorization source.
- The execution fixture validates only the unverified audit suffix per action,
  and exposes full-chain verification for off-path checks and quarantine.
- Repeated policy snapshots are stored as content-addressed audit objects, with
  policy digests in routine requests.
- A local benchmark reports p50/p95/p99 latency and bytes per action. See
  [performance and storage profile](docs/performance-profile.md) for pilot
  targets, caveats, and production requirements.
- Thirteen new security regressions cover bounded counters, cross-grant type
  limits, ancestor/descendant scope, time-window expiry,
  audit-tail corruption, truncation, full verification, and side-effect denial.

## Current boundaries

The optimized audit-head guard is trusted process-local state, not a durable
independently anchored log. Concurrency, restart recovery, atomic budget
reservations, and persistent external audit checkpoints are not implemented.

Escalation approval in the reference stack records a review outcome but does
not create an executable authorization token. Only a future trusted adapter can
atomically consume an approved request after rechecking live authority.

The reference stack is an in-memory test implementation. The local workflow
replays agent requests against real database operations; it does not invoke an
LLM or isolate an adversarial agent process. Deployment still requires identity
authentication, credential isolation, persistent state, full wire-schema events,
and handling of concurrent requests and uncertain remote outcomes.

Trust scores are heuristic and need calibration against independently observed
results. Lexical output scores do not establish semantic correctness. Audit
chains need independent checkpoints to detect whole-history replacement or
truncation.

The next validation steps are an isolated agent pilot and an independently
authored implementation. See [deployment validation](docs/operational-validation.md)
for the acceptance criteria.
