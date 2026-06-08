# Agent Governance Specification

**Version:** 0.6.0-draft
**Status:** Draft Interoperability Specification
**Author:** aboynamedstacey
**Date:** 2026-06-08
**License:** Apache 2.0

---

## Abstract

This document is a draft interoperability specification for the governance of autonomous AI agents in enterprise environments. It sets out the contracts, event schemas, and system guarantees through which governance components built by separate teams can work as one.

Agent frameworks have matured quickly, and companies are already running them against production data and live systems. The machinery for governing those agents has lagged well behind. A firm that deploys them today cannot easily give an auditor a clean account of who authorized each action, what the bounds of that authority were, and how authority passed from one agent to the next as work was delegated. The market has so far answered in fragments, one class of product policing what an agent says and another constraining what it does, with little that addresses the wider problem of accountable delegation that regulated deployment requires.

The specification rests on a single premise, that an AI agent is **an untrusted process acting under delegated human authority**. That idea shapes every decision that follows. An agent may be capable, well-behaved, and built from code the operator wrote, and it remains, for the purposes of governance, an untrusted process to be bounded accordingly.

### Design Principles

1. **Containment.** The governance layer is built to constrain agents rather than to collaborate with them. It does not negotiate, it does not rely on an agent's account of its own conduct, and it does not defer to an agent's judgment about what it should be permitted to do.

2. **A single governance surface.** What an agent does, through tool calls, API invocations, and the spawning of further agents, and what an agent says, through its text, recommendations, and instructions to other agents, are governed under one policy framework rather than two disconnected ones.

3. **Authority of human origin.** Every action an agent takes traces back to a human decision along an unbroken chain of delegation, and where that chain is broken, the action carries no authority.

4. **Implementation left to the implementer.** The specification fixes the contracts and the guarantees and leaves the engineering to those who build it. Separate teams can supply their own policy engines, audit backends, and framework adapters, and these interoperate through the shared event schemas.

5. **Effort proportional to risk.** A low-risk action resolves in microseconds through deterministic rule evaluation, a higher-risk action draws richer scrutiny, and human review is held in reserve for the cases that automated evaluation cannot settle on its own.

---

### Execution Model

The specification defines a broad governance architecture, but the ordinary request path is intentionally narrow. For routine actions, conforming implementations need only perform local identity validation, Tier 1-2 policy evaluation against cached policy and request parameters, Execution Boundary proxying, and audit append or bounded queueing. Trust adjustment, compliance projection, policy authoring, candidate-rule promotion, and most observability functions are asynchronous or administrative. Tier 3 analysis, escalation, and synchronous output evaluation are exception paths invoked only when policy or risk class requires them.

The architecture operates in three execution lanes:

**Lane 1: Fast Path** *(runs on every ordinary action)*

```
Agent
  → Local identity validation (signature check, expiry check — no network call)
  → Cached Tier 1-2 policy evaluation (rule match + constraint check — in-memory)
  → Execution Boundary proxy (credential resolution + tool call)
  → Audit append or bounded local queue (non-blocking write)
  → Return result to agent
```

This is the entire synchronous cost of a routine action. There are no trust lookups, no historical scans, no human routing, no compliance mapping, and no full-context retrieval on this path.

Components with fast-path touchpoints:
- **Policy Gate (Tiers 1-2):** Cached rule evaluation. No external state required.
- **Execution Boundary:** Proxies the action. Holds credentials. Returns result.
- **Audit Ledger:** Append or queue. If the ledger is temporarily unreachable, entries queue locally up to a bounded threshold. The write is non-blocking on the action path.
- **Identity Service:** Not consulted per-action. Identity is validated locally against the signed token. The Identity Service is consulted only at registration and spawn time.

**Lane 2: Exception Path** *(runs only when Tier 1-2 cannot safely resolve)*

```
  → Tier 3 pattern/context evaluation (queries Trust Engine, recent audit history)
  → Escalation routing (pauses action, routes to human reviewer)
  → Synchronous output evaluation (for high-risk output channels only)
```

These paths are triggered by policy configuration or risk classification, not by every action. A well-tuned policy resolves 90%+ of actions at Tier 1-2 without entering the exception path.

Components with exception-path touchpoints:
- **Policy Gate (Tier 3):** Behavioral envelope, aggregate thresholds, velocity analysis. Requires Trust Engine and audit history. *(Extension: Trust-Adjusted Evaluation)*
- **Escalation Router:** Pauses the action. Routes to human. Waits for resolution or timeout. *(Extension: Adaptive Escalation)*
- **Output Evaluator:** Scope alignment check. Synchronous only for high-risk channels (customer-facing, agent-to-agent). *(Extension: Output Governance)*

**Lane 3: Control Plane** *(runs at setup time, asynchronously, or periodically)*

```
  → Grant creation, modification, revocation (human-initiated, administrative)
  → Policy validation and versioning (pre-activation checks)
  → Policy distribution to Policy Gate instances (push on change)
  → Trust adjustment (reads audit history, updates trust tiers — periodic batch)
  → Candidate-rule generation and promotion (from escalation resolutions)
  → Compliance projection (maps event data to regulatory frameworks — on-demand)
  → Cold-storage context retrieval (for investigations — on-demand)
  → Metrics, alerting, observability (continuous background)
  → Identity renewal (on request, before expiry)
  → Kill switch activation (emergency, human-initiated)
```

None of these functions sit inline on the ordinary action path. They deepen governance without adding request-path weight.

**What Core conformance means in runtime terms:** A conforming Core implementation's fast path is Lane 1 only. The Lane 2 components are Extension Profiles, so a Core implementation that receives an ESCALATE decision from Tier 1-2 pauses the action and records the escalation, while the human review workflow itself is Extension-defined. Lane 3 runs entirely off-path. A Core implementation can be fast because most of the architecture lives in Lanes 2 and 3.

---

## 1. Threat Model

### 1.1 Primary Threats

The specification defends against five threat categories, all originating from or enabled by the agents themselves.

**Threat 1: Scope Drift**

This is the dominant threat. An agent asked to summarize customer feedback calls a write API because the model reasoned that doing so would be helpful. Scope drift is rarely a matter of malice. It is the ordinary consequence of stochastic systems operating inside deterministic enterprise environments, and at machine speed, across many systems at once, it compounds into scope explosion.

Most organizations underestimate scope drift because it does not present as a security incident. It presents as an agent being helpful, which is precisely what makes it difficult to detect.

**Threat 2: Authority Laundering**

When Agent A spawns Agent B, the question is what Agent B is then able to do, and in most current frameworks the answer is "whatever Agent A can do, or more." That makes privilege escalation a routine part of operation: a research agent spawns a "helper" with access to the same tools, and an unaudited subprocess now holds production API keys.

Authority laundering extends to breadth as well as depth. An agent that spawns a hundred sub-agents, each delegating further, can create a tree of more than a thousand relationships in seconds. That delegation topology differs fundamentally from a human organization, and it calls for explicit architectural controls.

**Threat 3: Prompt Injection and Manipulation**

Agents consume external data, including emails, documents, web content, and API responses, any of which can carry instructions that a model will follow. The attack vector is well established, and it becomes an architectural concern once agents act on what they read, because a manipulated agent does not merely produce bad text; it calls real APIs with real consequences.

Prompt injection has no close equivalent in traditional security models, since it is a threat in which the data being processed can rewrite the principal's intent.

*See Section 1.3 (Scope of Governance-Layer Defense Against Prompt Injection) for how this specification engages this threat.*

**Threat 4: Audit Opacity**

Under the EU AI Act, SOC2, and similar frameworks, "an AI did it" is not an explanation. Regulators and courts require reconstruction of the chain of reasoning, the data consumed, the decisions made, and the authority under which each action was taken.

Standard application logs record what happened. Governance requires a record of **why** each action was permitted: which policy was in effect, how the action was evaluated, who authorized the delegation chain, and what the trust state was at the moment of the decision. This specification provides a record substrate that supports the production of such evidence for regulatory inquiries, though the evidentiary adequacy of any given implementation will depend on its fidelity to the specification and on the regulatory context.

**Threat 5: Governance System Failure**

The governance layer is itself a high-value target and a potential point of failure. If the control plane goes down and agents default to "allow," governance disappears; if they default to "deny," operations halt. The governance system's own security, availability, and failure modes must therefore be designed explicitly rather than left to chance.

### 1.2 Threat Model Boundaries

This specification does not place the "adversarial superintelligent AI" at the center of its threat model. That scenario is not dismissed as impossible; it is simply the wrong design frame for enterprise governance. The great majority of agent failures in enterprise environments are mundane, a matter of scope drift, misconfiguration, inherited permissions, and bad inputs. An architecture that handles those well constrains adversarial behavior as a side effect, whereas an architecture built primarily around adversarial AI tends to be over-engineered for the common case and still inadequate for the exotic one.

The specification also does not replace network security, infrastructure security, or application security. It layers on top of existing security architectures, addressing the governance gap specific to autonomous AI agents.

### 1.3 Scope of Governance-Layer Defense Against Prompt Injection

Prompt injection is a threat to the model layer, where a model can be deceived by adversarial content into producing outputs that diverge from the principal's intent. This specification does not defend against that deception. Model-level defenses, such as instruction hierarchy, content classifiers, constitutional methods, and input sanitization, are the responsibility of the model provider and the runtime environment.

The governance layer defends against injection's operational consequences. A successfully deceived agent operates under its existing authority, and the spec's invariants bound what that authority permits. The table below maps injection consequences to the mechanisms that contain them.

| Consequence of successful injection | Containment mechanism | Guarantee |
|---|---|---|
| Agent attempts to exfiltrate credentials | Execution Boundary holds all credentials; agent context never includes secrets. | G5: Credential Isolation |
| Agent attempts action outside granted scope | Policy Gate denies; authority cannot expand through deception. | G3: Authority Only Attenuates |
| Agent attempts to grant a child agent broader authority | Delegation invariant rejects any grant exceeding parent authority. | G3: Authority Only Attenuates |
| Agent attempts high-frequency or high-damage actions | Rate limits and damage budgets throttle and bound. | G1: No Bypass (via Policy Gate) |
| Agent succeeds in a bounded harmful action | Audit chain records cause, decision, outcome, and policy version. | G6: Decision Traceability; G7: Tamper Evidence |
| Agent targets the governance layer itself | Agent isolation prevents access to Policy Gate, Authority Registry, or Audit Ledger. | G4: Agent Isolation |
| All governance mechanisms fail | System fails closed; agents stop. | G8: Fail-Closed |

