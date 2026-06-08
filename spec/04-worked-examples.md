# Appendix F: Worked Examples

Nine end-to-end scenarios showing complete event traces through the governance system.

F.1–F.3 cover the Policy Gate's three permissive outcomes at Tiers 1 and 2 (allow, attenuate, escalate-then-approve). F.4–F.9 cover behaviors that implementers are most likely to get wrong: delegation attenuation (Guarantee 3), clean denial, authority expiration mid-task (Guarantee 9), tamper detection (Guarantee 7), fail-closed operation (Guarantee 8), and Output Evaluator intervention (Output Governance extension).

---

## F.1 Simple Allow: Database Query

A research agent queries a database. The action is within scope, satisfies all constraints, and resolves at Tier 1.

### Setup

```json
{
  "grant": {
    "grant_id": "grant-research-001",
    "agent_type": "research-agent",
    "granted_by": "human:alex@org",
    "ttl": "4h",
    "policy_version": "2.1.0"
  },
  "agent": {
    "instance_id": "agent-abc123",
    "lineage_chain": ["agent-abc123"],
    "trust_tiers": { "DATA_READ": "HIGH", "DATA_WRITE": "LOW" }
  },
  "action": {
    "action_type": "database.query",
    "params": { "table": "customers", "limit": 100, "fields": ["name", "region"] },
    "resource": { "resource_type": "database", "resource_id": "analytics-db-prod" }
  }
}
```

### Evaluation Trace

**Tier 1: Deterministic Rule Check**
1. Identity valid? `agent-abc123` is signed and unexpired. **Pass.**
2. Authority expired? Grant `grant-research-001` is active and within TTL. **Pass.**
3. Action in scope? `database.query` matches `database.*` in authorized_actions with decision ALLOW. **Match found.**
4. Rate limit? 0/100 queries in current window. **Pass.**
5. **Decision: ALLOW at Tier 1.** No need to proceed to Tier 2.

### Events Emitted

```
Event 1: ActionRequested
  event_id: "evt-001"
  agent_identity: { instance_id: "agent-abc123", ... }
  action_type: "database.query"
  causal_parent: null  (root action in this task)

Event 2: ActionEvaluated
  event_id: "evt-002"
  decision: "ALLOW"
  tier: 1
  reason_code: null  (no denial reason — action was allowed)
  policy_version: "2.1.0"
  causal_parent: "evt-001"

Event 3: ActionExecuted
  event_id: "evt-003"
  action_type: "database.query"
  outcome: { status: "SUCCESS", duration_ms: 45 }
  causal_parent: "evt-002"
```

### Audit Chain

```
evt-001 (ActionRequested) → evt-002 (ALLOW, Tier 1) → evt-003 (SUCCESS)
```

Total latency added by governance: <1ms (Tier 1 in-memory evaluation only).

---

## F.2 Attenuation: Bulk Write Reduced

An agent attempts to write 200 records. Policy allows writes but constrains batch size to 50. The action is attenuated rather than denied.

### Setup

```json
{
  "policy_rule": {
    "pattern": "database.write",
    "decision": "ALLOW",
    "constraints": [
      { "field": "record_count", "operator": "LESS_THAN_OR_EQUAL", "value": 50 }
    ]
  },
  "action": {
    "action_type": "database.write",
    "params": { "table": "staging", "record_count": 200, "data": "[...]" }
  }
}
```

### Evaluation Trace

**Tier 1: Deterministic Rule Check**
1. Identity valid? **Pass.**
2. Authority active? **Pass.**
3. Action in scope? `database.write` matches rule with decision ALLOW. **Match found, but it has constraints, so proceed to Tier 2.**
4. Rate limit? **Pass.**

**Tier 2: Constraint Evaluation**
5. Constraint: `record_count LESS_THAN_OR_EQUAL 50`. Actual value: 200. **Constraint violated.**
6. Attenuation possible? Yes, the numeric constraint can be capped. Attenuate `record_count` from 200 to 50.
7. **Decision: ATTENUATE at Tier 2.**

### Attenuation Record

