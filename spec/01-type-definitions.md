# Appendix C: Type Definitions

This appendix defines all types referenced in the specification. These definitions are **normative for interoperability** — conforming implementations that claim interoperability MUST serialize and deserialize these types according to these definitions.

Implementations MAY extend types with additional fields. Extension fields MUST NOT conflict with defined fields. Consumers MUST ignore unrecognized fields.

---

## C.1 Enumerations

### Decision

```
enum Decision {
    ALLOW
    DENY
    ESCALATE
    ATTENUATE
}
```

### OutputDecision

```
enum OutputDecision {
    RELEASE
    SUPPRESS
    ESCALATE
    REVISE           // Returns output to agent with specific findings for revision
}
```

**Design note:** REVISE was added based on review feedback. SUPPRESS blocks the output entirely. REVISE returns the output to the agent with structured findings, allowing the agent to correct scope violations without losing the compliant portions. The Output Evaluator does not modify the output — it provides feedback that the agent framework uses to prompt a revision.

### EscalationDecision

```
enum EscalationDecision {
    APPROVE
    DENY
    MODIFY          // See Section C.7 for ModifiedAction
}
```

### TerminationReason

```
enum TerminationReason {
    COMPLETED       // Agent finished its task normally
    EXPIRED         // Agent's identity TTL elapsed
    REVOKED         // Authority grant was revoked
    ERROR           // Agent encountered an unrecoverable error
    CASCADED        // Parent agent was terminated
    KILLED          // Emergency kill switch activated
}
```

### GrantTerminationReason

```
enum GrantTerminationReason {
    EXPIRED         // Grant's TTL elapsed (system-driven)
    REVOKED         // Grant was explicitly revoked by a human
    CASCADED        // Parent grant was terminated, propagating to this grant
}
```

Used by the `AuthorityGrantTerminated` event. Distinct from `TerminationReason`, which applies to agent identities. A grant and an identity can each terminate for different reasons — for example, an identity may be `CASCADED` while its underlying grant remains `ACTIVE`.

### TrustTier

```
enum TrustTier {
    HIGH
    MEDIUM
    LOW
    RESTRICTED
}
```

Implementations MAY define intermediate tiers. The four normative tiers define the minimum granularity.

### RiskLevel

```
enum RiskLevel {
    LOW
    MEDIUM
    HIGH
    CRITICAL
}
```

### OutputType

```
enum OutputType {
    RECOMMENDATION
    FACTUAL_CLAIM
    INSTRUCTION_TO_AGENT
    CUSTOMER_FACING
    INTERNAL_SUMMARY
}
```

Implementations MAY define additional output types.

### Audience

```
enum Audience {
    HUMAN_OPERATOR
    ANOTHER_AGENT
    EXTERNAL_CUSTOMER
    INTERNAL_SYSTEM
}
```

### ReasonCode

Structured reason codes for Policy Gate decisions. Used in `DenialReason` and `EvaluationRecord`.

```
enum ReasonCode {
    IDENTITY_INVALID            // Signature verification failed
    IDENTITY_EXPIRED            // Agent identity TTL elapsed
    AUTHORITY_EXPIRED           // Underlying grant TTL elapsed
    AUTHORITY_REVOKED           // Grant was explicitly revoked
    SCOPE_VIOLATION             // Action type not in authority scope
    RATE_LIMIT_EXCEEDED         // Per-action-type rate limit hit
    DAMAGE_BUDGET_EXCEEDED      // Aggregate impact limit hit
    DELEGATION_DEPTH_EXCEEDED   // Spawn would exceed max delegation depth
    DELEGATION_SCOPE_VIOLATION  // Requested child scope not a subset of parent's
    CONSTRAINT_VIOLATION        // Action parameters violate a policy constraint
    TRUST_INSUFFICIENT          // Agent's trust tier too low for this action at this tier
    BEHAVIORAL_ANOMALY          // Action outside behavioral envelope (Tier 3)
    AGGREGATE_THRESHOLD         // Collective action pattern exceeds threshold (Tier 3)
    VELOCITY_ANOMALY            // Action rate unusual for context (Tier 3)
    POLICY_MATCH_DENY           // Explicit deny rule matched
    ESCALATION_REQUIRED         // Policy mandates human review for this action class
    OUTPUT_SCOPE_MISALIGNED     // Output not consistent with agent's assigned task
    UNMATCHED_ACTION            // No rule matched; default deny applied
}
```

### CapabilityClass

Base taxonomy of capability classes for trust scoring. Implementations MUST support these base classes and MAY define additional classes.

