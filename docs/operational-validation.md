# Operational validation

## What the local workflow proves

`python simulation/workflow.py` uses the canonical rule evaluator and integration
identity service to mediate registered tools against a temporary SQLite store.
It proves the tested requests produce these effects:

| Request | Decision | Database effect |
|---|---|---|
| Authorized delegated draft | ALLOW | One draft inserted |
| Injected request to send | DENY | No message sent |
| Draft exceeding recipient cap | DENY | No additional draft |
| Draft after root grant revocation | DENY | No additional draft |

Regression tests also exercise audit write failure, decision tampering, exact
expiration, invalid parameters, and reconstruction of grantor, grant, lineage,
policy snapshot, request, decision, and outcome. The fixture blocks ATTENUATE pending a validated transformed request.

## First deployment acceptance criteria

1. Put a real agent runtime in a separate trust zone. Route its entire tool
   surface through an authenticated boundary; remove direct credentials, alternate
   egress, local execution, and unmanaged child-agent paths. Test attempted bypass.
2. Choose a single bounded workflow (for example, customer-response drafts),
   configure resource and recipient limits, and require review for external sends.
   Resource allowlists must be enforced by the adapter, not merely declared.
3. Authenticate the initiating human and each agent. Bind policies and requests
   immutably. Demonstrate cascading revocation during concurrent requests and
   define the authorization-to-execution race semantics.
4. Persist intent before execution and reconcile completed/failed/unknown outcomes.
   Use idempotency keys for remote side effects, atomic budget reservations, and
   replay protection. Test crash, timeout, duplicate delivery, and partial outage.
5. Emit full schema-valid events. Bind every execution to grant, identity lineage,
   policy version, request, decision, and evidence. Protect an external checkpoint
   of the audit head: a hash chain alone cannot detect complete history replacement
   or suffix truncation by an actor who can rewrite the store.
6. Authenticate independent outcome observers. Use task-specific criteria and
   retain fixed review thresholds for high-impact actions. Test evidence replay,
   same-capability easy-task farming, and incident reset governance.
7. Classify output channels in trusted policy. Bind review approvals to exact
   output digests and audiences; edits invalidate approval. Measure false positives,
   false negatives, latency, escalation volume, and operator effort.

Record the baseline without governance and with governance. Report blocked
unauthorized side effects, false denials, latency percentiles, throughput, review
load, recovery behavior, and residual bypasses. No benchmark results are claimed
by this repository until measured.

## Independent interoperability gate

An independent author should implement from the normative text, schemas, and
vectors without copying this implementation. Compare policy decisions, delegation
refinements, byte-identical audit canonicalization, and failure behavior. Test
unicode keys, numeric representations, wildcard exceptions, expiry boundaries,
and outcome-evidence replay. This revision does not supply independent authorship.

Implementation boundaries and coverage are recorded in [STATUS.md](../STATUS.md).