```json
{
  "original_action": {
    "action_type": "database.write",
    "params": { "table": "staging", "record_count": 200 }
  },
  "attenuated_action": {
    "action_type": "database.write",
    "params": { "table": "staging", "record_count": 50 }
  },
  "modifications": [
    {
      "field": "record_count",
      "original_value": 200,
      "attenuated_value": 50,
      "reason": "Exceeds LESS_THAN_OR_EQUAL constraint",
      "policy_rule": "database.write constraint #1"
    }
  ]
}
```

### Events Emitted

```
Event 1: ActionRequested
  event_id: "evt-010"
  action_type: "database.write"
  action_params: { record_count: 200 }
  causal_parent: "evt-009"  (prior action in this task)

Event 2: ActionEvaluated
  event_id: "evt-011"
  decision: "ATTENUATE"
  tier: 2
  reason_code: "CONSTRAINT_VIOLATION"
  reason_detail: "record_count=200 exceeds limit 50, attenuated"
  attenuation: { ... see above ... }
  causal_parent: "evt-010"

Event 3: ActionExecuted
  event_id: "evt-012"
  action_type: "database.write"
  action_params: { record_count: 50 }  ← attenuated value
  outcome: { status: "SUCCESS", duration_ms: 320 }
  causal_parent: "evt-011"
```

### What the Agent Sees

The agent requested a 200-record write. The Execution Boundary executed a 50-record write. The agent receives the result of the attenuated action. The agent's framework MAY inform the agent that attenuation occurred (implementation-specific), but the governance layer does not negotiate with the agent about the attenuation.

---

## F.3 Escalation with Candidate Rule Promotion

An agent attempts to send an email. Policy requires human review. The human approves and the system generates a candidate rule for future automation.

### Setup

```json
{
  "policy_rule": {
    "pattern": "gmail.messages.send",
    "decision": "ESCALATE"
  },
  "escalation_rule": {
    "notify": ["human:jane@org"],
    "timeout": "30m",
    "on_timeout": "DENY"
  },
  "action": {
    "action_type": "gmail.messages.send",
    "params": { "to": "client@partner.com", "subject": "Q2 Review", "body": "..." }
  }
}
```

### Evaluation Trace

**Tier 1: Deterministic Rule Check**
1. Identity valid? **Pass.**
2. Authority active? **Pass.**
3. Action in scope? `gmail.messages.send` matches rule with decision ESCALATE.
4. **Decision: ESCALATE at Tier 1.** Action is paused.

**Escalation Package Sent to Human**

```json
{
  "escalation_id": "esc-001",
  "action": { "action_type": "gmail.messages.send", "params": { "to": "client@partner.com" } },
  "agent_identity": { "instance_id": "agent-abc123", "lineage_chain": ["agent-abc123"] },
  "reason": "Policy requires human review for gmail.messages.send",
  "tier_results": [
    { "tier": 1, "evaluated": true, "result": "RESOLVED", "decision": "ESCALATE", "reason_code": "ESCALATION_REQUIRED" }
  ],
  "risk_assessment": "MEDIUM",
  "default_decision": "DENY",
  "timeout": "30m",
  "on_timeout": "DENY"
}
```

**Human Resolves: APPROVE**

```json
{
  "escalation_id": "esc-001",
  "decision": "APPROVE",
  "justification": "Verified: client@partner.com is authorized external contact for Project Atlas. Email content reviewed — contains no confidential data. Approve this send.",
  "decider_identity": "human:jane@org",
  "candidate_rule": {
    "candidate_id": "cr-001",
    "source_escalation": "evt-022",
    "proposed_rule": {
      "pattern": "gmail.messages.send",
      "decision": "ALLOW",
      "constraints": [
        { "field": "to_domain", "operator": "EQUALS", "value": "partner.com" }
      ]
    },
    "proposed_tier": 2,
    "confidence": 0.7,
    "status": "PROPOSED"
  }
}
```

### Events Emitted

```
Event 1: ActionRequested
  event_id: "evt-020"
  action_type: "gmail.messages.send"

Event 2: ActionEvaluated
  event_id: "evt-021"
  decision: "ESCALATE"
  tier: 1
  reason_code: "ESCALATION_REQUIRED"
  causal_parent: "evt-020"

Event 3: ActionEscalated
  event_id: "evt-022"
  reason: "Policy requires human review"
  tier_results: [{ tier: 1, result: "RESOLVED", decision: "ESCALATE" }]
  causal_parent: "evt-021"

Event 4: EscalationResolved
  event_id: "evt-023"
  decision: "APPROVE"
  justification: "Verified: client@partner.com is authorized..."
  decider_identity: "human:jane@org"
  candidate_rule: { candidate_id: "cr-001", ... }
  causal_parent: "evt-022"

Event 5: ActionExecuted
  event_id: "evt-024"
  action_type: "gmail.messages.send"
  outcome: { status: "SUCCESS", duration_ms: 1200 }
  causal_parent: "evt-023"
```