```
enum CapabilityClass {
    DATA_READ                   // Reading data from any source
    DATA_WRITE                  // Writing, updating, or deleting data
    DATA_DELETE                 // Destructive data operations (subset of WRITE, tracked separately)
    EXTERNAL_COMMS              // Communications to external parties
    INTERNAL_COMMS              // Communications to internal systems/users
    FINANCIAL_TRANSACTION       // Monetary operations
    AGENT_SPAWN                 // Creating child agents
    SYSTEM_CONFIG               // Modifying system configuration
    CUSTOMER_FACING_OUTPUT      // Producing content visible to customers
}
```

Each capability class MUST be assigned a `RiskLevel` in the implementation's configuration. This risk level determines the minimum trust tier required for automated resolution at each evaluation tier.

---

## C.2 PolicyScope

The central type defining what an agent is authorized to do. PolicyScope supports subset operations for delegation attenuation.

```
PolicyScope {
    authorized_actions: ActionPattern[]     // Which action types are permitted
    resource_constraints: ResourceConstraint[]  // Which resources can be accessed
    parameter_constraints: ParameterConstraint[] // Constraints on action parameters
    output_policy: OutputPolicy             // Constraints on agent outputs
    delegation: DelegationRule              // Whether and how the agent can delegate
}
```

### Subset Relation

Scope A is a **subset** of Scope B if and only if:
1. Every action pattern in A matches a subset of the actions matched by B's patterns.
2. Every resource constraint in A is equal to or more restrictive than the corresponding constraint in B.
3. Every parameter constraint in A is equal to or more restrictive than the corresponding constraint in B.
4. A's output policy is equal to or more restrictive than B's output policy.
5. A's delegation rules are equal to or more restrictive than B's delegation rules.

The Identity Service MUST implement this subset check and MUST reject child identity requests where the requested scope is not a subset of the parent's delegatable scope.

### ActionPattern

```
ActionPattern {
    pattern:                string                  // Action type pattern. Supports wildcards.
                                                    // "gmail.drafts.create" — exact match
                                                    // "gmail.drafts.*" — all draft operations
                                                    // "gmail.*" — all gmail operations
                                                    // "*" — all actions (use with caution)
    decision:               Decision                // Decision when constraints satisfied
                                                    // (or absent)
    constraints:            ParameterConstraint[]   // Conditions that gate the decision
    on_constraint_fail:     Decision | null         // Decision when constraints present and
                                                    // not satisfied. When non-null, takes
                                                    // precedence over attenuation. Null
                                                    // (default) defers to attenuation for
                                                    // ALLOW rules and to DENY otherwise.
                                                    // MUST be null if constraints is empty.
                                                    // MUST NOT be ATTENUATE.
                                                    // See D.2 Constraint Failure Precedence.
    escalation:             EscalationRule | null   // Override escalation behavior
}
```

### ResourceConstraint

```
ResourceConstraint {
    resource_pattern:   string          // Resource identifier pattern (supports wildcards)
    access_level:       ACCESS_READ | ACCESS_WRITE | ACCESS_DELETE | ACCESS_EXECUTE
    classification_max: string | null   // Maximum data classification level (e.g., "CONFIDENTIAL")
    conditions:         Condition[]     // Additional conditions
}
```

### ParameterConstraint

```
ParameterConstraint {
    field:              string          // Dot-notation path into action_params
    operator:           ConstraintOperator
    value:              any             // The comparison value
}
```

### ConstraintOperator

```
enum ConstraintOperator {
    EQUALS                  // field == value
    NOT_EQUALS              // field != value
    LESS_THAN               // field < value
    LESS_THAN_OR_EQUAL      // field <= value
    GREATER_THAN            // field > value
    GREATER_THAN_OR_EQUAL   // field >= value
    IN                      // field is in value (value is a list)
    NOT_IN                  // field is not in value (value is a list)
    MATCHES                 // field matches value (value is a regex pattern)
    NOT_MATCHES             // field does not match value
    EXISTS                  // field is present
    NOT_EXISTS              // field is absent
}
```

### Condition

General-purpose condition used in constraints and rules.

```
Condition {
    field:              string          // Dot-notation field path. Supports variable references:
                                        // "${agent.task_context.user_id}" — from agent identity
                                        // "${action.params.recipient}" — from action parameters
                                        // "${env.current_time}" — from execution environment
    operator:           ConstraintOperator
    value:              any
}
```

### OutputPolicy

