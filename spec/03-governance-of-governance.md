# Appendix E: Governance of the Governance Layer

The governance layer itself is a high-value target (Threat 5, Section 1.1). This appendix defines normative requirements for securing the governance infrastructure.

---

## E.1 Administrative Roles

Implementations MUST define and enforce the following administrative role separation:

| Role | Permissions | Cannot |
|---|---|---|
| **Grant Administrator** | Create, modify, and revoke authority grants. Update policies. Monitor grant Termination Completeness (Section 3.1); investigate and remediate stale grants where `is_expired(now)` but `terminated == false`. | Access audit data beyond grant-scoped queries. Resolve escalations. Activate kill switch. Rotate governance signing or hashing keys (Emergency Operator + E.2). |
| **Audit Reader** | Read and query the Audit Ledger. Run compliance projections. Run `verify_integrity` on cadence (E.5). Reconcile external chain anchors (Section 3.5). | Modify grants, policies, or trust. Resolve escalations. Write to the Audit Ledger (the ledger is populated by governance infrastructure only). Modify or disable metric definitions (E.2). |
| **Escalation Reviewer** | Review and resolve escalated actions. Provide justification. | Create or modify grants. Access audit data beyond the escalation context provided. Approve their own candidate-rule promotions (E.2). Modify trust parameters or rotate governance keys. |
| **Trust Administrator** | Configure trust adjustment parameters. Review trust history. | Create or modify grants. Resolve escalations. Activate kill switch. Access audit data beyond trust-scoped queries. Unilaterally raise trust tiers, reset trust state across an agent type, or modify decay parameters (E.2). |
| **Emergency Operator** | Activate graduated response levels (E.3.1) and the kill switch (E.3). Force-revoke all grants. Enact time-bound policy freezes (E.4). Authorize rotation of governance signing and hashing keys (E.5). | Create new grants (must be done by Grant Administrator after kill switch). Resolve escalations. Modify policies directly. Read Audit Ledger contents beyond incident-scoped queries. Modify trust parameters. |

No single individual may hold all roles. Implementations MUST enforce that at least the following separations are maintained:

- The person who creates a grant MUST NOT be the only person who can revoke it.
- The person who resolves an escalation MUST NOT be the person who approves the resulting candidate rule for policy promotion.
- The person who activates the kill switch MUST NOT be the person who re-creates grants afterward.
- The person who configures external chain anchors MUST NOT be the sole Audit Reader who reconciles them.

---

## E.2 Dual Control for High-Risk Operations

The following operations MUST require approval from two or more authorized individuals:

| Operation | Minimum Approvers | Rationale |
|---|---|---|
| Create grant with `can_delegate: true` and `max_depth > 1` | 2 Grant Administrators | Deep delegation trees amplify risk. |
| Create grant with damage budget threshold above implementation-defined high-water mark | 2 Grant Administrators | High-value budgets warrant additional scrutiny. |
| Promote a candidate rule to policy | Original escalation reviewer + 1 Grant Administrator | Prevents single-reviewer policy injection. |
| Modify the governance layer's own configuration | 2 Emergency Operators, or 1 Emergency Operator + 1 Grant Administrator | Governance infrastructure changes affect all agents. |
| Disable or reduce audit retention periods | 2 Audit Readers + 1 Grant Administrator | Reducing audit coverage must not be unilateral. |
| Disable or modify observability metric definitions; reduce metric retention | 2 Audit Readers + 1 Grant Administrator | Blinding the detection surface must not be unilateral. |
| Bulk trust reset across an agent type, or raise an agent type's trust tier for any capability class | 2 Trust Administrators, or 1 Trust Administrator + 1 Grant Administrator | Trust softens scrutiny; fleet-wide shifts warrant two-party review. |
| Modify trust decay parameters or per-capability trust bounds | 2 Trust Administrators | Changes the envelope of automatic scrutiny for all agents. |
| Rotate Identity Service signing keys, Audit Ledger hashing keys, or external-anchor signing keys | 2 Emergency Operators | Key rotation affects historical verifiability; it preserves chain integrity when done correctly and breaks audits when done wrong. |
| Enact a policy-change freeze exceeding 4 hours (E.4) | 2 Emergency Operators, or 1 Emergency Operator + 1 Grant Administrator | Prevents drift from legitimate policy evolution without triggering the kill switch. |