### Candidate Rule Lifecycle

The candidate rule `cr-001` proposes: "Allow gmail.messages.send when the recipient domain is partner.com." This enters the governed promotion pipeline:

```
1. cr-001 created (status: PROPOSED)
   Source: Escalation esc-001, resolved by human:jane@org

2. Grant Administrator human:bob@org reviews
   - Does the rule conflict with existing policy? No.
   - Is the confidence appropriate? 0.7 — reasonable for domain-scoped allow.
   - Is the constraint tight enough? Allows sends to partner.com only.

3. human:bob@org approves (human:bob != human:jane — separation enforced)
   cr-001 status: APPROVED

4. Rule promoted to policy version 2.2.0
   cr-001 status: PROMOTED
   PolicyUpdated event emitted

5. Next time an agent tries gmail.messages.send to partner.com:
   Tier 2 evaluates the new rule → ALLOW
   No escalation needed. Human judgment has been encoded into policy.
```

### Causal Chain (Full Trace)

Walking backward from the successful send:

```
evt-024 (ActionExecuted: SUCCESS)
  ← evt-023 (EscalationResolved: APPROVE by human:jane@org)
    ← evt-022 (ActionEscalated: policy requires human review)
      ← evt-021 (ActionEvaluated: ESCALATE at Tier 1)
        ← evt-020 (ActionRequested: gmail.messages.send)
```

Any auditor can reconstruct: this email was sent because human:jane@org approved it after reviewing the content, the recipient, and the agent's lineage. The authority for the agent traces to human:alex@org via the grant. Two humans are in the chain. The decision is fully traceable.

---

## F.4 Delegation Cascade with Authority Narrowing

A parent agent spawns a child with a narrowed scope. The child succeeds on an in-scope action and is denied on an action that is outside the child's (attenuated) scope but would have been permitted for the parent. Demonstrates Guarantee 3 (Authority Only Attenuates).

### Setup

```json
{
  "parent_agent": {
    "instance_id": "agent-research-001",
    "lineage_chain": ["agent-research-001"],
    "authorized_actions": ["database.read", "database.write"],
    "delegation_depth_remaining": 2
  },
  "spawn_request": {
    "parent": "agent-research-001",
    "child_type": "subquery-agent",
    "requested_child_scope": ["database.read"]
  }
}
```

### Spawn Evaluation (Identity Service)

1. Parent has delegation rights? **Pass.**
2. Child scope `["database.read"]` is a subset of parent's delegatable scope `["database.read", "database.write"]`? **Pass.**
3. Delegation depth limit? Parent has 2 remaining; child will have 1. **Pass.**
4. Mint child identity.

### Child Identity Minted

```json
{
  "instance_id": "agent-subquery-042",
  "parent_id": "agent-research-001",
  "lineage_chain": ["agent-research-001", "agent-subquery-042"],
  "authorized_actions": ["database.read"],
  "delegation_depth_remaining": 1
}
```

### Event 1: Spawn

```
Event: AgentSpawned
  event_id: "evt-100"
  parent_identity: { instance_id: "agent-research-001", ... }
  child_identity: { instance_id: "agent-subquery-042", ... }
  scope_attenuation: { removed: ["database.write"], retained: ["database.read"] }
  causal_parent: "evt-099"  (parent's prior action)
```

### Child Action 1: In-Scope Read

The child issues `database.read`.

**Tier 1:**
1. Identity valid? **Pass.**
2. Action in scope of child's authority? `database.read` is in `["database.read"]`. **Pass.**
3. Rate limit? **Pass.**
4. **Decision: ALLOW at Tier 1.**

```
Event: ActionRequested   evt-101   agent-subquery-042   database.read
Event: ActionEvaluated   evt-102   ALLOW, Tier 1
Event: ActionExecuted    evt-103   SUCCESS
```