```
OutputPolicy {
    authorized_output_types: OutputType[]   // Which output types this agent may produce
    synchronous_channels: SyncChannelRule[] // Which audience/type combinations require sync evaluation
    scope_keywords: string[]                // Terms/topics within scope (for scope alignment)
    out_of_scope_keywords: string[]         // Terms/topics explicitly outside scope
}

SyncChannelRule {
    audience:           Audience | null     // null means "any audience"
    output_type:        OutputType | null   // null means "any type"
    // A rule matches if both audience and output_type match (null = wildcard)
}
```

---

## C.3 DelegationRule

```
DelegationRule {
    can_delegate:       boolean         // Whether this agent can spawn children at all
    max_depth:          integer         // Maximum delegation chain depth from this agent
    max_breadth:        integer         // Maximum concurrent children per agent instance
    delegatable_scope:  PolicyScope | null  // Scope available for delegation (null = same as agent's scope)
                                        // Must be a subset of the agent's own scope
    allowed_child_types: string[] | null   // Which agent types can be spawned (null = any)
    child_ttl_max:      duration | null    // Maximum TTL for child identities (null = parent's remaining TTL)
}
```

---

## C.4 EscalationRule

```
EscalationRule {
    always_escalate:    string[]        // Action patterns that always require human review
    escalate_when:      ConditionalEscalation[]  // Conditions that trigger escalation
    notify:             string[]        // Identities to notify on escalation
    timeout:            duration        // How long to wait for human response
    on_timeout:         Decision        // Decision if human does not respond (default: DENY)
    default_risk_level: RiskLevel       // Risk level applied to escalations from this grant
}

ConditionalEscalation {
    action_pattern:     string          // Which actions this condition applies to
    conditions:         Condition[]     // When those actions should escalate
    notify:             string[]        // Override notification list for this condition
    timeout:            duration | null // Override timeout for this condition
    on_timeout:         Decision | null // Override timeout decision
}
```

---

## C.5 RateLimit

```
RateLimit {
    action_pattern:     string          // Which action types this limit applies to
    max_count:          integer         // Maximum number of actions in the window
    window:             duration        // Time window for counting
    window_type:        SLIDING | FIXED // Sliding window or fixed-interval reset
    scope:              INSTANCE | TYPE | DELEGATION_TREE
                                        // INSTANCE: per agent instance
                                        // TYPE: across all instances of this agent type
                                        // DELEGATION_TREE: across the entire delegation tree
    on_exceed:          DENY | ESCALATE // What happens when limit is hit
}
```

**Rate limit interaction with attenuation:** Attenuated actions count against the rate limit of the **original** action type, not the attenuated form. An action attenuated from read-write to read-only counts against the read-write rate limit. This prevents attenuation from being used to circumvent rate limits.

---

## C.6 DamageBudget

```
DamageBudget {
    budgets:            BudgetEntry[]
}

BudgetEntry {
    metric:             string          // What is being measured
                                        // Examples: "dollar_amount", "record_count",
                                        // "external_recipients", "api_calls"
    threshold:          number          // Maximum permitted value
    window:             duration        // Time window for accumulation
    scope:              INSTANCE | TYPE | DELEGATION_TREE
    accumulator:        string          // Dot-notation path to the value in action_params
                                        // that contributes to this metric.
                                        // Example: "params.transaction.amount"
    on_exceed:          DENY | ESCALATE
    evaluation_tier:    2 | 3           // Which tier checks this budget.
                                        // Tier 2 for simple thresholds on individual actions.
                                        // Tier 3 for aggregate accumulation across actions.
}
```

---

## C.7 Action and Resource Types

### ActionDescriptor

```
ActionDescriptor {
    action_type:        string          // Hierarchical action identifier (e.g., "gmail.drafts.create")
    params:             object          // Action-specific parameters (structure varies by action type)
    resource:           ResourceDescriptor  // Target resource
}
```

### ResourceDescriptor

```
ResourceDescriptor {
    resource_type:      string          // Type of resource (e.g., "database", "api", "filesystem")
    resource_id:        string          // Resource identifier (e.g., "customer-database-prod")
    classification:     string | null   // Data classification level if applicable
    attributes:         object          // Additional resource attributes for ABAC evaluation
}
```

### ActionOutcome

```
ActionOutcome {
    status:             SUCCESS | FAILURE | TIMEOUT | PARTIAL
    result:             object | null   // Action-specific result data
    error:              ErrorInfo | null // Error details if status is FAILURE
    duration_ms:        integer         // Execution time in milliseconds
}

ErrorInfo {
    code:               string
    message:            string
    retryable:          boolean
}
```

### Attenuation