An implementation conforming to the Core Profile contains the consequences of injection at the governance layer, even though the underlying deception occurs at the model layer. Preventing the deception lies outside the scope of this specification; containing its consequences, attributing them, and recovering within bounded damage lies within it.

---

## 2. Architecture Overview

### 2.1 Components

The architecture consists of eight components. Each has a single responsibility, communicates through defined event schemas, and can be implemented independently by different engineering teams.

```
┌──────────────────────────────────────────────────────────────────┐
│                      HUMAN OPERATORS                             │
│            (Define authority grants, review escalations)         │
└─────────────────────────────┬────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────────┐
              │               │                   │
              ▼               ▼                   ▼
┌──────────────────┐ ┌────────────────┐  ┌─────────────────┐
│   1. AUTHORITY   │ │  8. ESCALATION │  │   7. TRUST      │
│      REGISTRY    │ │     ROUTER     │  │      ENGINE     │
│                  │ │                │  │                 │
│  What agents MAY │ │ Human review   │  │ Dynamic,        │
│  do. Source of   │ │ with forced    │  │ capability-     │
│  truth for       │ │ engagement.    │  │ scoped trust    │
│  authority.      │ │ Feedback loop. │  │ measurement.    │
└────────┬─────────┘ └────────────────┘  └─────────────────┘
         │
         ▼
┌──────────────────┐
│ 2. AGENT IDENTITY│
│    SERVICE       │
│                  │
│ Mints signed     │
│ identities with  │
│ lineage and      │
│ scoped authority.│
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                      3. POLICY GATE                              │
│                                                                  │
│  Intercepts every agent action. Four decisions:                  │
│  ALLOW | DENY | ESCALATE | ATTENUATE                             │
│                                                                  │
│  Tiered evaluation with early exit:                              │
│  Tier 1 (deterministic rules) → Tier 2 (parameter inspection)   │
│  → Tier 3 (pattern analysis) → Escalation                       │
└──────────┬────────────────────────────────────┬──────────────────┘
           │                                    │
     Actions                              Agent outputs
           │                                    │
           ▼                                    ▼
┌──────────────────┐                 ┌──────────────────┐
│ 4. EXECUTION     │                 │ 6. OUTPUT        │
│    BOUNDARY      │                 │    EVALUATOR     │
│                  │                 │                  │
│ Proxies tool     │                 │ Scope alignment  │
│ calls. Holds all │                 │ checking. Sync   │
│ credentials.     │                 │ for high-risk,   │
│ Agents never     │                 │ async for        │
│ touch creds.     │                 │ internal.        │
└────────┬─────────┘                 └────────┬─────────┘
         │                                    │
         └──────────────┬─────────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ 5. AUDIT LEDGER  │
              │                  │
              │ Append-only.     │
              │ Tamper-evident.  │
              │ Causally chained.│
              │ Agent-           │
              │ inaccessible.    │
              └──────────────────┘
```

### 2.2 Data Flow

```
Agent intends action
  → Policy Gate receives (agent identity + action + parameters + context)
  → Tier 1: Authority scope check, rate limit check, delegation chain validation
    → Resolved? → ALLOW/DENY → done
  → Tier 2: Parameter inspection against constraints
    → Resolved? → ALLOW/DENY/ATTENUATE → done
  → Tier 3: Behavioral pattern analysis against trust history
    → Resolved? → ALLOW/DENY/ATTENUATE → done
  → Unresolved → ESCALATE → Escalation Router → Human review
  
If ALLOW:
  → Execution Boundary proxies the action (agent never touches credentials)
  → Result returned to agent
  → Audit Ledger records: action, identity, policy version, decision, tier, outcome
  
If ATTENUATE:
  → Execution Boundary proxies a modified action (read-only, redacted, scoped)
  → Attenuated result returned to agent
  → Audit Ledger records: original request, attenuation applied, outcome

If DENY:
  → Agent receives denial with reason
  → Audit Ledger records: action, identity, policy version, denial reason

If ESCALATE:
  → Escalation Router presents to human with full context and reason each tier could not resolve
  → Human provides decision + justification (required, not optional)
  → Resolution generates candidate rule for automated tiers (governed promotion)
  → Audit Ledger records: escalation, human decision, justification, rule candidate

Agent produces output:
  → Output Evaluator assesses scope alignment
  → High-risk channels (customer-facing, agent-to-agent): synchronous evaluation
  → Internal/draft channels: asynchronous evaluation
  → Audit Ledger records: output, evaluation, scope alignment score
```

---

### 2.3 Reconciling External Inputs

Several of the components defined below are contracts rather than fixed implementations, and an operator may satisfy them by consuming work emerging elsewhere in the ecosystem rather than building everything from scratch. The Agent Identity Service (Section 3.2) is the clearest case, since its requirements can be met by an external identity standard such as AIP, the Agent Identity Protocol, or the MIT "Authenticated Delegation" model. Where an operator adopts an external input of this kind, the rules below preserve the specification's guarantees across the seam.

**Human origin, scoped to where it is practical.** Within the operator's own organization, every chain of authority must terminate at a named human. That is Guarantee 2, and consuming an external input does not relax it. When the operator consumes an external identity for an agent that belongs to another organization, naming a specific individual at that counterparty is often not possible. There, the chain must terminate at an accountable organization, and at a named human within it wherever the external standard supplies one. The requirement holds in full where the operator has control, and falls back to institutional accountability at the boundary where individual attribution is not available.

**Audit remains the operator's own record.** An external input may carry its own provenance inside its token, as AIP does through its completion blocks. That record is a useful input, but it is not the system of record. The governance layer must write an independent entry to the Audit Ledger (Section 3.5) for every decision it makes. In-token provenance may be referenced, but it does not by itself satisfy Guarantee 6 (Decision Traceability) or Guarantee 7 (Tamper Evidence).

**External risk signals inform the decision without replacing it.** Some external inputs supply stateful or temporal risk signals, in the manner of an admission-control protocol such as ACP. These may be fed into Tier 3 of the Policy Gate as further evidence. They must not displace the Gate's four-outcome decision (ALLOW, DENY, ESCALATE, ATTENUATE) with a binary admit-or-deny verdict, since attenuation and escalation are central to how this specification governs.

---

## 3. Component Contracts

Each contract defines the interface that any conforming implementation must satisfy. The specification defines WHAT each component does and what guarantees it must provide. It does not prescribe HOW, leaving engineering teams to choose their own implementation technology, storage backends, and deployment models.

### 3.1 Authority Registry

**Responsibility:** Single source of truth for what each agent type is authorized to do. Defines the boundary between what an agent CAN do (capability) and what it MAY do (authority).

#### Data Model

```
AuthorityGrant {
    grant_id:           string          // Unique identifier
    agent_type:         string          // What kind of agent this applies to
    scope:              PolicyScope     // Authorized actions, resources, and constraints
    delegation_rules:   DelegationRule  // Can this agent spawn children? With what authority subset?
    escalation_policy:  EscalationRule  // Which action classes require human review
    rate_limits:        RateLimit[]     // Per-action-type rate constraints
    damage_budget:      DamageBudget    // Aggregate impact limits (e.g., max dollar value per window)
    ttl:                duration        // Authority expiration. REQUIRED. No permanent grants.
    granted_by:         string          // Human identity who authorized this grant
    granted_at:         timestamp
    policy_version:     string          // Version of the policy document
    terminated:         boolean
    terminated_at:      timestamp | null
    terminated_by:      string | null          // Human identity for REVOKED; null for system-driven (EXPIRED, CASCADED)
    termination_reason: GrantTerminationReason | null
}
```

#### Required Operations

| Operation | Description |
|---|---|
| `create_grant` | Issue a new authority grant for an agent type. Requires human identity. |
| `get_grant` | Retrieve the current grant for an agent type. |
| `revoke_grant` | Immediately revoke an authority grant. Push revocation to all Policy Gate instances. |
| `list_grants` | List all active grants, optionally filtered by agent type or granting human. |
| `get_policy_version` | Retrieve a specific historical version of a grant. |
| `rollback_policy` | Restore a previous policy version. Creates a new version (not a destructive overwrite). |

#### Guarantees

- Every grant traces to a human identity. No system-generated grants.
- Every grant has a TTL. The implementation MUST reject grants without expiration.
- Grant revocation propagates to all Policy Gate instances within a defined SLA (implementation-specific, but MUST be documented).
- Policy history is retained. No version is deleted. Rollback creates a new version that restores the content of a prior version.
- **Termination completeness.** Every grant termination, whether `REVOKED`, `CASCADED`, or `EXPIRED`, MUST produce exactly one `AuthorityGrantTerminated` event and MUST be reflected in the grant struct (`terminated = true`, `terminated_at` set, `terminated_by` set for REVOKED or null for system-driven, `termination_reason` set to the appropriate value). TTL elapse is a termination, not a computed non-state. Whether implementations detect TTL elapse eagerly (scheduled sweep) or lazily (on-access check that fires the event and updates the struct before any denial) is implementation-defined. The invariant is that by the time any Policy Gate evaluation runs against an expired grant, the `AuthorityGrantTerminated` event has been emitted and the struct reflects termination.

#### Policy Validation

The Authority Registry MUST support policy validation before activation:

| Operation | Description |
|---|---|
| `validate_policy` | Check internal consistency of a policy before it becomes active. |

Minimum required consistency checks:
- Every action pattern in policy rules must be within the authority grant's scope.
- Rate limits must not permit action volumes that would exceed damage budgets within the same window.
- Escalation rules must reference action types that exist in the authority scope.
- Delegation rules must define a scope that is a subset of the agent's own scope.
- Constraint operators must reference valid fields for the action types they constrain.