### Child Action 2: Out-of-Scope Write (Denied)

The child attempts `database.write`. The parent's authority includes write, but the child's attenuated scope does not.

**Tier 1:**
1. Identity valid? **Pass.**
2. Action in scope of **child's** authority? `database.write` is not in `["database.read"]`. **Fail.**
3. **Decision: DENY at Tier 1.** Reason: `SCOPE_VIOLATION`.

```
Event: ActionRequested   evt-104   agent-subquery-042   database.write
Event: ActionEvaluated   evt-105   DENY, Tier 1, reason_code: SCOPE_VIOLATION
Event: ActionDenied      evt-106   causal_parent: evt-105
```

### What the Agent Framework Sees

The child receives DENY with `reason_code = SCOPE_VIOLATION`. The reason code does not reveal that the parent *did* have write authority, since the Policy Gate evaluates against the child's identity only. The agent framework may terminate the child, retry with a narrower action, or request re-delegation via a human-initiated grant.

### Causal Chain

```
evt-103 (child read SUCCESS)
  ← evt-102 (ALLOW)
    ← evt-101 (ActionRequested)
      ← evt-100 (AgentSpawned)
        ← evt-099 (parent's prior action)
          ← ... ← parent grant ← human:alex@org
```

Both the successful read and the denied write trace back to the same human grant. The chain tells the auditor: "the child was authorized to read because its parent was; the child was denied write because its spawn narrowed the scope, regardless of the parent's permissions."

---

## F.5 Clean DENY: Out-of-Scope Action

An agent attempts an action that is not in its authority at all. Denied at Tier 1 with no attenuation attempted. Demonstrates Guarantee 4 (Agent Isolation) in the structure of the DENY response.

### Setup

```json
{
  "agent": {
    "instance_id": "agent-research-077",
    "authorized_actions": ["database.read", "database.query"],
    "authority_scope": "analytics_db.*"
  },
  "action": {
    "action_type": "admin.users.delete",
    "params": { "user_id": "u-9812" },
    "resource": { "resource_type": "identity_provider", "resource_id": "okta-prod" }
  }
}
```

### Evaluation Trace

**Tier 1:**
1. Identity valid? **Pass.**
2. Authority active? **Pass.**
3. Action in scope? `admin.users.delete` has no matching rule in the agent's authorized_actions. Default deny applies.
4. Attenuation possible? Not applicable, since the action is entirely outside scope. Attenuation applies only when an action is within scope, the matching rule is ALLOW, and the violated constraints are non-strict numeric bounds (LTE/GTE) per D.2 Attenuation Eligibility. See Section 3.3 Decision Types.
5. **Decision: DENY at Tier 1.** Reason: `SCOPE_VIOLATION`.

### DENY Response Returned to Agent

```json
{
  "decision": "DENY",
  "tier": 1,
  "reason_code": "SCOPE_VIOLATION",
  "reason_detail": null,
  "policy_version": "2.1.0"
}
```

Note what the response does **not** include: the specific rule checked, the threshold values, whether other rules exist, which capability class the action falls under. Per Guarantee 4, DENY responses must not reveal policy internals. The agent framework can handle the denial programmatically via `reason_code`, but cannot probe policy structure through repeated failures.

### Events Emitted

```
Event: ActionRequested
  event_id: "evt-200"
  agent_identity: { instance_id: "agent-research-077", ... }
  action_type: "admin.users.delete"
  causal_parent: null

Event: ActionEvaluated
  event_id: "evt-201"
  decision: "DENY"
  tier: 1
  reason_code: "SCOPE_VIOLATION"
  reason_detail: "Action outside authorized scope for agent type research-agent"
  policy_version: "2.1.0"
  causal_parent: "evt-200"

Event: ActionDenied
  event_id: "evt-202"
  reason_code: "SCOPE_VIOLATION"
  causal_parent: "evt-201"
```

Note that `reason_detail` in the audit entry may carry more information than the agent sees. The Audit Ledger is not subject to Agent Isolation, so the detail is available to auditors though not to agents. The agent receives only `reason_code`.

---

## F.6 Authority Expiration Mid-Task

An agent's grant TTL elapses while the agent is still active. One action is already executing when the grant expires; the next action is denied. Demonstrates Guarantee 9 (Authority Expires) and the expiration semantics defined in Section 3.2.