```
Attenuation {
    original_action:    ActionDescriptor    // What was requested
    attenuated_action:  ActionDescriptor    // What will actually execute
    modifications:      Modification[]      // What was changed and why
}

Modification {
    field:              string          // Which field was modified
    original_value:     any             // Original value
    attenuated_value:   any             // Attenuated value
    reason:             string          // Why this modification was applied
    policy_rule:        string          // Which policy rule triggered this attenuation
}
```

### ModifiedAction

Used when a human reviewer selects MODIFY during escalation resolution.

```
ModifiedAction {
    original_action:    ActionDescriptor    // What was originally requested
    modified_action:    ActionDescriptor    // What the human approved instead
    modifications:      Modification[]      // What was changed
    requires_reevaluation: boolean          // Whether the modified action must pass through the Policy Gate
                                            // Default: true. The modified action is re-evaluated to ensure
                                            // it still conforms to policy.
}
```

---

## C.8 Context Types

### TaskContext

```
TaskContext {
    task_id:            string          // Unique identifier for the task
    task_description:   string          // Human-readable description of what the agent should do
    initiated_by:       string          // Human identity who initiated the task
    initiated_at:       timestamp
    parameters:         object          // Task-specific parameters
}
```

### ExecutionContext

```
ExecutionContext {
    task_context:       TaskContext
    actions_taken:      integer         // Number of actions this agent has taken in this task
    actions_denied:     integer         // Number of actions denied in this task
    actions_escalated:  integer         // Number of actions escalated in this task
    elapsed_time:       duration        // Time since agent started this task
    recent_actions:     ActionSummary[] // Summary of recent actions (last N, implementation-defined)
}

ActionSummary {
    action_type:        string
    decision:           Decision
    timestamp:          timestamp
}
```

### TrustSnapshot

```
TrustSnapshot {
    agent_type:         string
    capability_trust:   Map<CapabilityClass, TrustTier>
    snapshot_at:        timestamp
}
```

### TrustHistory

```
TrustHistory {
    observations:       TrustObservation[]
    window:             duration        // How far back observations extend
}

TrustObservation {
    capability_class:   CapabilityClass
    outcome:            SUCCESSFUL | DENIED | ESCALATED_APPROVED | ESCALATED_DENIED | INCIDENT
    action_type:        string
    timestamp:          timestamp
    audit_entry_id:     string          // Links to the audit entry for this observation
}
```

---

## C.9 Evaluation Types

### EvaluationRecord

```
EvaluationRecord {
    decision:           Decision
    tier:               integer         // 1, 2, or 3
    reason_code:        ReasonCode
    reason_detail:      string | null   // Human-readable detail (optional)
    policy_version:     string
    rule_matched:       string | null   // Identifier of the policy rule that matched
    evaluation_time_ms: integer         // How long evaluation took
}
```

### TierResult

```
TierResult {
    tier:               integer
    evaluated:          boolean         // Whether this tier was reached
    result:             RESOLVED | UNRESOLVED | SKIPPED
    decision:           Decision | null // If resolved, what was the decision
    reason_code:        ReasonCode | null
    reason_detail:      string | null
}
```

### Finding

Used by the Output Evaluator to report specific scope violations or concerns.

```
Finding {
    finding_type:       SCOPE_VIOLATION | AUDIENCE_MISMATCH | CONFIDENCE_CONCERN |
                        INFLUENCE_RISK | POLICY_VIOLATION
    severity:           RiskLevel
    description:        string          // What was found
    location:           string | null   // Where in the output (e.g., paragraph number, field path)
    recommendation:     string | null   // Suggested remediation
}
```

---

## C.10 Rule Candidate Type

### CandidateRule

Generated by escalation resolutions to feed the policy learning loop.

```
CandidateRule {
    candidate_id:       string
    source_escalation:  string          // Event ID of the escalation resolution that generated this
    proposed_rule:      ActionPattern   // The rule that would automate this decision
    proposed_tier:      1 | 2 | 3      // Which tier this rule should be evaluated at
    confidence:         float           // 0.0 to 1.0 — how applicable this rule is beyond the specific case
    status:             PROPOSED | UNDER_REVIEW | APPROVED | REJECTED | PROMOTED
    reviewed_by:        string | null   // Human who reviewed (must differ from escalation decider)
    promoted_at:        timestamp | null
    policy_version:     string | null   // Policy version this rule was promoted into
}
```

---

## C.11 Agent Output Type

### AgentOutput

```
AgentOutput {
    content:            string          // The output text or structured data
    format:             TEXT | STRUCTURED_DATA | MARKDOWN | HTML | JSON
    metadata:           object | null   // Output-specific metadata
    token_count:        integer | null  // If applicable
}
```

---

## C.12 Governance Error Types

