# Implementation status

Last verified: 2026-09-17 — revision 0.7.0-draft.

This document distinguishes specified contracts, passing reference tests, and
unproven deployment properties. Test success is not production certification.

## Artifacts

| Artifact | Current state |
|---|---|
| Core specification | Normative contracts published; D.3 authority refinement hardened |
| Extension algorithms | Verified-outcome trust, explicit Tier 3 authority/effects, lexical output checks and delivery routing |
| Types and events | JSON Schemas; outcome evidence and lexical assessment added |
| Reference algorithms | Python, D.1–D.8; RFC 8785 audit canonicalization |
| Integration harness | In-memory lifecycle and policy tests; execution rules bound to validated scope |
| Local execution workflow | Real temporary SQLite effects through a registered-tool boundary |
| Adversarial regressions | Delegation, replay, output release, audit failures, tool effects, schema payloads, canonicalization |
| CI definition | Python 3.10 and 3.12 verification configured; local results below use Python 3.12 |
| Independent implementation | None validated; interoperability remains unproven |
| Production agent adapter | Not delivered; deployment acceptance criteria published |

## Verified results

Run the commands in the README after installing `requirements-dev.txt`.

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| `simulation/reference_algorithms.py` | 86 | 0 | 13 |
| `simulation/integration_tests.py` | 30 | 0 | 0 |
| `simulation/test_security_regressions.py` | 36 | 0 | 0 |
| **Total** | **152** | **0** | **13** |

The 13 algorithm-harness skips are retained stateful/behavioral vector definitions;
they are not counted as executed or passing. Related lifecycle behavior is
exercised in the integration suite. There are 53 published conformance vectors,
including 14 effective-delegation vectors; additional cases live in the runners.
Schema checks include structural validation and concrete payload checks for the
new outcome-evidence and lexical-assessment contracts, not every event payload.

The local workflow and illustrative demo also complete successfully. The workflow
creates one draft, sends zero messages, blocks an over-cap request and a revoked
child, and verifies its audit chain. It does not invoke an LLM or a cloud API.

## What changed

- Delegation preserves first-match decisions, exceptions, rule-local constraints,
  failure branches, resource operations, and output controls. Unknown implication
  cases fail closed. Pattern-only utility checks cannot authorize children.
- Identity creation checks actual and delegatable parent authority, binds execution
  rules to scope, copies inputs, and rejects inactive parents and exact expiry.
- ALLOW, DENY, ESCALATE, and ATTENUATE are neutral for trust. Verified outcomes
  require bound evidence with replay protection. Tampering creates persistent
  quarantine; inactivity does not restore adverse scores.
- Tier 3 requires authority confirmation and trusted tool-effect metadata. There
  is no implicit conversion from mutating to read-only operations.
- Lexical assessments explicitly disclaim semantic assurance. High-risk delivery
  requires separate authenticated review, even after a lexical PASS.
- Audit hashes cover full integration payloads and use RFC 8785 canonicalization.

## Conformance and remaining limitations

A Core implementation must implement the Authority Registry, Identity Service,
Policy Gate, Execution Boundary, and Audit Ledger, preserve the nine specified
properties, pass the applicable vectors, and emit the required schema-valid
records. The reference fixtures do not establish all of those deployment claims.

The integration harness is in-memory, uses test identities, and is not an
adversarially isolated credential proxy. The workflow's internal records are
illustrative, not complete wire-schema events. The local boundary serializes
requests; distributed revocation races, atomic shared budgets, durable queues,
remote idempotency, and crash recovery remain untested deployment obligations.
Hash chaining requires independent checkpoints to detect history replacement
or truncation. Trust scoring remains an uncalibrated heuristic. Evidence
structure validation does not authenticate an observer or establish outcome truth.

The next gates are an actual isolated agent deployment with measured failure
behavior and an independently authored implementation passing the same vectors.
See [operational validation](docs/operational-validation.md) for acceptance criteria.
