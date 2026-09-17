# Agent Governance Specification

A draft interoperability specification for the governance of autonomous AI agents in regulated enterprise systems. It defines the components, contracts, and event schemas that a governance layer needs in order to sit between an agent and the systems it touches, and it is designed to consume the agent-identity standards now emerging in the ecosystem rather than to reinvent them.

Agent frameworks have grown capable enough that companies are deploying them against production data and live APIs, and the governance machinery around them has not kept pace. The engineering problem is to produce a consistent account of who authorized each action, how that authority was bounded, and what changed during delegation across runtimes. This specification defines contracts for that layer; deployments must evaluate how their existing identity and agent tooling already meets them.

The current revision is **0.7.0-draft**. The repository includes normative
contracts, machine-readable schemas, a Python reference implementation, and
an executable local tool workflow. Delegation checks preserve effective
first-match authority; trust updates consume verified outcomes; lexical output
checks carry explicit evidence limits and a delivery gate.

This is an author's draft, not a ratified standard or production platform.
No independently authored second implementation has been validated. See
[STATUS.md](STATUS.md) for measured coverage, limitations, and next milestones.

## Run the controls

Requires Python 3.10 or later. From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python simulation/reference_algorithms.py
python simulation/integration_tests.py
python -m unittest discover -s simulation -p 'test_*.py'
python simulation/workflow.py
```

The workflow creates a real draft in a temporary SQLite database, blocks an
unauthorized send request representative of prompt injection, rejects a
recipient-cap violation, and blocks a delegated child after grant revocation.
It checks database effects and the audit chain. It does not invoke an LLM,
connect to a cloud account, or establish an OS isolation boundary. It tests
containment of requests a model could emit, not resistance to model deception.
[Workflow and acceptance criteria](docs/operational-validation.md).

## Scope clarification

Being explicit about scope matters here, because the phrase "AI governance" carries a lot of unrelated baggage.

- **Not a model-safety framework.** The specification does not evaluate model outputs for harmful content, bias, or alignment. Trust-and-safety tooling solves a different problem.
- **Not a legal compliance opinion.** Section 9.2 maps the specification's controls to NIST AI RMF, ISO/IEC 42001, the EU AI Act, MITRE ATLAS, and the OWASP LLM Top 10, but those mappings are illustrative. Adopting this specification does not on its own satisfy any cited regulation, and nothing here is legal advice.
- **Not a replacement for IAM or security tooling.** The specification assumes the surrounding identity, secrets, and network controls already exist. The governance layer sits above them and governs how a delegated agent uses what those systems already authorize.
- **Not a finished product.** This repository contains a specification and a single reference implementation, not a drop-in platform. There is no managed service, no UI, no support contract.

What the specification **is** is a governance control plane for delegated agent action: the layer that decides, records, and bounds what an autonomous agent is allowed to do on a human's behalf.

## The governance gap

The specification organizes agent control around five questions:

1. What is each agent authorized to do, by whom, and until when?
2. What did each agent actually do, and on what evidence was the action permitted?
3. When one agent spawned another, how was authority narrowed, recorded, and bounded in time?
4. What evidence will support compliance review, regulatory inquiry, or incident reconstruction?
5. Does the same governance framework cover an agent's outputs (text, recommendations, messages to other agents) alongside its actions, or are those handled by separate tooling?

The intended contribution is a portable contract joining authority, enforcement,
and evidence across agent runtimes. The repository does not establish feature
uniqueness against current commercial products or demonstrate customer demand.

## Design

The architecture treats AI agents as untrusted processes operating under delegated human authority.

**Untrusted.** The governance layer decides what an agent is allowed to do, and does not take the agent's word for what it has actually done. When the system needs to confirm that an action took place under authority, it reads the audit record. An agent's account of its own behavior carries no weight.

**Delegated.** Agents start with no permissions of their own. Every permission an agent holds is a human grant with explicit bounds on actions, resources, and time. When one agent spawns another, the child inherits a subset of the parent's authority. A delegation chain only narrows.

**Human authority.** Every chain of authority terminates at a human decision. Grants expire. The audit record keeps each agent action traceable back to the person whose decision started the chain.

From this premise the specification derives a Core Profile of five components, plus four optional Extension Profiles.

### Core Profile

| Component | Function |
|---|---|
| Authority Registry | Records the actions each agent is permitted to perform, the human who authorized the grant, and the grant's expiration. |
| Agent Identity Service | Issues each agent a signed credential and maintains the chain of identities back to the originating human. |
| Policy Gate | Intercepts every agent action and produces one of four decisions: allow, deny, escalate to human review, or attenuate (proceed with parameters narrowed within the agent's authority). |
| Execution Boundary | Proxies all tool calls. Holds all credentials. Agents do not receive credentials directly. |
| Audit Ledger | Maintains an append-only, cryptographically chained record of every governance decision and the evidence on which it rested. |

### Extension Profiles

- **Trust-Adjusted Evaluation** adjusts the level of scrutiny each action receives based on the agent's track record, without expanding the agent's underlying authority.
- **Output Governance** supplies lexical task checks and a delivery gate. High-risk release requires separate authenticated review; lexical PASS is not semantic assurance.
- **Adaptive Escalation** routes unresolved decisions to human review and promotes resolved cases to candidate policy rules through a separation-of-duties workflow.
- **Compliance Projection** maps the specification's controls to NIST AI RMF, ISO/IEC 42001, the EU AI Act, MITRE ATLAS, and the OWASP LLM Top 10.

## System guarantees

A conforming implementation preserves nine properties regardless of agent behavior.

1. **No bypass.** Every action passes through the Policy Gate.
2. **Human origin.** Every chain of authority terminates at a human decision.
3. **Authority only attenuates.** Child agent authority is a subset of parent authority, never an extension of it.
4. **Agent isolation.** Agents cannot access governance infrastructure.
5. **Credential isolation.** Agents do not hold credentials.
6. **Decision traceability.** Every action carries a complete causal record.
7. **Tamper evidence.** Audit records are cryptographically chained; modification is detectable.
8. **Fail-closed behavior.** Governance failure halts agent action. It does not permit unsupervised continuation.
9. **Authority expiration.** Grants are time-bound. Permanent authority is forbidden.

## Quickstart for evaluators

Most readers of this repository will not run the Python files. The path below is for the recruiter, CTO, general counsel, board member, or investor who wants to assess what the specification actually is, in roughly five minutes, without becoming an implementer.

1. **Read the thesis**: the opening of this README, through the System Guarantees table. Two minutes. That establishes what problem the specification is solving and the nine properties a conforming implementation preserves.
2. **Inspect the Core Profile**: the five-component table above. The whole architecture rests on those five components and the contracts between them. Anything labelled "Extension" is optional.
3. **Run the local workflow**: `python simulation/workflow.py`. It executes real local tool effects through a boundary and verifies that denied requests produce no side effects. The separate `simulation/demo.py` remains an illustrative narrative, not a production implementation.
4. **Inspect one conformance vector**: open `tests/conformance-vectors.json` and search for `PE-mixed`. It is the test case that says: when a policy rule is ALLOW with mixed categorical and numeric constraint failures, the engine MUST DENY rather than attenuate. That single rule prevents a class of authority-leak bugs and is the kind of edge case that demonstrates the specification is written at the level of detail an implementer needs.
5. **Read one worked example**: `spec/04-worked-examples.md`, section F.4 ("Delegation Cascade with Authority Narrowing"). It traces a parent agent spawning a child agent and shows how authority narrows, how the audit chain records the cascade, and what the events look like end-to-end. This is the scenario most distinct from ordinary IAM.
6. **Read [STATUS.md](STATUS.md)**: current artifact maturity, test coverage, and the gaps the author has not closed.

That sequence is enough to evaluate whether the specification is serious, what it covers, and what it does not.

## Repository contents

| Path | Contents |
|---|---|
| `spec/00-specification.md` | Sections 1–10 and Appendices A–B of the specification. |
| `spec/01-type-definitions.md` | Appendix C: type definitions for all governance objects. |
| `spec/02-algorithms.md` | Appendix D: canonical algorithms (D.1 pattern matching; D.2 policy evaluation; D.3 scope subset; D.4 rate limits; D.5 hash chain; D.6 trust state; D.7 Tier 3 policy evaluation; D.8 output evaluator). |
| `spec/03-governance-of-governance.md` | Appendix E: administrative roles, dual control, incident severity classification, and observability metrics. |
| `spec/04-worked-examples.md` | Appendix F: nine traced end-to-end scenarios. |
| `schemas/types.schema.json` | JSON Schema for all governance types. |
| `schemas/events.schema.json` | JSON Schema for all event types. |
| `tests/conformance-vectors.json` | Conformance test vectors used by the reference implementation. |
| `simulation/reference_algorithms.py` | Python reference implementation; normative for Appendix D. |
| `simulation/integration_tests.py` | Behavioral and integration test harness. |
| `simulation/workflow.py` | Executable local tool effects and authority containment. |
| `simulation/test_security_regressions.py` | Adversarial regression suite. |
| `docs/operational-validation.md` | Evidence limits and production acceptance criteria. |
| `STATUS.md` | Current conformance and coverage state. |
| `CHANGELOG.md` | Revision history. |

## Maturity and conformance

The Core Profile has normative contracts and executable reference algorithms. The algorithmic suite checks published vectors; the integration harness checks lifecycle behavior; adversarial regressions challenge authority refinement, outcome-evidence replay, output release, and real local side effects. These tests do not certify a production deployment.

The specification has also been hardened through a clean-room exercise. A second Python implementation was built using only the specification text, the JSON Schemas, and the conformance vectors, without reference to the original implementation. Two independent rounds of adversarial review then ran against the result. Between them they identified one security-critical attenuation rule, four schema violations, and a precedence inversion in the failure-handling algorithm. All findings were corrected.

Two remaining gates are independent interoperability testing and a production deployment that demonstrates isolation, durable evidence, revocation under concurrency, and failure recovery. Until two unrelated codebases run the same conformance vectors and produce the same results, the specification's portability claim remains unproven.

Closing that gap is the next public milestone. An engineer or team building a second implementation in any language, against the published specification, JSON Schemas, and conformance vectors, would supply the independent confirmation the portability claim currently lacks. Contact through the channels in [CONTRIBUTING.md](CONTRIBUTING.md) is welcome.

## Standards positioning

The specification has not been submitted to NIST, ISO, IEEE, OASIS, or any industry working group. It is one author's draft, and most of its revisions have come from writing reference implementations against it and finding the gaps in the text.

Its place in the landscape is deliberate. Rather than compete with the agent-identity work now emerging, such as AIP and the MIT Authenticated Delegation model, the specification is built to consume that work as an identity input and to concentrate on the layers those efforts leave open: holding credentials away from the agent at the Execution Boundary, governing what agents say and not only what they do, and projecting the resulting record onto the named compliance frameworks. Section 9.2 maps the specification's controls to the NIST AI RMF, ISO/IEC 42001, MITRE ATLAS, the OWASP LLM Top 10, and the EU AI Act. Those mappings are illustrative, and adopting the specification does not on its own satisfy any regulation it cites.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