Dual control decisions are recorded in the Audit Ledger with both approver identities.

---

## E.3 Kill Switch Authorization

The kill switch (Section 6) MUST be protected by:

1. **Authentication.** The activating individual must be authenticated through the organization's identity provider, not through the governance system itself (which may be compromised).
2. **Authorization.** Only Emergency Operators may activate the kill switch. The role MUST be held by a small, named set of individuals (implementation-defined, recommended: 2-5 people).
3. **Confirmation.** The kill switch MUST require an explicit confirmation step. Single-click activation is not conforming.
4. **Audit.** Kill switch activation is recorded in the Audit Ledger before the revocation cascade begins. The Audit Ledger continues to function after activation.
5. **Notification.** All Grant Administrators and Emergency Operators are notified immediately upon activation.
6. **Recovery.** Resuming operations requires fresh grant creation by Grant Administrators. The kill switch activation event is permanently recorded and cannot be removed from the audit history.

---

## E.3.1 Graduated Response Levels

The kill switch (E.3) is an all-stop action. Many incidents warrant intermediate response without total shutdown. Conforming implementations MUST support the following graduated response levels:

| Level | Effect | Activation |
|---|---|---|
| **L0 Normal** | Standard operations. | Default state. |
| **L1 Heightened** | Candidate-rule auto-promotion is disabled (all promotions require dual approval per E.2). Tier 3 evaluation is forced for all sensitive-category actions regardless of trust tier. Escalation timeout windows MAY be shortened per implementation policy. | 1 Emergency Operator. |
| **L2 Restricted** | L1, plus: new grant creation is frozen (existing grants continue). Action rate limits MAY be tightened per implementation policy. All mutating actions escalate regardless of policy. | 2 Emergency Operators, or 1 Emergency Operator + 1 Grant Administrator. |
| **L3 Kill Switch** | Per E.3. | Per E.3. |

Each level activation MUST:

- Be time-bounded (implementation-defined maximum; RECOMMENDED: 24h for L1, 12h for L2). Extension requires reactivation under the same authorization requirement.
- Be recorded in the Audit Ledger with activating identity, level, reason, and expiration.
- Trigger notification to all Grant Administrators and Emergency Operators.
- Be visible via the observability interface (E.6 System Health).

De-escalation (returning to a lower level) requires the same authorization as the activation of the level being left.

---

## E.3.2 Incident Severity and Notification

Graduated response (E.3.1) addresses *what* the system does during an incident. Severity classification addresses *who* is notified, *how fast*, and *by what channel*. Conforming implementations MUST classify governance-layer incidents using the following framework:

| Severity | Definition | Notification | Target Engagement |
|---|---|---|---|
| **S0 Critical** | Kill switch activation. Total governance outage. Audit Ledger chain integrity break. Widespread fail-closed across components. | Immediately page all Emergency Operators and Grant Administrators. Notify incident response leadership. | Within 15 minutes. |
| **S1 High** | Policy Gate unreachable at scale. Authority Registry partial outage. Termination Completeness invariant breach (nonzero stale-grant count). External anchor divergence. Failed backup restore drill. Dual-control operation completed without a required second approver. | Immediately page on-call Emergency Operator and designated Audit Reader. Notify Grant Administrators. | Within 1 hour. |
| **S2 Moderate** | Escalation Router outage or sustained queue backup. Sustained abnormal Tier 3 escalation rate. Trust adjustment anomalies. Single-component flapping. | Alert on-call rotation. Notify designated administrators. | Within 4 business hours / 8 off-hours. |
| **S3 Low** | Metric anomalies without operational impact. Single-entry audit anomalies resolved by re-verification. Non-critical component recoverable errors. | Ticketed for standard review. | Next business day. |

Implementations MUST:

- Maintain an on-call rotation for Emergency Operators and Audit Readers with coverage consistent with the target engagement times above.
- Document severity classification criteria and review them periodically (RECOMMENDED: annually).
- Track classification, response time, and resolution for every incident in the Audit Ledger.
- Surface severity distribution and response-time metrics per E.6 Governance-of-Governance Metrics.