Policy versions that fail validation MUST NOT be activated. Validation failures are recorded in the Audit Ledger.

#### Rule Evaluation Strategy

Policy rules are evaluated using **first-match-wins** ordering. When the Policy Gate evaluates an action against a policy's rules:

1. Rules are evaluated in their declared order.
2. The first rule whose pattern and conditions match the action determines the decision.
3. If no rule matches, the policy's default decision applies.
4. Conforming implementations MUST use first-match-wins. Alternative evaluation strategies (most-specific-match, deny-takes-precedence) are not conforming.

First-match-wins is mandated because it is deterministic and predictable: the same policy evaluated by different conforming implementations MUST produce the same decision for the same input. More complex evaluation strategies introduce ambiguity that creates safety risks.

#### Design Notes

Authority is attribute-based (ABAC, Attribute-Based Access Control) rather than role-based (RBAC). Agents do not have roles; they have types, tasks, lineage, and context. A policy that says "research-agents can read but not write" is only a starting point, because enterprise governance also needs to express "research-agents can read this specific data for this specific task during this time window." ABAC captures that directly, whereas RBAC cannot without an accumulating role explosion.

RBAC may still exist at the infrastructure level, since the Execution Boundary's credentials can be managed through it, but the agent-facing governance layer is ABAC.

---

### 3.2 Agent Identity Service

**Responsibility:** Establishes the identity of every agent instance, the lineage that links it to the human who authorized it, and the rule that a child's authority is always a subset of its parent's.

This component is defined as an **interface contract**. The specification states what an agent identity must assert and what the governance layer must verify, and it does not mandate a particular identity format. A conforming implementation may meet the contract with an identity service of its own or by consuming an external identity standard that satisfies the same requirements.

**Reference binding.** The natural candidates are the agent-identity efforts now gaining traction: AIP, the Agent Identity Protocol, which carries identity, attenuated authority, and provenance in a single signed token; and the MIT "Authenticated Delegation" work, which extends OAuth and verifiable credentials for the same purpose. Where an operator adopts one of these as its identity input, the reconciliation rules in Section 2.3 apply.

#### Data Model

```
AgentIdentity {
    instance_id:        string          // Unique per invocation, not per agent type
    agent_type:         string          // What kind of agent this is
    parent_id:          string | null   // Who spawned this instance (null for root agents)
    lineage_chain:      string[]        // Full ancestry: [root, ..., parent, self]
    authority_scope:    PolicyScope     // From grant, possibly attenuated by parent
    task_context:       TaskContext     // What task this agent was created to perform
    trust_tier:         TrustTier       // Current trust level, per capability class
    created_at:         timestamp
    expires_at:         timestamp       // From grant TTL or parent-imposed limit
    signature:          string          // Signed by Identity Service, NOT by parent agent
}
```

#### Required Operations

| Operation | Description |
|---|---|
| `create_root_identity` | Mint identity for an agent spawned directly by a human. Links to human and authority grant. |
| `create_child_identity` | Mint identity for an agent spawned by another agent. Validates delegation authority and attenuates scope. |
| `get_identity` | Retrieve an identity by instance ID. |
| `get_lineage` | Retrieve the full delegation chain for an identity, back to the human origin. |
| `get_trust` | Query current trust tier for an identity, scoped by capability class. |
| `expire_identity` | Mark an identity as expired. Expired identities cannot pass the Policy Gate. |
| `validate_identity` | Verify that an identity's signature is valid and it has not expired or been revoked. |

#### Guarantees

- Instance IDs are unique and non-reusable. A terminated agent's ID is never reassigned.
- Identities are signed by the Identity Service, not by parent agents. A compromised parent cannot mint children with arbitrary authority.
- Delegation attenuation is enforced at minting time. The Identity Service MUST reject any child identity request where the child's scope is not a subset of the parent's delegatable scope.
- Delegation depth is capped per authority grant. The Identity Service MUST reject spawn requests that exceed the delegation depth limit.
- Lineage chains are immutable once created. No entity can modify an identity's ancestry.
- An agent cannot modify its own identity record.

#### Delegation Attenuation

When Agent A requests a child identity for Agent B:

1. Identity Service retrieves Agent A's identity and authority grant.
2. Confirms Agent A's grant includes delegation rights.
3. Confirms the requested child scope is a subset of Agent A's delegatable scope.
4. Confirms the delegation depth limit has not been exceeded.
5. Mints the child identity with the attenuated scope and Agent A as parent.
6. Emits an `AgentSpawned` event.

If any check fails, the spawn request is denied and an `ActionDenied` event is emitted.

#### Ephemeral Agents

Short-lived agents spawned for a single task inherit a constrained subset of their parent's trust. They never build independent trust history. Their trust floor is determined by the parent's delegated trust tier for the relevant capability class. This prevents ephemeral agents from being used to bypass trust requirements, because a disposable agent cannot be spawned to do something the parent's trust tier would not itself permit.

#### Identity Renewal

Long-running agents may need to continue past their initial TTL. The Identity Service MUST support identity renewal:

| Operation | Description |
|---|---|
| `renew_identity` | Extend an active identity's expiration. Subject to: (a) the underlying authority grant must still be active and unexpired, (b) the renewal is recorded in the Audit Ledger, (c) trust state is re-evaluated at renewal time. |

Renewal does not create a new identity; the instance_id, lineage_chain, and authority_scope remain unchanged, and only `expires_at` is extended. The maximum extension is bounded by the authority grant's own TTL, since an identity cannot outlive its grant.

#### Authority Expiration During Active Tasks

When an agent's authority grant expires (TTL elapses) while the agent is active:

1. **In-flight actions** (already past the Policy Gate, currently executing in the Execution Boundary) complete normally. Their results are recorded in the Audit Ledger with an annotation that the authority expired during execution.
2. **New actions** are denied. The Policy Gate MUST return `ReasonCode.AUTHORITY_EXPIRED`, which is distinct from `SCOPE_VIOLATION` or other denial reasons. This allows agent frameworks to handle renewal or graceful shutdown.
3. **Child agents** whose parent's authority has expired are terminated with `TerminationReason.CASCADED`. See Parent Termination Cascade below.
4. **Pending escalations** for the expired agent are resolved as DENY with reason "authority expired during escalation."

#### Parent Termination Cascade

When a parent agent is terminated (for any reason: completed, expired, revoked, error, or killed):

1. All child agents in the parent's delegation tree are terminated with `TerminationReason.CASCADED`.
2. Cascade is recursive, so children of children are also terminated.
3. In-flight actions of cascaded children complete but no new actions are permitted.
4. The Identity Service emits `AgentTerminated` events for each cascaded child.
5. The causal_parent for each cascaded termination links to the parent's termination event.

**Rationale:** Authority derives from the parent chain, so if a link breaks, everything downstream is unauthorized. This is consistent with Guarantee 2 (No Authority Without Human Origin): if the chain from human to agent is broken, the agent has no authority.

Implementations MAY define a brief grace period (implementation-defined, MUST be documented) for in-flight actions of cascaded children. The grace period allows currently-executing actions to complete but does not permit new actions.

---

### 3.3 Policy Gate

**Responsibility:** The enforcement point. Every agent action, whether a tool call, an API invocation, an agent spawn, or an output to an external channel, passes through the Policy Gate, which resolves it into one of four decisions: Allow, Deny, Escalate, or Attenuate.

The identity and delegation assertions the Gate relies on at Tier 1 are an interface input, and may be supplied by an external identity standard under the terms of Section 2.3. The four-outcome decision and the attenuation logic, by contrast, are defined by this specification and are not delegated to an external input.

#### Decision Types

| Decision | Meaning | When |
|---|---|---|
| **ALLOW** | Action proceeds as requested. | Action is within scope, all constraints satisfied. |
| **DENY** | Action is blocked. Agent is informed why. | Action is outside scope, or constraints violated. |
| **ESCALATE** | Action is paused. Routed to human review. | Action is within scope but in a sensitive category, or automated evaluation cannot resolve. |
| **ATTENUATE** | Action proceeds, but a failing parameter is clamped to satisfy the constraint. | Action is within scope but a non-strict numeric bound (LTE/GTE) is violated. v0.5 restricts ATTENUATE to numeric clamping per D.2 Attenuation Eligibility; richer patterns ("read-only instead of read-write," "redacted data instead of full data," "scoped query instead of broad query") are out of scope for this revision and may be defined in future versions. |

#### Evaluation Request

```
PolicyEvaluationRequest {
    agent_identity:     AgentIdentity       // Who is acting
    action_type:        string              // What they want to do
    action_params:      object              // The specifics
    resource:           ResourceDescriptor  // What system/data the action targets
    execution_context:  ExecutionContext     // What the agent has done so far in this task
}
```

#### Evaluation Response

```
PolicyEvaluationResponse {
    decision:           Decision            // ALLOW | DENY | ESCALATE | ATTENUATE
    tier:               integer             // Which evaluation tier resolved this
    reason_code:        ReasonCode          // Structured reason code (see Appendix C.1)
    reason_detail:      string | null       // Optional human-readable detail
    policy_version:     string              // Which version of the policy was applied
    constraints:        ParameterConstraint[] // Any conditions on the allowed/attenuated action
    attenuation:        Attenuation | null  // If attenuated, what modifications were applied
}
```

**DENY responses and Agent Isolation:** DENY responses include a `reason_code` and optional `reason_detail` to allow agent frameworks to handle denials programmatically (e.g., retry with different parameters, request identity renewal, shut down gracefully). However, DENY responses MUST NOT reveal policy internals such as specific rule names, threshold values, or policy structure. The `reason_code` enum provides sufficient information for programmatic handling without exposing the policy's internal logic to the agent.

#### Tiered Evaluation

Actions are evaluated through a tiered pipeline with early exit. Most actions resolve at Tier 1.

**Tier 1: Deterministic Rule Evaluation**

Static checks that require no external state. Evaluated against the local policy cache.

- Is the agent identity valid and unexpired?
- Is this action type within the agent's authority scope?
- Has the agent exceeded its rate limit for this action type?
- Is the delegation chain valid (no broken links, no depth exceeded)?

