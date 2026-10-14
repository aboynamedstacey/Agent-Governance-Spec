# Agent Governance Specification

A control layer for AI agents acting on delegated human authority.

The specification defines how to grant authority, narrow it when agents delegate,
enforce it at execution, and record why each action was permitted. It connects
those controls across agent runtimes through shared contracts, schemas, and
reference algorithms.

**Current revision: 0.7.0-draft.** Includes a Python reference implementation,
152 passing tests, and an executable local tool workflow.

## Design

Agents are untrusted processes. They request actions; the governance layer decides
whether those actions can proceed. Credentials stay at the execution boundary.
Every grant has an owner, a scope, and an expiration. Child agents receive a
subset of their parent's authority.

### Core components

| Component | Function |
|---|---|
| Authority Registry | Records grants, human authorization, scope, and expiration. |
| Agent Identity Service | Identifies agents and preserves their delegation lineage. |
| Policy Gate | Returns ALLOW, DENY, ESCALATE, or ATTENUATE for each request. |
| Execution Boundary | Holds credentials and executes authorized tool calls. |
| Audit Ledger | Records requests, decisions, policies, and outcomes in a cryptographic chain. |

### Optional extensions

- **Trust-adjusted evaluation:** adjusts scrutiny using independently verified outcomes, with replay protection and capability-specific scores.
- **Output governance:** checks declared topics and constraints, then routes delivery or review according to channel risk.
- **Adaptive escalation:** routes decisions to human reviewers and turns resolved cases into candidate policy rules.
- **Compliance projection:** maps governance records to established control frameworks.

The specification works with existing identity, secrets, and network infrastructure.
External agent-identity standards can satisfy the Identity Service contract.

## Run it

Requires Python 3.10 or later. From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python simulation/workflow.py
```

The workflow executes tools against a temporary SQLite database. It creates an
authorized draft, blocks an injected send request, rejects a recipient-cap
violation, and blocks a delegated child after revocation. It verifies both the
database effects and the audit chain.

Run the verification suites:

```bash
python simulation/reference_algorithms.py
python simulation/integration_tests.py
python -m unittest discover -s simulation -p 'test_*.py'
```

## What this revision improves

**Delegation preserves effective authority.** Checks account for rule order,
DENY exceptions, parameter caps, failure branches, and output controls. A child
cannot gain authority by changing the decision attached to an existing action
pattern or by supplying execution rules different from its validated scope.

**Trust follows outcomes.** Permission to act is not proof of a good result.
Verified successes and failures adjust trust; ALLOW, DENY, and ESCALATE do not.
Evidence replay cannot inflate scores, and inactivity does not clear tampering.

**Output checks have an enforcement path.** Lexical checks feed a delivery gate.
High-risk outputs require review, even when their keywords match the task.

**Audit evidence covers the decision.** Hashes cover the full recorded payload,
using RFC 8785 canonicalization. The workflow links execution to its request,
policy snapshot, grant, and originating human.

## System guarantees

A conforming implementation preserves nine properties:

1. Every action passes through the Policy Gate.
2. Authority originates in an accountable human decision.
3. Delegation only narrows authority.
4. Agents cannot access governance infrastructure.
5. Credentials remain outside agent control.
6. Every action has a reconstructable decision record.
7. Audit records are tamper-evident.
8. Governance failures stop execution.
9. Authority expires and requires renewal.

## Repository guide

| Path | Contents |
|---|---|
| [Core specification](spec/00-specification.md) | Architecture, component contracts, and guarantees. |
| [Type definitions](spec/01-type-definitions.md) | Governance objects and interfaces. |
| [Canonical algorithms](spec/02-algorithms.md) | Policy evaluation, delegation, audit hashing, trust, and output checks. |
| [Governance operations](spec/03-governance-of-governance.md) | Administration, incident response, and observability. |
| [Worked examples](spec/04-worked-examples.md) | End-to-end decision traces. |
| [Schemas](schemas/) | Machine-readable types and events. |
| [Conformance vectors](tests/conformance-vectors.json) | Shared inputs and expected decisions. |
| [Reference implementation](simulation/reference_algorithms.py) | Executable canonical algorithms. |
| [Local workflow](simulation/workflow.py) | Tool execution and blocked side effects. |
| [Regression tests](simulation/test_security_regressions.py) | Adversarial and contract tests. |
| [Implementation status](STATUS.md) | Verified coverage and current boundaries. |
| [Deployment validation](docs/operational-validation.md) | Pilot acceptance criteria. |
| [Changelog](CHANGELOG.md) | Revisions and migration notes. |

## Next milestones

Deploy one bounded workflow with a real agent runtime and measure containment,
latency, review load, and recovery. Build an independent implementation against
the same contracts and conformance vectors. Contributions toward either are
welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License and security

Apache License 2.0. See [LICENSE](LICENSE) and [SECURITY.md](SECURITY.md).