Severity classification is independent of graduated response level (E.3.1). An S1 incident may be addressed without activating L1; an L1 response may be warranted for S2 incidents during heightened threat windows. Severity and level MAY be adjusted as an incident evolves; all transitions are recorded.

---

## E.4 Policy Change Management

Policy changes (new grants, grant modifications, policy version updates) follow a governed lifecycle:

```
1. Grant Administrator drafts policy change
2. validate_policy runs (Section 3.1) — rejects inconsistent policies
3. Change enters review queue
4. Second Grant Administrator approves (for high-risk changes)
   OR change auto-approves (for low-risk changes within predefined parameters)
5. Change is versioned and deployed
6. PolicyUpdated event is emitted
7. Policy Gate instances receive updated policy within the propagation SLA
```

**Rollback:** If a policy change causes unexpected behavior (spike in denials, escalation surge), any Grant Administrator can initiate rollback. Rollback creates a new version that restores the content of a prior version. It does not delete the intermediate version.

**Change freeze:** During an active incident or investigation, any Emergency Operator MAY enact a time-bound freeze preventing any policy change. Freezes exceeding 4 hours require dual control per E.2. The freeze MUST:

- Have an explicit expiration time.
- Reject all policy changes (including candidate rule promotions) during the freeze window.
- Be recorded in the Audit Ledger with activating identity, reason, and expiration.
- Not block emergency grant revocations or kill switch activation.

**Change audit:** Every policy change records who drafted it, who approved it, what changed (diff between versions), and when it was deployed. This history is immutable.

---

## E.5 Infrastructure Security Requirements

| Requirement | Description |
|---|---|
| **Signed artifacts** | Governance component deployments MUST use signed artifacts. Unsigned or tampered artifacts MUST NOT be deployed. |
| **Independent monitoring** | The governance layer's health, availability, and integrity MUST be monitored by systems that are independent of the governance layer — running on separate infrastructure, using separate credentials, and administered by personnel not responsible for governance-layer operations. Independent monitoring MUST detect, at minimum: (a) failure of any Core component; (b) unexpected silence from the Audit Ledger when activity is expected (silent-corruption proxy); (c) external anchor divergence (per Chain integrity verification, below); (d) stale-grant count exceeding zero (per Grant termination monitoring, below); (e) graduated response level changes (E.3.1); (f) dual-control operations (E.2) completing without the required second approver. A failure in the governance layer MUST NOT suppress the alert about that failure. Monitoring integrity is itself verified periodically (RECOMMENDED: monthly) via synthetic incident injection, with results recorded per E.6. |
| **Network isolation** | Governance infrastructure endpoints (Authority Registry, Identity Service, Policy Gate control plane, Audit Ledger write interface) SHOULD be network-isolated from agent runtimes. Agents interact through the Governance Sidecar or SDK, not directly with governance infrastructure. |
| **Execution Boundary credential rotation** | Credentials used by the Execution Boundary to access tools and APIs MUST be rotated on a schedule. Rotation MUST NOT require agent restart or grant reissuance. |
| **Governance signing and hashing keys** | Identity Service signing keys, Audit Ledger hashing keys (when using keyed hash algorithms), and external-anchor signing keys MUST be rotated on a schedule. Rotation MUST preserve verifiability of historical signatures and hashes via key history preservation — previous keys MUST remain available for audit replay. Rotation MUST NOT invalidate existing grants or identities and is dual-controlled per E.2. |
| **Chain integrity verification** | Audit Readers MUST run `verify_integrity` on active chains at an implementation-defined cadence. RECOMMENDED minimum: daily for the hot-tier chain head, weekly for warm-tier chains, quarterly for cold-tier chains. Verification failures MUST trigger incident response via the independent monitoring path (above). External chain anchors (Section 3.5) MUST be reconciled on each verification pass; any divergence MUST be treated as a verification failure. |
| **Grant termination monitoring** | Implementations MUST surface any grant where `is_expired(now)` but `terminated == false` to the observability interface (E.6) within a bounded detection window (RECOMMENDED: 1 minute for eager implementations, 1 Policy Gate evaluation for lazy implementations). A nonzero stale-grant count indicates a Termination Completeness invariant breach (Section 3.1) and MUST trigger incident response. Grant Administrators own investigation and remediation. |
| **Backup and recovery** | The Audit Ledger, Authority Registry, and Identity Registry MUST have documented backup and recovery procedures with per-component RTO and RPO targets (implementation-defined; RECOMMENDED: RPO ≤ 5 minutes for the Audit Ledger, ≤ 15 minutes for the Identity Registry, ≤ 1 hour for the Authority Registry). Backups MUST be encrypted at rest using keys independent of the primary system's credential store; backup credentials MUST be isolated from the primary credential store. Backup integrity MUST be verified without requiring a restore (RECOMMENDED: weekly for Audit Ledger backups via `verify_integrity` on the backup copy; monthly for registries). Full restore drills MUST be conducted on a defined schedule (RECOMMENDED: at least quarterly) to a parallel environment, with (i) recovery time compared against RTO targets, (ii) chain-integrity verification for the restored Audit Ledger, and (iii) drill results recorded in the Audit Ledger. A failed restore drill is an S1 incident (E.3.2). |

