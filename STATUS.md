# Implementation status

Revision **0.7.0-draft**, verified locally on Python 3.12 on 2026-09-17.

## Verification

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Reference algorithms | 86 | 0 | 13 |
| Integration harness | 30 | 0 | 0 |
| Adversarial and contract regressions | 36 | 0 | 0 |
| **Total** | **152** | **0** | **13** |

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

## Current boundaries

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