Error types for the GovernanceClient interface (Section 7.2). All GovernanceClient methods MUST use these error types for failure conditions.

```
GovernanceError {
    error_type:         GovernanceErrorType
    message:            string
    retryable:          boolean
    retry_after_ms:     integer | null  // Suggested retry delay if retryable
}

enum GovernanceErrorType {
    GOVERNANCE_UNAVAILABLE      // Governance infrastructure is unreachable
    AUTHORITY_EXPIRED           // The agent's authority grant has expired
    IDENTITY_EXPIRED            // The agent's identity has expired
    IDENTITY_INVALID            // Identity signature verification failed
    IDENTITY_REVOKED            // Identity has been revoked (parent terminated, grant revoked)
    REGISTRATION_FAILED         // Agent could not be registered (registry down, invalid type)
    RATE_LIMITED                // Too many requests to governance infrastructure itself
    POLICY_EVALUATION_TIMEOUT   // Policy evaluation did not complete within timeout
}
```

**Failure behavior:** When a GovernanceClient method encounters an infrastructure error (`GOVERNANCE_UNAVAILABLE`, `POLICY_EVALUATION_TIMEOUT`), it MUST fail-closed: `request_action` returns DENY, `request_spawn` fails, `submit_output` blocks synchronous outputs. The agent framework receives the error and MAY retry according to `retry_after_ms` if `retryable` is true.

When a GovernanceClient method encounters an authority/identity error (`AUTHORITY_EXPIRED`, `IDENTITY_EXPIRED`, `IDENTITY_REVOKED`), retrying is pointless — the agent must be re-registered with a new identity or the grant must be renewed by a human.

---

## C.13 Compliance Projection Types

### EventQuery

```
EventQuery {
    event_types:        string[]        // Which event types to query
    filters:            Condition[]     // Filter conditions on event fields
    time_range:         TimeRange | null
    aggregation:        Aggregation | null  // Optional aggregation (count, sum, etc.)
}

TimeRange {
    start:              timestamp | null    // null = unbounded start
    end:                timestamp | null    // null = unbounded end (up to now)
}

Aggregation {
    type:               COUNT | SUM | AVG | MIN | MAX | DISTINCT
    field:              string          // Which field to aggregate on
    group_by:           string[] | null // Optional grouping fields
}
```

### Format

```
Format {
    format_type:        TABLE | NARRATIVE | TIMELINE | EVIDENCE_CHAIN
    template:           string | null   // Template for rendering (implementation-specific)
    include_fields:     string[]        // Which event fields to include in output
}
```

---

## C.14 Audit Queue Configuration

```
AuditQueueConfig {
    max_depth:          integer | null  // Maximum number of entries in the local queue.
                                        // null = use max_age or max_bytes only.
    max_age:            duration | null // Maximum age of oldest unwritten entry.
                                        // null = use max_depth or max_bytes only.
    max_bytes:          integer | null  // Maximum size of the local queue in bytes.
                                        // null = use max_depth or max_age only.
    on_threshold_exceeded: FAIL_CLOSED  // When any threshold is exceeded, new actions fail-closed.
                                        // In-flight actions complete but their audit entries
                                        // are queued locally.
    monitoring:         boolean         // Whether queue depth/age/size are exposed via health metrics.
                                        // MUST be true for conforming implementations.
}
```

At least one of `max_depth`, `max_age`, or `max_bytes` MUST be configured. Implementations MUST expose current queue state through a monitoring interface.

---

## C.15 Hash Chain Configuration

```
HashChainConfig {
    algorithm:          SHA256 | SHA384 | SHA512
                                        // The hash algorithm used for chain integrity.
                                        // Conforming implementations MUST support SHA256.
                                        // Implementations MAY support additional algorithms.
    genesis_entry:      GenesisEntry    // The first entry in the chain.
    external_anchoring: ExternalAnchor | null  // Optional external timestamping.
}

GenesisEntry {
    entry_id:           string          // Fixed identifier for the genesis entry
    timestamp:          timestamp       // When the chain was initialized
    initialized_by:     string          // Human identity who initialized the ledger
    algorithm:          string          // Hash algorithm declared at initialization
    chain_id:           string          // Unique identifier for this chain instance
    signature:          string          // Signed by the initializing authority
}

ExternalAnchor {
    service:            string          // External timestamping service identifier
    interval:           duration        // How often chain heads are published
    verification_url:   string | null   // Where published anchors can be verified
}
```

Implementations SHOULD support external anchoring. Publishing chain head hashes to an independent timestamping service at regular intervals allows detection of wholesale chain replacement — an attack that a self-contained hash chain cannot detect.
