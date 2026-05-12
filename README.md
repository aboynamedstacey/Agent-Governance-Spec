# Agent Governance Specification

A draft interoperability specification for governing autonomous AI agents in regulated enterprise systems. It defines the components, contracts, and event schemas a governance layer needs in order to sit between an agent and the systems it touches.

Agent frameworks are now capable enough that companies are deploying them against production data and live APIs. The governance infrastructure has not kept up. A company running these systems cannot, today, hand an auditor a clean account of who authorized each agent's actions, what the bounds of that authority were, and how the authority moved when one agent handed work to another. LangChain, CrewAI, AutoGen, and the Claude SDK do not answer that question. This specification is an attempt to define the layer that does.

The current revision is 0.5.0-draft. The Core Profile is fully specified, and the Python reference implementation passes all 102 executed tests across the algorithmic and behavioral suites; 13 further cases are skipped because they are exercised through the integration harness rather than directly. The specification has not been submitted to a standards body and has not been through working-group review. No team independent of the author has yet built a second implementation, so cross-implementation interoperability remains an unproven claim. See [STATUS.md](STATUS.md) for conformance state and [CHANGELOG.md](CHANGELOG.md) for revision history.

## Scope clarification

Being explicit about scope matters here, because the phrase "AI governance" carries a lot of unrelated baggage.

- **Not a model-safety framework.** The specification does not evaluate model outputs for harmful content, bias, or alignment. Trust-and-safety tooling solves a different problem.
- **Not a legal compliance opinion.** Section 9.2 maps the specification's controls to NIST AI RMF, ISO/IEC 42001, the EU AI Act, MITRE ATLAS, and the OWASP LLM Top 10, but those mappings are illustrative. Adopting this specification does not on its own satisfy any cited regulation, and nothing here is legal advice.
- **Not a replacement for IAM or security tooling.** The specification assumes the surrounding identity, secrets, and network controls already exist. The governance layer sits above them and governs how a delegated agent uses what those systems already authorize.
- **Not a finished product.** This repository contains a specification and a single reference implementation, not a drop-in platform. There is no managed service, no UI, no support contract.

What the specification **is** is a governance control plane for delegated agent action — the layer that decides, records, and bounds what an autonomous agent is allowed to do on a human's behalf.

## The governance gap

Five questions come up in every regulated agent deployment, and none of the major frameworks answer them on their own:

1. What is each agent authorized to do, by whom, and until when?
2. What did each agent actually do, and on what evidence was the action permitted?
3. When one agent spawned another, how was authority narrowed, recorded, and bounded in time?
4. What evidence will support compliance review, regulatory inquiry, or incident reconstruction?
5. Does the same governance framework cover an agent's outputs (text, recommendations, messages to other agents) alongside its actions, or are those handled by separate tooling?

The closest commercial products solve part of the problem, typically by filtering agent output for safety or by wrapping tool calls to control which APIs an agent can hit. Few cover both surfaces, and almost none track how authority moves between agents, keep credentials out of the agent runtime, or maintain audit records that survive investigation.

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
- **Output Governance** evaluates agent outputs against the task and authority scope, not only agent actions.
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

1. **Read the thesis** — the opening of this README, through the System Guarantees table. Two minutes. That establishes what problem the specification is solving and the nine properties a conforming implementation preserves.
2. **Inspect the Core Profile** — the five-component table above. The whole architecture rests on those five components and the contracts between them. Anything labelled "Extension" is optional.
3. **Run the demo** — `python3 simulation/demo.py` from the repository root. It prints a narrated walkthrough of allow, attenuate, escalate, deny, and delegation scenarios with audit-chain output. Skip this if you do not have Python handy; the output is also readable directly in `simulation/demo.py`.
4. **Inspect one conformance vector** — open `tests/conformance-vectors.json` and search for `PE-mixed`. It is the test case that says: when a policy rule is ALLOW with mixed categorical and numeric constraint failures, the engine MUST DENY rather than attenuate. That single rule prevents a class of authority-leak bugs and is the kind of edge case that demonstrates the specification is written at the level of detail an implementer needs.
5. **Read one worked example** — `spec/04-worked-examples.md`, section F.4 ("Delegation Cascade with Authority Narrowing"). It traces a parent agent spawning a child agent and shows how authority narrows, how the audit chain records the cascade, and what the events look like end-to-end. This is the scenario most distinct from ordinary IAM.
6. **Read [STATUS.md](STATUS.md)** — current artifact maturity, test coverage, and the gaps the author has not closed.

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
| `STATUS.md` | Current conformance and coverage state. |
| `CHANGELOG.md` | Revision history. |

## Maturity and conformance

The Core Profile is fully specified. The Python reference implementation covers all Appendix D algorithms (D.1 through D.8). The repository ships with two test harnesses. The algorithmic harness checks each algorithm against the published conformance vectors. The behavioral harness exercises delegation cascades, authority expiration, escalation lifecycles, and audit-chain integrity.

The specification has also been hardened through a clean-room exercise. A second Python implementation was built using only the specification text, the JSON Schemas, and the conformance vectors, without reference to the original implementation. Two independent rounds of adversarial review then ran against the result. Between them they identified one security-critical attenuation rule, four schema violations, and a precedence inversion in the failure-handling algorithm. All findings were corrected.

The biggest remaining gap is not in the specification itself. It is the absence of an independently authored second implementation. Until two unrelated codebases run the same conformance vectors and produce the same results, the specification's portability claim is unproven.

Closing that gap is the next public milestone. An engineer or team building a second implementation — in any language — against the published specification, JSON Schemas, and conformance vectors would establish interoperability in the only way that counts. Contact through the channels in [CONTRIBUTING.md](CONTRIBUTING.md) is welcome.

## Standards positioning

The specification has not been submitted to NIST, ISO, IEEE, OASIS, or any industry working group. It is one author's draft. Most revisions have come from writing reference implementations against the specification and finding gaps in the text. Section 9.2 maps the specification's controls to NIST AI RMF, ISO/IEC 42001, MITRE ATLAS, the OWASP LLM Top 10, and the EU AI Act. The mappings are illustrative; adopting this specification does not on its own satisfy any cited regulation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