---

## E.6 Observability Requirements

Conforming implementations MUST expose the following operational metrics through a monitoring interface:

### Policy Gate Metrics

- Decision distribution: count of ALLOW, DENY, ESCALATE, ATTENUATE per time window
- Tier resolution distribution: percentage of actions resolved at each tier
- Evaluation latency: p50, p95, p99 per tier
- Introspection rate: dry-run evaluations per time window per agent type

### Escalation Metrics

- Escalation queue depth: number of pending escalations
- Escalation resolution time: p50, p95 from escalation to resolution
- Timeout rate: percentage of escalations that time out
- Candidate rule promotion rate: rules promoted per time window

### Audit Metrics

- Audit queue depth: entries pending write (if ledger is temporarily unavailable)
- Audit queue age: age of oldest pending entry
- Chain length: total entries
- Chain integrity: last `verify_integrity` result and timestamp
- External anchor reconciliation: last reconciliation result and timestamp; anchor divergence count (expected: 0)

### Trust Metrics

- Trust adjustment frequency: changes per agent type per time window
- Trust distribution: count of agent types at each trust tier per capability class

### Grant Lifecycle Metrics

These metrics track Termination Completeness (Section 3.1):

- Terminations emitted: count by reason (EXPIRED, REVOKED, CASCADED) per time window
- Termination detection mode: count of eager (sweep-driven) vs. lazy (access-driven) emissions
- Termination latency: p50, p95 between TTL elapse and `AuthorityGrantTerminated` emission (applicable to lazy implementations)
- Stale grants: count where `is_expired(now)` but `terminated == false` (expected: 0; any nonzero value is an invariant breach per E.5 Grant termination monitoring)

### System Health

- Component availability: up/down status per component
- Circuit breaker state: open/closed per component
- Grant utilization: active agents per grant; approaching-expiry grants
- Graduated response level (E.3.1): current level (L0–L3), activating identity, expiration timestamp

### Governance-of-Governance Metrics

These metrics track the operational integrity of the governance layer itself — the "who watches the watchmen" surface:

- Incident distribution: count by severity (S0/S1/S2/S3, per E.3.2) per time window
- Incident response time: p50, p95 from detection to engagement per severity
- Dual-control completion rate: percentage of E.2 operations completing with required approvers (expected: 100%)
- Independent monitoring synthetic test: last synthetic incident injection result and timestamp (per E.5 Independent monitoring)
- Backup integrity verification: last successful backup-copy `verify_integrity` pass per protected component (per E.5 Backup and recovery)
- Restore drill: last successful full-restore drill timestamp and measured RTO per component
- Key rotation: last rotation timestamp per key class (Identity Service signing, Audit Ledger hashing, external anchor signing)
- On-call coverage: percentage of time the Emergency Operator and Audit Reader rotations are staffed (expected: 100%)

Metrics MUST be accessible to Audit Readers and system operators. Metrics MUST NOT be accessible to agents. Metric definitions and retention are themselves governed — modifications require dual control per E.2.