Resolution at Tier 1 is microsecond-scale. An in-memory rule evaluation against cached policy. No network calls.

Expected resolution rate: 90%+ of all actions.

**Tier 2: Parameter and Constraint Evaluation**

Inspects action parameters against policy constraints. Still deterministic, but requires reading the action's specifics.

- "Can modify records, but not more than 50 in a single operation." Count the records.
- "Can send communications, but only to domains on the approved list." Check the domain.
- "Can execute transactions under $10,000." Check the amount.
- "Can access data, but only at classification level X or below." Check the data classification.

If constraints cannot be fully satisfied, evaluate whether attenuation is possible. If the agent requests read-write access and only read is authorized, attenuate to read-only rather than denying outright.

Resolution at Tier 2 is sub-millisecond to low millisecond.

**Tier 3: Pattern and Context Evaluation**

Evaluates the action against behavioral history and aggregate context. Requires querying the Trust Engine and potentially the Audit Ledger.

- Is this action within the agent's behavioral envelope for this capability class?
- Has this delegation chain been used successfully for similar actions?
- Does this action, combined with the agent's recent actions, exceed an aggregate threshold? (e.g., 500 individual transactions that are each under the $10,000 limit but collectively total $4.5 million)
- Is the velocity of actions unusual for this agent type and task context?

Tier 3 defends against patterns that are individually compliant but collectively harmful: reputation farming, salami attacks, and slow-motion scope drift.

Resolution at Tier 3 is low milliseconds.

**Escalation (when all tiers fail to resolve)**

If no tier can make a definitive Allow, Deny, or Attenuate decision, the action is escalated to the Escalation Router. The escalation includes the reason each tier could not resolve, which is essential context for meaningful human review.

#### Permission Introspection

The Policy Gate MUST support a dry-run evaluation mode:

```
introspect(agent_identity, action_type, action_params) → PolicyEvaluationResponse
```

This allows agents (or their frameworks) to query "can I do X?" without actually doing it. Dry-run evaluations are cheaper than full evaluations (no audit entry in the primary ledger, no execution), reduce unnecessary denials, and reduce Policy Gate load by preventing agents from submitting actions they cannot perform.

**Introspection rate limiting and abuse detection:** Dry-run evaluations do not affect action rate limits or behavioral pattern analysis for the primary action path. However, dry-run evaluations MUST be:

- **Independently rate-limited.** Implementations MUST enforce a separate rate limit on introspection requests per agent instance. Excessive probing is itself a signal.
- **Logged to a separate introspection log.** This log is available to the Trust Engine.
- **Analyzed for anomalous patterns.** The Trust Engine SHOULD analyze introspection patterns for systematic boundary probing, for example a burst of introspect calls that systematically vary a single parameter to discover where a constraint threshold changes. Anomalous introspection patterns SHOULD reduce the agent's trust tier for the relevant capability class.

Introspection responses are subject to the same Agent Isolation constraints as DENY responses: they MUST NOT reveal policy internals beyond the `reason_code`.

#### Performance Requirements

The specification does not mandate specific latency numbers (these are implementation-dependent), but establishes the following design constraints:

- Tier 1 evaluation MUST NOT require network calls. Policy rules are cached locally.
- Tier 2 evaluation MUST NOT require calls to external systems beyond the policy cache and the action parameters themselves.
- Tier 3 evaluation MAY query the Trust Engine and recent audit history, but MUST have a timeout. If Tier 3 cannot resolve within the timeout, the action is escalated (not allowed by default).

---

### 3.4 Execution Boundary

**Responsibility:** The proxy through which all agent actions execute. Ensures agents never have direct access to tools, APIs, or credentials. Enforces attenuation decisions. Captures results for the Audit Ledger.

#### Data Flow

```
Agent → Policy Gate (decision) → Execution Boundary (proxies action) → Tool/API
                                         │
                                         ├── Result → Agent
                                         └── Entry → Audit Ledger
```

#### Required Operations

| Operation | Description |
|---|---|
| `execute` | Proxy an allowed action to the target tool/API. Apply attenuation if specified. Return result to agent. |
| `execute_attenuated` | Proxy a modified version of the action (read-only, redacted, scoped). |
| `resolve_resource` | Translate a resource name (e.g., "customer-database-prod") to actual connection credentials. Agents never see credentials. |

#### Guarantees

- **Credential isolation.** Agents reference resources by name. The Execution Boundary resolves names to credentials at execution time. Agent context never contains API keys, connection strings, passwords, or tokens. A compromised agent (through prompt injection or any other vector) cannot leak credentials because it never had them.
- **Attenuation enforcement.** When the Policy Gate returns ATTENUATE, the Execution Boundary enforces the modification. If the policy says "read-only," the Execution Boundary ensures the connection is actually read-only, rather than relying on the agent's promise to only read.
- **Result capture.** Every execution result is captured and forwarded to the Audit Ledger, including errors and timeouts.
- **No direct agent access.** If an agent can reach a tool or API without passing through the Execution Boundary, the specification's guarantees are void. The Execution Boundary is a mandatory chokepoint, not an optional proxy.

#### Design Notes

The Execution Boundary is architecturally distinct from the Policy Gate: the Gate makes decisions, and the Boundary enforces them. This separation of decision from enforcement is a long-standing principle of security architecture. Combining the two would create a single component that is at once a high-throughput decision engine and a credential-holding proxy, two roles whose security requirements pull against each other.

---

### 3.5 Audit Ledger

**Responsibility:** Append-only, immutable, causally chained record of every action, decision, and output in the system. The Audit Ledger is more than a log; it is a causal chain that can reconstruct the complete history of any agent's operation, including why each action was permitted.

#### Audit Entry

```
AuditEntry {
    entry_id:           string          // Unique identifier
    timestamp:          timestamp       // When the event occurred
    event_type:         EventType       // See Event Schema (Section 4)
    agent_identity:     AgentIdentity   // Full identity snapshot at time of event
    action_requested:   ActionDescriptor | null  // What the agent wanted to do
    policy_version:     string          // Which policy version was in effect
    evaluation:         EvaluationRecord // Decision, tier, reason
    action_executed:    ActionDescriptor | null  // What actually happened (may differ if attenuated)
    outcome:            ActionOutcome   // Result, including errors
    delegation_chain:   string[]        // Full lineage at time of event
    trust_state:        TrustSnapshot   // Agent's trust tiers at time of event
    context_hash:       string          // Hash of agent's context at decision time
    causal_parent:      string | null   // Entry ID of the event that caused this one
}
```

#### Causal Chaining

Each entry links to the entry that caused it via `causal_parent`. Agent B's action links back to Agent A's spawn action, which links back to the human's task initiation. Walking the causal chain backward from any action reconstructs why that action happened: which human authorized the chain of delegation, through which agents, and under which policies.

This is distinct from chronological logging. Two actions may occur at the same time with no causal relationship. Two actions may be separated by hours but be causally linked. The causal chain captures the actual decision path, not the timeline.

#### Context Snapshots