### Setup

```json
{
  "grant": {
    "grant_id": "grant-research-002",
    "ttl": "4h",
    "granted_at": "2026-04-21T10:00:00Z",
    "expires_at": "2026-04-21T14:00:00Z"
  },
  "agent": {
    "instance_id": "agent-research-302",
    "authorized_actions": ["database.query", "report.generate"]
  }
}
```

### Timeline

| Time | Event |
|---|---|
| 13:59:30 | Agent submits Action #1: `database.query` |
| 13:59:31 | Policy Gate evaluates → ALLOW. Execution begins in Execution Boundary. |
| 14:00:00 | Grant expires. |
| 14:00:02 | Action #1 completes in Execution Boundary. |
| 14:00:05 | Agent submits Action #2: `report.generate`. |
| 14:00:05 | Policy Gate evaluates → DENY with `AUTHORITY_EXPIRED`. |

### Action #1: In-Flight at Expiration

Per Section 3.2, in-flight actions that have already passed the Policy Gate complete normally. Their results are annotated.

```
Event: ActionRequested
  event_id: "evt-300"
  timestamp: 2026-04-21T13:59:30Z

Event: ActionEvaluated
  event_id: "evt-301"
  decision: "ALLOW"
  tier: 1
  timestamp: 2026-04-21T13:59:31Z
  causal_parent: "evt-300"

Event: ActionExecuted
  event_id: "evt-302"
  timestamp: 2026-04-21T14:00:02Z
  outcome: { status: "SUCCESS", duration_ms: 31000 }
  annotations: ["authority_expired_during_execution"]
  causal_parent: "evt-301"
```

The annotation is recorded in the audit entry but does not invalidate the result. The action was authorized at the moment of Policy Gate evaluation.

### Grant Expiration: System-Driven Event

At 14:00:00 the grant's TTL elapses. The expiration is recorded as a system-driven audit entry with null `causal_parent` and a `reason_code` identifying the trigger (Section 3.5 causal completeness requirement).

```
Event: AuthorityGrantTerminated
  event_id: "evt-303"
  grant_id: "grant-research-002"
  timestamp: 2026-04-21T14:00:00Z
  reason: "EXPIRED"
  reason_detail: "TTL elapsed at 2026-04-21T14:00:00Z"
  terminated_by: null
  cascade_count: 0
  causal_parent: null
```

### Action #2: After Expiration

Per Section 3.2, new actions after expiration receive `AUTHORITY_EXPIRED`, distinct from `SCOPE_VIOLATION`. This allows the agent framework to handle renewal or graceful shutdown rather than retrying with different parameters.

```
Event: ActionRequested
  event_id: "evt-304"
  timestamp: 2026-04-21T14:00:05Z
  action_type: "report.generate"

Event: ActionEvaluated
  event_id: "evt-305"
  decision: "DENY"
  tier: 1
  reason_code: "AUTHORITY_EXPIRED"
  reason_detail: "Grant grant-research-002 expired at 2026-04-21T14:00:00Z"
  causal_parent: "evt-304"

Event: ActionDenied
  event_id: "evt-306"
  causal_parent: "evt-305"
```

### Cascaded Child Termination

If `agent-research-302` had spawned children, they would have been terminated with `TerminationReason.CASCADED` at 14:00:00 (Section 3.2 Parent Termination Cascade), each emitting an `AgentTerminated` event with `causal_parent` pointing to `evt-303`. Per the grace-period allowance, their in-flight actions would complete but no new actions would be permitted.

### What the Agent Framework Should Do

Because the denial reason is `AUTHORITY_EXPIRED` rather than `SCOPE_VIOLATION`, the framework has an unambiguous signal that renewal, rather than retry, is the correct response. It may:

- Request identity renewal if the agent's identity TTL is separate and still active.
- Request a new grant from a human.
- Terminate the agent gracefully and emit an `AgentTerminated` event with reason `GRANT_EXPIRED`.

---

## F.7 Tamper Detection via Integrity Verification

An external auditor invokes `verify_integrity` on the Audit Ledger. A modification to a historical entry is detected because the computed previous-entry hash no longer matches the stored hash. Demonstrates Guarantee 7 (Tamper Evidence).