Storing the full agent context (which may include the LLM's entire conversation history) for every action is impractical at scale. The ledger stores a cryptographic hash of the context. Full context is stored separately in cold storage, retrievable by hash. For routine audits, the hash verifies integrity. For investigations, the full context is retrieved.

#### Required Operations

| Operation | Description |
|---|---|
| `append` | Write a new entry. Append-only, with no update and no delete. |
| `get_entry` | Retrieve an entry by ID. |
| `get_causal_chain` | Walk the causal chain backward from an entry to its root. |
| `query` | Search entries by agent identity, time range, event type, decision, or policy version. |
| `verify_integrity` | Verify that the cryptographic chain is unbroken. |
| `get_context` | Retrieve the full context snapshot from cold storage by hash. |

#### Guarantees

- **Append-only.** Entries cannot be modified or deleted, even by system administrators.
- **Tamper-evident.** Each entry includes a cryptographic hash incorporating the previous entry's hash, using an algorithm from the approved set (see Appendix C.15). The hash algorithm is declared at chain initialization in the genesis entry and MUST NOT change within a chain. Gaps or modifications in the chain are detectable through integrity verification.
- **Agent-inaccessible.** No agent identity can read from or write to the Audit Ledger. The ledger is populated by the governance infrastructure (Policy Gate, Execution Boundary, Output Evaluator), never by agents.
- **Causal completeness.** Every action-driven event has an audit entry with a `causal_parent` linking to the event that caused it. System-driven events (authority expiration, trust adjustment, policy update) MAY have null `causal_parent` when there is no single triggering event. System-driven events with null `causal_parent` MUST include a `reason_code` explaining the trigger.
- **External anchoring.** Implementations SHOULD support publishing chain head hashes to an independent external timestamping service at configurable intervals (see Appendix C.15). External anchoring enables detection of wholesale chain replacement, an attack that a self-contained hash chain cannot detect.
- **Queryable.** The ledger supports structured queries by authorized external systems (compliance tools, investigation dashboards, regulatory reporting). Query access is governed by its own access control, independent of agent governance.

#### Tiered Storage

| Tier | Retention | Use Case |
|---|---|---|
| Hot | Implementation-defined (e.g., 24 hours) | Real-time monitoring, incident detection |
| Warm | Implementation-defined (e.g., 90 days) | Compliance queries, operational review |
| Cold | Implementation-defined (e.g., 7 years) | Regulatory retention, investigations, full context retrieval |

The specification does not mandate specific retention periods. These are determined by the implementing organization's regulatory and operational requirements.

---

### 3.6 Output Evaluator *(Extension: Output Governance)*

**Responsibility:** Assesses agent outputs, meaning the text, recommendations, data, and instructions that agents produce and that influence humans or other agents, as distinct from their tool calls.

Controlling what agents do through tool calls is necessary but not sufficient. An agent that calls no tools, yet generates a persuasive and incorrect recommendation to a human decision-maker, has done real damage without triggering action-based governance. An agent that produces instructions consumed by another agent is effectively programming that agent, without making a tool call at all.

#### Evaluation Model

The Output Evaluator performs **scope alignment checking**, not content filtering. Content filters (toxicity, PII, brand safety) are orthogonal and can be layered separately. The Output Evaluator asks: **is this output consistent with what this agent was authorized and assigned to do?**

An email-drafting agent producing a financial analysis is out of scope regardless of whether the content is "safe." A research agent producing action recommendations when it was authorized only to produce summaries is out of scope. Scope alignment catches drift at the output level, complementing action-level scope enforcement in the Policy Gate.

#### Evaluation Request

```
OutputEvaluationRequest {
    agent_identity:     AgentIdentity
    output:             AgentOutput         // Text, structured data, recommendation
    output_type:        OutputType          // RECOMMENDATION | FACTUAL_CLAIM |
                                            // INSTRUCTION_TO_AGENT | CUSTOMER_FACING |
                                            // INTERNAL_SUMMARY
    audience:           Audience            // HUMAN_OPERATOR | ANOTHER_AGENT |
                                            // EXTERNAL_CUSTOMER
    task_context:       TaskContext         // What the agent was assigned to do
}
```

#### Evaluation Response

```
OutputEvaluationResponse {
    decision:           RELEASE | SUPPRESS | ESCALATE | REVISE
    scope_alignment:    float               // 0.0 to 1.0
    findings:           Finding[]           // Specific scope violations or concerns
    audience_risk:      RiskLevel           // LOW | MEDIUM | HIGH | CRITICAL
}
```

**REVISE decision:** When an output is partially in-scope but contains specific violations, the Output Evaluator returns REVISE instead of SUPPRESS. REVISE returns the output to the agent framework with structured `findings` that identify what is out of scope. The agent framework uses these findings to prompt the agent to produce a corrected output. The revised output is re-evaluated. REVISE preserves the compliant portions of the output rather than discarding everything.

**Design note:** The Output Evaluator does not modify outputs directly. SUPPRESS blocks an output entirely, while REVISE provides structured feedback, and the agent framework, rather than the governance layer, handles the revision interaction. This maintains the principle that the governance layer constrains agents without collaborating with them: it says "this is wrong and here is why," and it does not say "let me fix it for you."

#### Synchronous vs. Asynchronous Evaluation

| Channel | Evaluation Mode | Rationale |
|---|---|---|
| Customer-facing content | Synchronous | Irreversible reputational/legal exposure |
| Instructions to other agents | Synchronous | Agent-to-agent influence is an action by proxy |
| Regulated domains (financial, medical, legal) | Synchronous | Regulatory exposure |
| Internal summaries | Asynchronous | Will be reviewed by humans before use |
| Intermediate reasoning | Asynchronous | Not externally visible |
| Drafts for human review | Asynchronous | Human gate exists downstream |

The policy for which outputs require synchronous vs. asynchronous evaluation is defined in the Authority Registry per agent type.

#### Guarantees

- Every output to a synchronous channel is evaluated before release. No bypass path.
- Suppressed outputs are recorded in the Audit Ledger with the reason for suppression.
- The Output Evaluator does not modify outputs. It releases, suppresses, escalates, or requests revision. When REVISE is returned, the findings are delivered to the agent framework to prompt a corrected output. The revised output is re-evaluated before release.

---

### 3.7 Trust Engine *(Extension: Trust-Adjusted Evaluation)*

**Responsibility:** Measures and manages dynamic, capability-scoped trust for agent types. Trust determines the **scrutiny level** applied to actions within an agent's existing authority, controlling how much evaluation is required rather than what is permitted.

**Critical distinction: Trust never creates authority.** An agent with HIGH trust in `data_read` cannot read data that its authority scope does not include. Trust only affects whether an allowed action resolves quickly at Tier 1 or requires deeper evaluation at Tier 2-3. Authority (defined by the Authority Registry) determines what an agent MAY do. Trust (measured by the Trust Engine) determines how much scrutiny is applied to actions within that authority. These are separate mechanisms and MUST NOT be conflated in implementation.

#### Trust Model

Trust is not a single score. It is scoped per capability class.

```
TrustProfile {
    agent_type:         string
    capability_trust:   Map<CapabilityClass, TrustTier>
    // Example:
    // {
    //   "data_read":        HIGH,
    //   "data_write":       MEDIUM,
    //   "external_comms":   LOW,
    //   "agent_spawn":      LOW
    // }
    history_basis:      TrustHistory    // What observations inform the current tiers
    last_adjusted:      timestamp
}
```

An agent type trusted for data reads is not automatically trusted for data writes. An agent type trusted for internal communications is not automatically trusted for customer-facing communications. Trust is earned per capability class based on observed behavior in that class.

To be explicit: a trust tier of HIGH for `data_read` means "this agent's data read actions can be resolved with minimal evaluation overhead." It does not mean "this agent can read more data." The scope of what the agent may read is defined entirely by its authority grant. Trust adjusts the cost of evaluation, not the boundary of permission.

#### Trust Tiers

The specification defines four trust tiers. Implementations may add intermediate tiers.

| Tier | Effect on Policy Gate | Typical Assignment |
|---|---|---|
| HIGH | Most actions in this capability class resolve at Tier 1-2. | Agent type with extensive successful history in this capability. |
| MEDIUM | Actions resolve at Tier 1-2 with tighter constraints. Some may require Tier 3. | Default for established agent types. |
| LOW | Most actions require Tier 2-3 evaluation. Sensitive actions escalate. | New agent types, or after trust reduction. |
| RESTRICTED | All actions in this capability class escalate to human review. | After significant incident, or for capability classes not yet authorized. |

#### Trust Adjustment

Trust is adjusted based on observed outcomes, not agent self-reporting. The Trust Engine reads from the Audit Ledger and evaluates:

- Successful actions within scope → gradual trust increase for that capability class.
- Denied actions (agent attempted something outside scope) → trust decrease for that capability class.
- Escalated actions resolved as "approve" → minor trust increase.
- Escalated actions resolved as "deny" → trust decrease.
- Incidents (actions that caused measurable harm) → significant trust decrease, potentially across capability classes.

Trust adjustment is always asynchronous. It never blocks the action path.

#### Delegation Trust Attenuation

When Agent A spawns Agent B, Agent B's trust tiers are the minimum of:
- Agent A's trust tiers for the delegated capabilities
- The floor trust tier for Agent B's agent type

Trust never increases through delegation. A parent with MEDIUM data_write trust cannot spawn a child with HIGH data_write trust, regardless of the child's agent type profile.

#### Reputation Farming Defense

Trust at low-stakes capability classes does not transfer to high-stakes capability classes. An agent that performs thousands of successful data reads does not earn elevated trust for data writes or external communications. Each capability class has an independent trust trajectory.

This prevents the marketplace fraud pattern: building a perfect track record on safe operations to exploit elevated trust for a high-impact action.

#### Guarantees

- Trust is capability-scoped. No global trust score.
- Trust adjustment is based on observed outcomes from the Audit Ledger, not agent self-assessment.
- Trust only attenuates through delegation.
- An agent cannot query or modify its own trust profile.
- Trust changes are recorded in the Audit Ledger as `TrustAdjusted` events.

---

### 3.8 Escalation Router *(Extension: Adaptive Escalation)*

**Responsibility:** Routes actions that automated evaluation cannot resolve to human decision-makers. It shapes the human interaction so that review is substantive rather than a rubber stamp, and it manages the feedback loop from human decisions to automated rule candidates.

#### Escalation Package

When an action is escalated, the human reviewer receives:

```
EscalationPackage {
    escalation_id:      string              // Unique identifier for this escalation
    action:             ActionDescriptor    // What was attempted
    agent_identity:     AgentIdentity       // Who attempted it, including full lineage
    reason_code:        ReasonCode          // Why escalated (structured, from Appendix C.1)
    reason_detail:      string | null       // Supplemental context
    tier_results:       TierResult[]        // What each automated tier determined
    context:            ExecutionContext     // Relevant state for the reviewer
    risk_assessment:    RiskLevel           // System's assessment of potential impact
    default_decision:   DENY                // Asymmetric default: high-risk actions default to deny
    timeout:            duration            // How long to wait for human response (from EscalationRule)
    on_timeout:         Decision            // Decision if human does not respond (from EscalationRule, default: DENY)
    created_at:         timestamp
}
```

#### Escalation Timeout

When the `timeout` elapses without a human resolution:

1. The `on_timeout` decision applies (default: DENY).
2. An `EscalationTimedOut` event is emitted and recorded in the Audit Ledger.
3. The agent framework receives the timeout decision as a normal PolicyEvaluationResponse.
4. Timed-out escalations are flagged for review, since they indicate either staffing gaps or timeout values that are too short.

#### Resolution

```
EscalationResolution {
    escalation_id:      string              // Links to the EscalationPackage
    decision:           EscalationDecision  // APPROVE | DENY | MODIFY
    justification:      string              // REQUIRED. Not optional. Bare approve/deny is rejected.
    modified_action:    ModifiedAction | null // REQUIRED if decision is MODIFY. See Appendix C.7.
    decider_identity:   string              // Who made the decision
    candidate_rule:     CandidateRule | null // Proposed automation for future similar cases
    timestamp:          timestamp
}
```

**MODIFY decision:** When a human reviewer selects MODIFY, they provide a `ModifiedAction` that specifies the approved version of the action. By default, the modified action is re-evaluated by the Policy Gate before execution (`requires_reevaluation: true`). This ensures the human's modification still conforms to policy, so that a reviewer cannot use MODIFY to bypass policy constraints.

#### Forced Engagement Design

The Escalation Router is designed to defeat automation bias, the documented tendency of human reviewers to approve whatever the system recommends.

- **Justification is mandatory.** The reviewer cannot approve or deny without providing a reason. "Looks fine" is not a justification. The implementation SHOULD validate that the justification references specific aspects of the action or context.
- **Asymmetric defaults.** For high-risk action classes, the default is DENY. The reviewer must actively override the denial and justify why the action should proceed.
- **Tier failure context.** The reviewer sees WHY each automated tier could not resolve. This frames the review around the specific ambiguity the system needs resolved, rather than as a request to approve.
- **Sampling and audit.** Not every escalation needs unique deep review. The implementation MAY support statistical sampling, flagging some escalations for deep review while others receive standard review. All deep-review decisions are themselves audited.

#### Feedback Loop

Every human escalation resolution generates a `candidate_rule`, a proposed policy rule that, if promoted, would allow automated resolution of similar future cases. This is how the system learns, as human judgment is encoded into policy over time.

Candidate rules do not auto-promote. They enter a governed pipeline:

1. Candidate rule is generated from the escalation resolution.
2. Candidate is reviewed for policy consistency (does it conflict with existing rules?).
3. Candidate is approved by an authorized human (not the same human who made the escalation decision).
4. Promoted rule is versioned and deployed through the normal policy update process.
5. Rule promotion is recorded in the Audit Ledger.

If escalation rates exceed a configured threshold (implementation-defined), this is a signal that policies are underspecified and need revision, rather than a sign that more humans should review more actions.

#### Guarantees

- Every escalation resolution includes a justification from an identified human.
- Candidate rules require separate human approval before policy promotion.
- Escalation volume is monitored. Sustained high escalation rates trigger policy review alerts.
- All escalation resolutions are recorded in the Audit Ledger.

---

## 4. Event Schema

Standard events that flow between components. Any conforming implementation that emits and consumes these events is interoperable with other conforming implementations.

### 4.1 Event Types

```
ActionRequested {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    action_params:      object
    resource:           ResourceDescriptor
    causal_parent:      string | null
}

ActionEvaluated {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    decision:           ALLOW | DENY | ESCALATE | ATTENUATE
    tier:               integer
    reason_code:        ReasonCode | null   // Structured reason (see Appendix C.1)
    reason_detail:      string | null       // Supplemental human-readable detail
    policy_version:     string
    attenuation:        Attenuation | null
    causal_parent:      string          // Links to ActionRequested
}

ActionExecuted {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    action_params:      object          // As executed (may be attenuated)
    outcome:            ActionOutcome
    causal_parent:      string          // Links to ActionEvaluated
}

ActionDenied {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    reason_code:        ReasonCode          // Structured reason (see Appendix C.1)
    reason_detail:      string | null       // Supplemental human-readable detail
    policy_version:     string
    causal_parent:      string          // Links to ActionRequested
}

ActionEscalated {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    reason_code:        ReasonCode          // Why escalated (see Appendix C.1)
    reason_detail:      string | null       // Supplemental context for the reviewer
    tier_results:       TierResult[]
    causal_parent:      string          // Links to ActionEvaluated
}

EscalationResolved {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    action_type:        string
    decision:           APPROVE | DENY | MODIFY
    justification:      string
    decider_identity:   string
    candidate_rule:     CandidateRule | null
    causal_parent:      string          // Links to ActionEscalated
}

AgentSpawned {
    event_id:           string
    timestamp:          timestamp
    parent_identity:    AgentIdentity
    child_identity:     AgentIdentity
    delegated_scope:    PolicyScope
    causal_parent:      string          // Links to parent's action
}

AgentTerminated {
    event_id:           string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    reason:             TerminationReason   // COMPLETED | EXPIRED | REVOKED | ERROR | CASCADED | KILLED
    reason_detail:      string | null       // Supplemental context
    causal_parent:      string | null
}

TrustAdjusted {
    event_id:           string
    schema_version:     string          // Event schema version
    timestamp:          timestamp
    agent_type:         string
    capability_class:   CapabilityClass
    previous_tier:      TrustTier
    new_tier:           TrustTier
    basis:              string          // What observations prompted the change
    causal_parent:      string | null   // Audit entry IDs of the observations that triggered this.
                                        // May be null for periodic rebalancing.
}

PolicyUpdated {
    event_id:           string
    schema_version:     string
    timestamp:          timestamp
    agent_type:         string
    previous_version:   string
    new_version:        string
    updated_by:         string          // Human identity
    change_summary:     string
    causal_parent:      string | null   // If triggered by a CandidateRule promotion, links to it.
}

OutputEvaluated {
    event_id:           string
    schema_version:     string
    timestamp:          timestamp
    agent_identity:     AgentIdentity
    output_type:        OutputType
    audience:           Audience
    decision:           RELEASE | SUPPRESS | ESCALATE | REVISE
    scope_alignment:    float
    findings:           Finding[]
    causal_parent:      string
}

AuthorityGrantCreated {
    event_id:           string
    schema_version:     string
    timestamp:          timestamp
    grant:              AuthorityGrant  // Full grant details
    created_by:         string          // Human identity
}

AuthorityGrantTerminated {
    event_id:           string
    schema_version:     string
    timestamp:          timestamp
    grant_id:           string
    agent_type:         string
    reason:             GrantTerminationReason  // EXPIRED | REVOKED | CASCADED
    reason_detail:      string | null           // Supplemental context
    terminated_by:      string | null           // Human identity. Null for system-driven (EXPIRED, CASCADED).
    cascade_count:      integer                 // Number of active identities affected
}

EscalationTimedOut {
    event_id:           string
    schema_version:     string
    timestamp:          timestamp
    escalation_id:      string          // Links to original ActionEscalated
    agent_identity:     AgentIdentity
    action_type:        string
    timeout_duration:   duration        // How long the escalation waited
    applied_decision:   Decision        // The on_timeout decision that was applied
    causal_parent:      string          // Links to ActionEscalated
}
```

**Note:** All event types include a `schema_version` field. Events in Sections 4.1 that do not show `schema_version` above inherit it, and all events MUST include this field. The field is shown explicitly only on newly added events to avoid restating the full schema for existing events.

### 4.2 Event Guarantees

- Every event has a unique `event_id`, a `timestamp`, and a `schema_version`.
- Every event that results from a prior event links to it via `causal_parent`. System-driven events (TrustAdjusted, PolicyUpdated) MAY have null `causal_parent` with documented reasons.
- Events are immutable once emitted. Corrections are emitted as new events referencing the corrected event.
- The event schema is versioned. Every event includes a `schema_version` field indicating which version of the schema it conforms to.
- **Backward compatibility:** Within a major schema version, new optional fields may be added to events. Existing fields MUST NOT be removed or have their types changed. Consumers MUST ignore unrecognized fields. This ensures that implementations running different minor versions of the schema can interoperate.
- Implementations that claim interoperability MUST document their supported schema version range.

---

## 5. System Guarantees

These are the non-negotiable properties that any conforming implementation must maintain. If any guarantee is violated, the implementation is non-conforming.

### Guarantee 1: No Bypass

Every agent action passes through the Policy Gate. There is no path from agent intent to execution that skips evaluation. If an agent can reach a tool or API without passing through the governance layer, the specification's guarantees are void.

### Guarantee 2: No Authority Without Human Origin

Every authority grant traces back to a human decision. The delegation chain may be long, but it always terminates at an identified human. The Audit Ledger can reconstruct this chain for any action.

### Guarantee 3: Authority Only Attenuates

When Agent A spawns Agent B, Agent B's authority scope is at most a subset of Agent A's delegatable scope. It is never a superset. The Identity Service enforces this at minting time. There are no exceptions.

### Guarantee 4: Agent Isolation

The governance layer's internal state is not exposed to agents beyond what the GovernanceClient interface returns. Specifically:

- Agents cannot read from the Audit Ledger.
- Agents cannot query their own trust scores.
- Agents cannot inspect escalation history or policy rules.
- Agents cannot modify their own identity records.
- DENY responses include a `reason_code` but MUST NOT reveal policy internals (threshold values, rule names, or policy structure).

Agent isolation exists on a spectrum that depends on the integration model. The **sidecar pattern** provides network-level isolation, in that the agent process has no network path to governance infrastructure endpoints. The **SDK pattern** provides logical isolation, in that the GovernanceClient API surface is the only interface available, though it runs in the same process as the agent. Implementations MUST document their isolation level. For high-risk agent deployments, the sidecar pattern, with its network isolation, is RECOMMENDED.

### Guarantee 5: Credential Isolation

Agents never hold credentials, API keys, connection strings, or authentication tokens. The Execution Boundary holds all credentials and resolves resource references to credentials at execution time. Agent context is credential-free.

### Guarantee 6: Decision Traceability

Every action, whether allowed, denied, escalated, or attenuated, has a complete audit entry recording who acted, what was attempted, which policy was in effect, which tier resolved the decision, why, and what the outcome was. The causal chain links the action to its originating human authorization.

### Guarantee 7: Tamper Evidence

The Audit Ledger is append-only and cryptographically chained using an approved hash algorithm (see Appendix C.15). The chain is anchored by a signed genesis entry. Entries cannot be modified or deleted. Gaps or alterations in the chain are detectable through integrity verification. Implementations SHOULD publish chain head hashes to an independent external service to protect against wholesale chain replacement.

### Guarantee 8: Fail-Closed by Default

If the Policy Gate cannot reach the Authority Registry, or if the Execution Boundary cannot reach the Policy Gate, the default is DENY. Agents stop. Unauthorized action is worse than no action.

Implementations MAY define risk-class-specific overrides for low-risk actions (e.g., read-only queries to non-sensitive data may fail-open during brief governance outages). These overrides MUST be documented in the authority grant and recorded in the Audit Ledger.

### Guarantee 9: Authority Expires

Every authority grant has a TTL. There are no permanent grants. Expired authority cannot pass the Policy Gate. This forces periodic human review and prevents stale authority from accumulating.

---

## 6. Failure Modes

| Component Failure | System Behavior | Rationale |
|---|---|---|
| Policy Gate unreachable | Agents cannot act (fail-closed) | Unauthorized action is worse than no action |
| Authority Registry unreachable | Policy Gate uses cached grants; no new grants can be issued | Existing agents continue; no new authority can be created |
| Identity Service unreachable | No new agents can be created; existing agents continue | Prevents unidentified agents; does not kill working agents |
| Audit Ledger unreachable | Actions queued locally; agents continue up to queue threshold (see Appendix C.14) | Audit is critical but not real-time-safety-critical |
| Audit queue threshold exceeded | New actions fail-closed; in-flight actions complete. See Appendix C.14 for threshold configuration. | Cannot accumulate unlimited unaudited activity |
| Execution Boundary unreachable | Agents cannot act (fail-closed) | Same rationale as Policy Gate |
| Output Evaluator unreachable | Synchronous outputs blocked; async outputs queued | Prevents unreviewed high-risk outputs |
| Trust Engine unreachable | Tier 3 evaluation skipped; actions resolve at Tier 1-2 or escalate | Trust is informational, not safety-critical per-action |
| Escalation Router unreachable | Escalated actions default to DENY with retry | Human review cannot be bypassed by system failure |

### Circuit Breaker

Implementations MUST include a circuit breaker for each component. When a component fails:

1. The circuit opens (component is marked unavailable).
2. The failure mode from the table above takes effect.
3. The circuit breaker periodically probes the component.
4. When the component recovers, the circuit closes and normal operation resumes.
5. All circuit state changes are recorded in the Audit Ledger.

### Kill Switch

Implementations MUST provide an emergency kill switch that immediately:
- Revokes all authority grants
- Terminates all active agent identities
- Fails all Policy Gate evaluations to DENY
- Preserves the Audit Ledger (the kill switch does not destroy evidence)

The kill switch is a human-initiated action. Resuming operations after a kill switch activation requires re-issuing authority grants through the normal grant creation process. Kill switch activations cannot be reversed by a single administrative action, since the full grant creation workflow, with human authorization, must be repeated for each agent type.

---

## 7. Integration Model

### 7.1 Sidecar Pattern

The primary integration model is the **governance sidecar**, a lightweight proxy process that sits between the agent runtime and external systems. The sidecar intercepts outbound calls at the network or system level, routes them through the governance layer, and returns results or denials to the agent.

The sidecar pattern is borrowed from service mesh architecture (Envoy, Istio). It solves the same problem: enforcing policy across heterogeneous runtimes without modifying each one.

```
┌─────────────────────────────────┐
│         Agent Runtime           │
│  (LangChain, CrewAI, AutoGen,  │
│   Claude SDK, custom, etc.)    │
└──────────────┬──────────────────┘
               │ outbound calls
               ▼
┌─────────────────────────────────┐
│       Governance Sidecar        │
│                                 │
│  - Intercepts tool calls        │
│  - Routes through Policy Gate   │
│  - Proxies via Exec Boundary    │
│  - Captures outputs for eval    │
│  - Manages agent identity       │
└──────────────┬──────────────────┘
               │ governed calls
               ▼
         Tools, APIs, Services
```

### 7.2 SDK Pattern

For frameworks that support it, a **governance SDK** provides native integration with lower latency than the sidecar. The SDK wraps the framework's tool-calling interface, routing calls through the governance layer within the same process.

The SDK and sidecar implement the same interface contract:

```
interface GovernanceClient {
    // Called once when agent starts.
    // Errors: GOVERNANCE_UNAVAILABLE, REGISTRATION_FAILED
    register(agent_type, task_context) → AgentIdentity | GovernanceError

    // Called before every tool/API call.
    // Errors: GOVERNANCE_UNAVAILABLE, IDENTITY_EXPIRED, IDENTITY_REVOKED,
    //         AUTHORITY_EXPIRED, POLICY_EVALUATION_TIMEOUT
    // On infrastructure error: MUST return DENY (fail-closed).
    request_action(action_type, action_params, resource) → PolicyEvaluationResponse | GovernanceError

    // Called when agent wants to spawn a child.
    // Errors: GOVERNANCE_UNAVAILABLE, IDENTITY_EXPIRED, AUTHORITY_EXPIRED
    // On infrastructure error: MUST fail (no child created).
    request_spawn(child_type, child_scope) → AgentIdentity | GovernanceError

    // Called when agent produces output for external consumption.
    // Errors: GOVERNANCE_UNAVAILABLE, IDENTITY_EXPIRED
    // On infrastructure error for synchronous channels: MUST block output.
    submit_output(output, output_type, audience) → OutputEvaluationResponse | GovernanceError

    // Called for permission pre-check (dry run).
    // Errors: GOVERNANCE_UNAVAILABLE, RATE_LIMITED
    introspect(action_type, action_params) → PolicyEvaluationResponse | GovernanceError

    // Called when agent completes or is terminated.
    terminate(reason) → void
}
```

All methods that can fail MUST fail-closed on infrastructure errors: `request_action` returns DENY, `request_spawn` fails, `submit_output` blocks synchronous outputs. See Appendix C.12 for the full `GovernanceError` type definition and error semantics.

### 7.3 Framework Adapters

Framework-specific adapters translate between a framework's native execution model and the governance interface. For example:

- A **LangChain adapter** wraps the `Tool` and `AgentExecutor` classes to route calls through `GovernanceClient`.
- A **CrewAI adapter** wraps the `Agent` and `Task` classes.
- An **MCP adapter** intercepts MCP tool calls at the protocol level.

Adapters are implementation details, not part of the specification. The specification defines the `GovernanceClient` interface. Adapter implementers are responsible for ensuring their adapter correctly translates the framework's execution model.

---

## 8. Compliance Projections

The specification captures comprehensive governance data: authority chains, policy evaluations, decision traces, trust histories, and escalation resolutions. This data provides a control and record substrate that can be mapped to regulatory obligations. The specification does not itself constitute compliance with any regulation, though it supports the production of evidence for compliance programs.

A **compliance projection** is a module that maps the specification's native event data to a specific regulatory framework's reporting requirements. Projections are configuration rather than architecture. Adopting this specification does not by itself amount to compliance with any regulatory framework; it provides the underlying control and audit infrastructure that compliance programs require.

### 8.1 Projection Model

```
ComplianceProjection {
    framework:          string          // "EU_AI_ACT" | "SOC2" | "HIPAA" | etc.
    version:            string          // Version of the regulatory framework
    mappings:           Mapping[]       // Maps spec events to regulatory requirements
}

Mapping {
    requirement_id:     string          // e.g., "EU_AI_ACT_ART_14"
    requirement_text:   string          // Human-readable requirement
    satisfied_by:       EventQuery      // Query against the Audit Ledger that demonstrates compliance
    evidence_format:    Format          // How to present the evidence
}
```

### 8.2 Example: EU AI Act Projection

| Requirement | Specification Mechanism |
|---|---|
| Art. 9: Risk management | Authority Registry risk-class definitions + Policy Gate tiered evaluation |
| Art. 11: Technical documentation | Authority grants, policy versions, and architecture documentation |
| Art. 12: Record-keeping | Audit Ledger with causal chains and decision traces |
| Art. 13: Transparency | Agent identity lineage chains (traceability of all decisions) |
| Art. 14: Human oversight | Escalation Router records + mandatory justification |
| Art. 15: Accuracy, robustness, security | Output Evaluator scope alignment + Trust Engine behavioral tracking |

### 8.3 Projection Lifecycle

Compliance projections are community-contributed and versioned independently from the specification. When a regulation changes, the projection is updated. The underlying governance architecture does not change; only the mapping layer does.

---

## 9. Relationship to Existing Standards

This specification does not replace existing security architectures or constitute a full AI management system. It is a governance-layer control and record substrate that layers on top of security infrastructure and supports evidence production for AI-governance obligations.

### 9.1 Security and Identity Standards

| Standard | Relationship |
|---|---|
| **Zero Trust** | This specification is Zero Trust applied to agents. Verify every action, assume potential compromise. Extended with lineage verification and context evaluation that human-focused Zero Trust does not require. |
| **ABAC** | The specification's policy model is ABAC. Authority is defined by attributes (agent type, task context, delegation depth, trust tier), not by roles. |
| **OAuth 2.0 / JWT** | Agent identities can be implemented as JWTs with custom claims for lineage and scope. The Identity Service functions as an authorization server. |
| **SPIFFE / SPIRE** | Workload identity standards apply to agent identity. Agent instances are workloads. SPIFFE IDs can serve as the identity substrate. |
| **Service Mesh (Envoy/Istio)** | The sidecar integration model is architecturally identical. Policy enforcement patterns from service mesh translate directly. |
| **Open Policy Agent (OPA)** | OPA (or similar policy engines) can serve as the Policy Gate's evaluation engine. The specification extends OPA's model with attenuation and escalation as decision types. |
| **Certificate Transparency** | The Audit Ledger's append-only, cryptographically chained design borrows from Certificate Transparency's approach to tamper-evident logging. |
| **Capability-Based Security** | Authority attenuation through delegation is borrowed from capability-based security (Capsicum, object-capabilities). |
| **MCP (Model Context Protocol)** | MCP standardizes tool access. This specification standardizes governance of that access. An MCP adapter routes MCP tool calls through the governance layer. |
| **AIP (Agent Identity Protocol)** | An emerging agent-identity standard that the Agent Identity Service (Section 3.2) can consume as its identity input. AIP carries identity, attenuated authority, and provenance in a signed token. Section 2.3 sets out how the governance layer reconciles such an input with its own guarantees. |
| **Authenticated Delegation (MIT)** | A delegation model that extends OAuth and verifiable credentials, suitable as an identity input for agents that cross organizational boundaries, under the reconciliation rules in Section 2.3. |
| **ACP (Agent Control Protocol)** | A temporal admission-control protocol whose stateful risk signals can be supplied to Tier 3 of the Policy Gate as further evidence, without displacing the four-outcome decision (Section 2.3). |

### 9.2 AI Governance Standards

This specification is a control-and-record substrate. It does not by itself satisfy any AI-specific regulatory or standards obligation. A correctly deployed implementation supports evidence production for the obligations below, but conformance depends on organizational policies, implementation fidelity, and regulatory context.

| Standard | Relationship |
|---|---|
| **NIST AI RMF 1.0** | Provides technical controls supporting the MANAGE function (risk response via authority scoping, rate limits, damage budgets, and fail-closed behavior) and the MEASURE function (continuous monitoring via the Audit Ledger's decision record). GOVERN and MAP functions remain organizational responsibilities that this specification does not address. |
| **NIST AI 600-1 (Generative AI Profile)** | Supports the incident-record requirements applicable to generative AI agents and the risk-response controls called out in the MANAGE function. Generative-AI-specific risks such as content provenance, synthetic-media disclosure, and training-data governance are out of scope. |
| **ISO/IEC 42001:2023** | Supports Clause 8 (Operation: operational planning and control of AI systems) and Clause 9 (Performance evaluation: monitoring, measurement, internal audit) through the Policy Gate's enforcement record and the Audit Ledger's traceable decision history. Clauses 4–7 (context, leadership, planning, support) and Clause 10 (improvement) remain organizational responsibilities. |
| **MITRE ATLAS** | Provides governance-layer containment for ATLAS techniques AML.T0051 (LLM Prompt Injection, see Section 1.3), AML.T0053 (LLM Plugin Compromise, via Execution Boundary credential isolation), and AML.T0057 (LLM Data Leakage, via credential and context isolation). Does not address model-layer techniques such as AML.T0043 (Craft Adversarial Data) or AML.T0054 (LLM Jailbreak). |
| **OWASP LLM Top 10 (2025)** | Directly addresses LLM06 (Excessive Agency) through authority scoping, delegation invariants, and rate limits. Provides governance-layer containment for LLM01 (Prompt Injection) consequences, LLM02 (Sensitive Information Disclosure) via credential isolation, and LLM10 (Unbounded Consumption) via rate limits and damage budgets. Does not address LLM03 (Supply Chain), LLM04 (Data and Model Poisoning), LLM05 (Improper Output Handling), LLM07 (System Prompt Leakage), LLM08 (Vector and Embedding Weaknesses), or LLM09 (Misinformation). |
| **EU AI Act (Regulation (EU) 2024/1689)** | For high-risk AI systems, supports obligations under Article 12 (Automatic logging) and Article 13 (Transparency and information to deployers) through the Audit Ledger's decision-traceability and causal-chain records. Article 14 (Human oversight) is supported architecturally through the Escalation Router but requires organizational implementation of review workflows. Articles 9, 10, 11, and 15, and conformity assessment obligations under Article 43, are out of scope. |

For each standard, "supports" means that a correctly deployed implementation produces the records, controls, or evidence an auditor or regulator can examine. It does not mean conformance with the standard is automatic or guaranteed.

---

## 10. Implementation Guidance

This section is non-normative. It provides recommendations for teams implementing the specification.

### 10.1 Phased Rollout

Implementing the full specification at once is neither necessary nor advisable.

**Phase 1: Identity and Authority**
Deploy the Authority Registry and Agent Identity Service. Begin issuing identities and authority grants. This is the foundation, since without identity and authority nothing else can operate.

**Phase 2: Policy Gate in Audit Mode**
Deploy the Policy Gate, but configure it to log decisions rather than enforce them. This lets you observe what would be blocked, tune policies, and build confidence before enforcement.

**Phase 3: Execution Boundary for High-Risk Tools**
Wrap the tools that could cause the most damage first: database writes, external communications, payment APIs, customer-facing systems. Lower-risk tools can remain unwrapped temporarily.

**Phase 4: Policy Gate in Enforcement Mode**
Once policies are tuned from audit data, switch to enforcement. Start with high-risk action classes and expand.

**Phase 5: Audit Ledger with Causal Chaining**
Upgrade from standard logs to the structured causal ledger. Backfilling causal links is impractical, so begin capturing them as soon as the ledger is deployed.

**Phase 6: Trust Engine**
Deploy dynamic trust scoring. This requires sufficient audit history to be meaningful, and deploying it too early produces unreliable trust assessments.

**Phase 7: Output Evaluator**
This is the most complex component and rests on the least mature field, so deploy it last, starting with high-risk output channels such as customer-facing and agent-to-agent.

**Phase 8: Escalation Router Optimization**
Once escalation patterns are observed, begin the feedback loop: generating candidate rules, reviewing them, and promoting them to policy.

### 10.2 Governance of the Governance Layer

The governance layer itself must be secured:

- The Policy Gate, Authority Registry, and Audit Ledger are high-value targets. Compromise of any component compromises the entire governance model.
- Administrative access to governance components must be separately authenticated, logged, and subject to multi-party approval for destructive operations.
- Governance component deployments must be independently verified (signed artifacts, verified configurations).
- The governance layer's own availability and integrity should be monitored by systems independent of the governance layer itself.

### 10.3 What This Specification Does Not Cover

- **Model safety.** This specification governs agent behavior, not model training, alignment, or safety evaluation.
- **Content filtering.** Output governance in this specification is scope alignment checking. Content moderation (toxicity, PII, brand safety) is orthogonal and can be layered alongside.
- **Agent framework design.** This specification is framework-agnostic. It does not prescribe how agents are built, how they reason, or how they plan.
- **Infrastructure security.** Network security, host hardening, and infrastructure access control are prerequisites, not components of this specification.

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| **Action** | Any operation an agent attempts: tool call, API invocation, agent spawn, or output to an external channel. |
| **Agent** | An autonomous AI system that takes actions in an environment based on LLM reasoning. |
| **Agent Type** | A category of agent with a defined purpose and authority profile. |
| **Attenuation** | Modification of an action to reduce its blast radius while still allowing it to proceed. |
| **Authority** | What an agent MAY do, as defined by the Authority Registry. Distinct from capability (what an agent CAN do). |
| **Authority Grant** | A specific authorization for an agent type, issued by a human, with defined scope, constraints, and TTL. |
| **Causal Chain** | The linked sequence of audit entries from an action back to the human authorization that originated the delegation chain. |
| **Capability Class** | A category of action type for purposes of trust scoring. E.g., data_read, data_write, external_comms. |
| **Compliance Projection** | A mapping module that translates the specification's native event data to a specific regulatory framework's requirements. |
| **Delegation** | The act of an agent spawning a child agent with a subset of its own authority. |
| **Delegation Attenuation** | The guarantee that authority only narrows through delegation, never widens. |
| **Escalation** | Routing an action to human review when automated evaluation cannot resolve it. |
| **Execution Boundary** | The proxy through which all agent actions execute. Holds credentials. Agents never access tools directly. |
| **Governance Sidecar** | A proxy process that intercepts agent actions and routes them through the governance layer. |
| **Identity** | A cryptographically signed record of an agent instance's type, lineage, authority scope, and trust tier. |
| **Lineage Chain** | The full ancestry of an agent instance, from the root (human-spawned) agent to the current instance. |
| **Policy Gate** | The enforcement point that evaluates every agent action and makes Allow/Deny/Escalate/Attenuate decisions. |
| **Scope Alignment** | The degree to which an agent's output is consistent with its assigned task and authority. |
| **Trust Tier** | A dynamic rating of an agent type's reliability in a specific capability class, based on observed behavior. |

---

## Appendix B: Normative Status by Profile

This specification defines a **Core Profile** and four **Extension Profiles**. An implementation that satisfies all Core-normative requirements is a conforming Core implementation. Extensions are independently adoptable, so an implementation may conform to Core plus any combination of extensions.

### Core Profile (required for conformance)

| Section | Status | Component |
|---|---|---|
| 1. Threat Model | Core-normative | — |
| 2. Architecture Overview | Core-normative | — |
| 3.1 Authority Registry | Core-normative | Authority Registry |
| 3.2 Agent Identity Service | Core-normative | Agent Identity Service |
| 3.3 Policy Gate (Tiers 1-2) | Core-normative | Policy Gate |
| 3.4 Execution Boundary | Core-normative | Execution Boundary |
| 3.5 Audit Ledger | Core-normative | Audit Ledger |
| 4. Event Schema (Core events) | Core-normative for interoperability | — |
| 5. System Guarantees (1-9) | Core-normative | — |
| 6. Failure Modes | Core-normative | — |

Core events: ActionRequested, ActionEvaluated, ActionExecuted, ActionDenied, ActionEscalated, AgentSpawned, AgentTerminated, AuthorityGrantCreated, AuthorityGrantTerminated, PolicyUpdated.

### Extension: Trust-Adjusted Evaluation

| Section | Status | Component |
|---|---|---|
| 3.3 Policy Gate (Tier 3) | Extension-normative | Policy Gate Tier 3 |
| 3.7 Trust Engine | Extension-normative | Trust Engine |
| TrustAdjusted event | Extension-normative for interoperability | — |

A Core-only implementation that omits Trust Engine and Tier 3 evaluation is conforming. Actions that would reach Tier 3 are escalated instead.

### Extension: Output Governance

| Section | Status | Component |
|---|---|---|
| 3.6 Output Evaluator | Extension-normative | Output Evaluator |
| OutputEvaluated event | Extension-normative for interoperability | — |

A Core-only implementation that omits Output Evaluator is conforming. Agent outputs are not governed at the specification level (content filtering and other output controls may exist outside this specification).

### Extension: Adaptive Escalation

| Section | Status | Component |
|---|---|---|
| 3.8 Escalation Router | Extension-normative | Escalation Router |
| EscalationResolved event | Extension-normative for interoperability | — |
| EscalationTimedOut event | Extension-normative for interoperability | — |

A Core-only implementation that receives ESCALATE decisions MUST still pause the action and record the escalation. The Extension defines the human review workflow, forced engagement design, feedback loop, and candidate rule promotion. Without this extension, escalation resolution is implementation-defined.

### Extension: Compliance Projection

| Section | Status | Component |
|---|---|---|
| 8. Compliance Projections | Extension-normative | Compliance mapping |

### Non-Normative Sections

| Section | Status |
|---|---|
| 7. Integration Model | Non-normative (recommended patterns) |
| 9. Relationship to Existing Standards | Non-normative (informational) |
| 10. Implementation Guidance | Non-normative (recommended practices) |

### Appendix Status

| Appendix | Status |
|---|---|
| A. Glossary | Non-normative |
| B. Normative Status (this section) | Meta-normative |
| C. Type Definitions | Core-normative for interoperability |
| D. Canonical Algorithms | Core-normative (D.1-D.4), Extension-normative (D.4 DELEGATION_TREE scope requires Trust Extension) |
| E. Governance of the Governance Layer | Core-normative (E.1-E.3 admin roles, dual control, kill switch), Extension-normative (E.6 trust metrics require Trust Extension) |
| F. Worked Examples | Non-normative |