This scenario does not involve an agent. It is a governance-of-governance operation, the infrastructure verifying its own integrity.

### Setup

```json
{
  "ledger_state": {
    "chain_length": 1847,
    "genesis_entry": "entry-0001",
    "chain_head": "entry-1847",
    "hash_algorithm": "SHA-384",
    "serialization": "RFC 8785 JCS",
    "external_anchors": [
      { "entry_id": "entry-0100", "anchored_at": "2026-04-15T00:00:00Z", "external_service": "anchor.example" },
      { "entry_id": "entry-1000", "anchored_at": "2026-04-19T00:00:00Z", "external_service": "anchor.example" }
    ]
  },
  "invocation": {
    "caller": "human:compliance-auditor@org",
    "operation": "verify_integrity",
    "range": "entry-0001..entry-1847"
  }
}
```

### Verification Walk

The Audit Ledger walks the chain, recomputing each entry's hash from the canonical JSON serialization and comparing to the stored hash. At `entry-0342`:

- Stored `entry_hash`: `e4a9...7f2b`
- Computed hash (from canonical serialization of the stored fields + declared `prev_hash`): `8c11...2ae3`
- **Mismatch.**

### Cross-Check Against External Anchors

The auditor cross-references with published anchor points:

- `entry-0100` (anchored 2026-04-15): chain recomputation matches the anchor. Chain is intact through 0100.
- `entry-1000` (anchored 2026-04-19): chain recomputation matches the anchor. Chain is intact through 1000.

Because `entry-0342` falls between two valid anchors, the timing of the modification is bounded: it occurred after the entry was originally written, and after the 2026-04-15 anchor was published. The break is therefore post-anchor, a tamper with an entry whose surrounding chain was already externally anchored, which is exactly what external anchoring is designed to expose.

### Structured Verification Result

```json
{
  "verify_integrity_result": {
    "range": "entry-0001..entry-1847",
    "status": "BROKEN",
    "first_break_at": "entry-0342",
    "break_detail": {
      "stored_entry_hash": "e4a9...7f2b",
      "computed_entry_hash": "8c11...2ae3",
      "prev_hash_matches": true,
      "serialization": "RFC 8785 JCS"
    },
    "anchor_comparison": [
      { "anchor": "entry-0100", "anchored_at": "2026-04-15T00:00:00Z", "status": "CONSISTENT" },
      { "anchor": "entry-1000", "anchored_at": "2026-04-19T00:00:00Z", "status": "CONSISTENT" }
    ],
    "implication": "Entry-0342 content was modified after the 2026-04-15 anchor was published. The modification is detectable because the stored entry_hash does not match the computed hash from the current serialized fields."
  }
}
```

### What This Does Not Detect

- **Wholesale chain replacement.** If an attacker replaces the entire chain, a self-contained walk would succeed. External anchoring (Section 3.5) defends against this, since the anchors would not match the replaced chain head.
- **Omission of never-anchored entries.** Entries added and removed between two anchor publications without propagating forward are only detectable by replaying from a trusted anchor point and comparing expected vs. actual entries.

### Audit Response

Integrity break is a governance-of-governance incident (Appendix E). It is not automatically remediated, and the spec does not define what happens after detection. The implementing organization's incident response governs: the broken entry is quarantined, a forensic copy is preserved, and the break is reported to the parties identified in the administrative controls.

---

## F.8 Fail-Closed: Policy Gate Unreachable

The Execution Boundary loses connectivity to the Policy Gate. Per Guarantee 8, actions are denied. Demonstrates the fail-closed default defined in Section 6.

### Setup

```json
{
  "agent": {
    "instance_id": "agent-research-501",
    "authorized_actions": ["database.read", "database.query"]
  },
  "action": {
    "action_type": "database.query",
    "params": { "table": "customers", "limit": 10 }
  },
  "infrastructure_state": {
    "policy_gate": "UNREACHABLE",
    "audit_ledger": "REACHABLE",
    "circuit_breaker_state": "OPEN"
  }
}
```

### Evaluation Attempt

The agent's GovernanceClient calls `request_action`. The Execution Boundary attempts to consult the Policy Gate.

1. Open connection to Policy Gate; **timeout after 500ms**.
2. Circuit breaker is already OPEN (from prior failure). No further attempts within the circuit-open window.
3. Per Section 7.2 and Guarantee 8: on infrastructure error, `request_action` MUST return DENY.
4. Execution Boundary returns DENY with `GovernanceError.GOVERNANCE_UNAVAILABLE`.

### Response to Agent

```json
{
  "decision": "DENY",
  "tier": null,
  "reason_code": "GOVERNANCE_UNAVAILABLE",
  "reason_detail": "Policy Gate unreachable; circuit open",
  "policy_version": null
}
```

Note `tier: null`: no tier resolved the decision because none was reached. `policy_version: null` for the same reason. The agent cannot distinguish this case from a policy-level denial beyond the `reason_code` and should handle it as a governance outage (back off, report, optionally terminate).

### Events Emitted

The Audit Ledger is reachable in this scenario, so the fail-closed event is recorded at the Execution Boundary and persisted normally.

```
Event: ActionRequested
  event_id: "evt-400"
  agent_identity: { instance_id: "agent-research-501", ... }
  action_type: "database.query"
  causal_parent: null

Event: ActionEvaluated
  event_id: "evt-401"
  decision: "DENY"
  tier: null
  reason_code: "GOVERNANCE_UNAVAILABLE"
  reason_detail: "Policy Gate unreachable; request_action failed-closed"
  policy_version: null
  causal_parent: "evt-400"

Event: ActionDenied
  event_id: "evt-402"
  reason_code: "GOVERNANCE_UNAVAILABLE"
  causal_parent: "evt-401"
```

### If the Audit Ledger Were Also Unreachable

Per Section 6, the Audit Ledger has a different failure profile. Actions are queued locally by the Execution Boundary up to the Appendix C.14 threshold. If the threshold is exceeded, new actions also fail-closed. The current scenario assumes the Audit Ledger is reachable, so the chain is preserved without buffering.

### Recovery

The circuit breaker periodically probes the Policy Gate. When it recovers:

1. Circuit closes.
2. An audit entry records the circuit state change (Section 6 Circuit Breaker requirement #5).
3. Normal `request_action` evaluation resumes.

There is no retroactive re-evaluation of denied actions. An action that was denied while the gate was down is not retried by the governance layer, and the agent or its framework must re-submit if appropriate.

### Risk-Class Overrides

Section 6 permits implementations to define risk-class overrides (e.g., read-only queries to non-sensitive data may fail-open during brief outages). If such overrides exist, they are declared in the authority grant and produce a different trace: the DENY is replaced with a conditional ALLOW annotated with `fail_open_override`. No such override is configured in this example.

---

## F.9 Output Evaluator Intervention: REVISE

An email-drafting agent produces a draft containing content outside its assigned scope. The Output Evaluator returns REVISE with structured findings. The agent framework prompts a revision; the second draft passes. Demonstrates the Output Governance extension (Section 3.6) and the REVISE decision path.

### Setup

```json
{
  "agent": {
    "instance_id": "agent-email-drafting-812",
    "authorized_output_types": ["CUSTOMER_FACING"],
    "task_context": {
      "task_id": "task-inquiry-442",
      "assigned_scope": ["acknowledge_receipt", "confirm_meeting", "clarify_next_steps"]
    }
  },
  "output_policy": {
    "out_of_scope_topics": ["pricing_projection", "forecast", "contract_terms", "legal_opinion"]
  }
}
```

### Agent's First Draft

```json
{
  "output_id": "out-001",
  "output_type": "CUSTOMER_FACING",
  "audience": "EXTERNAL_CUSTOMER",
  "content": "Dear Customer,\n\nThank you for your inquiry. I confirm our meeting for Thursday at 2pm.\n\nIn anticipation of our discussion, I wanted to share that based on current market trends, we expect pricing in this category to increase 12-18% over the next two quarters. Our Q3 forecast suggests strongest growth in the premium tier, with projected margin expansion of 240 basis points. Given these dynamics, locking in current rates would deliver an estimated 8-figure NPV benefit.\n\nLooking forward to Thursday.\n\nBest,\nSales Team"
}
```

### Output Evaluation #1

The Output Evaluator runs scope alignment (D.8.2 Slot Match).

| Required slot | Covered? |
|---|---|
| acknowledge_receipt | Yes ("Thank you for your inquiry") |
| confirm_meeting | Yes ("I confirm our meeting for Thursday at 2pm") |
| clarify_next_steps | Partially ("Looking forward to Thursday", weak) |

| Forbidden topic | Mentioned? |
|---|---|
| pricing_projection | **Yes** ("pricing... to increase 12-18%") |
| forecast | **Yes** ("Q3 forecast... margin expansion") |
| contract_terms | Borderline ("locking in current rates") |
| legal_opinion | No |

```json
{
  "decision": "REVISE",
  "scope_alignment": 0.42,
  "findings": [
    {
      "finding_id": "f-001",
      "severity": "HIGH",
      "type": "OUT_OF_SCOPE_TOPIC",
      "topic": "pricing_projection",
      "quote": "pricing in this category to increase 12-18% over the next two quarters",
      "recommendation": "Remove pricing projections. Not within assigned task scope."
    },
    {
      "finding_id": "f-002",
      "severity": "HIGH",
      "type": "OUT_OF_SCOPE_TOPIC",
      "topic": "forecast",
      "quote": "Our Q3 forecast suggests strongest growth in the premium tier, with projected margin expansion of 240 basis points",
      "recommendation": "Remove forecast content. Not within assigned task scope."
    },
    {
      "finding_id": "f-003",
      "severity": "MEDIUM",
      "type": "OUT_OF_SCOPE_TOPIC",
      "topic": "contract_terms",
      "quote": "locking in current rates would deliver an estimated 8-figure NPV benefit",
      "recommendation": "Remove contract-terms framing. Pricing and rate-locking are outside assigned scope."
    }
  ],
  "audience_risk": "HIGH"
}
```

The decision is REVISE rather than SUPPRESS: the compliant portions, the acknowledgment and the meeting confirmation, are preserved. The framework receives structured findings to prompt a revision rather than discarding the entire draft.

### Agent's Second Draft

The agent framework (not the governance layer) re-prompts the agent with the findings. The agent produces:

```json
{
  "output_id": "out-002",
  "output_type": "CUSTOMER_FACING",
  "audience": "EXTERNAL_CUSTOMER",
  "content": "Dear Customer,\n\nThank you for your inquiry. I confirm our meeting for Thursday at 2pm.\n\nAhead of Thursday, please let me know if you'd like me to include anyone else from your team, and feel free to share any specific topics you'd like us to cover.\n\nLooking forward to speaking.\n\nBest,\nSales Team"
}
```

### Output Evaluation #2

| Required slot | Covered? |
|---|---|
| acknowledge_receipt | Yes |
| confirm_meeting | Yes |
| clarify_next_steps | Yes ("share any specific topics") |

| Forbidden topic | Mentioned? |
|---|---|
| pricing_projection | No |
| forecast | No |
| contract_terms | No |
| legal_opinion | No |

```json
{
  "decision": "RELEASE",
  "scope_alignment": 0.94,
  "findings": [],
  "audience_risk": "LOW"
}
```

### Events Emitted

```
Event: OutputEvaluated
  event_id: "evt-500"
  agent_identity: { instance_id: "agent-email-drafting-812", ... }
  output_id: "out-001"
  decision: "REVISE"
  scope_alignment: 0.42
  findings: [ ... 3 findings ... ]
  audience_risk: "HIGH"
  causal_parent: "evt-499"  (task initiation)

Event: OutputEvaluated
  event_id: "evt-501"
  output_id: "out-002"
  decision: "RELEASE"
  scope_alignment: 0.94
  findings: []
  audience_risk: "LOW"
  causal_parent: "evt-500"

Event: ActionExecuted
  event_id: "evt-502"
  action_type: "gmail.messages.send"
  outcome: { status: "SUCCESS" }
  causal_parent: "evt-501"
```

Both evaluations, the rejected first draft and the released second draft, are in the audit chain. An auditor can reconstruct: the agent initially produced out-of-scope content, received structured feedback, revised successfully, and only then executed the send.

### What the Governance Layer Does Not Do

The Output Evaluator does not rewrite the draft. It does not select language, and it does not collaborate with the agent on what the email should say. It releases, suppresses, escalates, or returns findings. Per the design principle in Section 3.6, the governance layer constrains agents without collaborating with them: it says "this is wrong and here is why," and it does not say "let me fix it for you." The revision loop is the agent framework's responsibility, not the governance layer's.
