# Appendix D: Canonical Algorithms

This appendix defines the reference algorithms for action pattern matching, policy rule evaluation, and scope subset comparison. These algorithms are **normative** — conforming implementations MUST produce identical results for identical inputs.

A reference implementation in Python is provided at `simulation/reference_algorithms.py`.

---

## D.1 Action Pattern Matching

An action pattern is a string that matches action types using the following rules:

| Pattern | Matches | Does Not Match |
|---|---|---|
| `gmail.drafts.create` | `gmail.drafts.create` only | `gmail.drafts.delete`, `gmail.messages.send` |
| `gmail.drafts.*` | `gmail.drafts.create`, `gmail.drafts.delete`, `gmail.drafts.list` | `gmail.messages.send`, `gmail.threads.get` |
| `gmail.*` | `gmail.drafts.create`, `gmail.messages.send`, `gmail.threads.get` | `calendar.events.create` |
| `*` | Everything | Nothing excluded |

### Algorithm

```
function matches(action_type: string, pattern: string) -> boolean:
    if pattern == "*":
        return true
    if pattern ends with ".*":
        prefix = pattern without the trailing ".*"
        return action_type == prefix OR action_type starts with (prefix + ".")
    return action_type == pattern
```

**Specificity:** Patterns are not ranked by specificity. The first-match-wins rule evaluation strategy (Section 3.1) determines which pattern applies. Policy authors control evaluation order by the declared order of action patterns in the `authorized_actions` array.

**No regex:** Action patterns use only exact match and prefix wildcard (`.*`). Regular expressions are not permitted in action patterns. This ensures matching is O(1) per pattern and deterministic across implementations.

---

## D.2 Policy Rule Evaluation (First-Match-Wins)

Given an ordered array of `ActionPattern` rules and an incoming action:

```
function evaluate_rules(rules: ActionPattern[], action_type: string, params: object) -> Decision:
    for rule in rules:                          // Declared order
        if matches(action_type, rule.pattern):
            if rule.constraints is empty:
                return rule.decision
            if all_constraints_satisfied(rule.constraints, params):
                return rule.decision
            // Constraints failed. Author preference (on_constraint_fail) wins
            // when explicitly set; attenuation is the default for ALLOW rules.
            if rule.on_constraint_fail is not null:
                return rule.on_constraint_fail
            if rule.decision == ALLOW and can_attenuate(rule.constraints, params):
                return ATTENUATE
            return DENY
    // No rule matched
    return DENY                                  // Default deny
```

### Constraint Failure Precedence

When a rule's constraints are present and not satisfied, the gate evaluates
the failure path in this order:

1. If `rule.on_constraint_fail` is explicitly set (non-null), return that
   value. The author's declaration wins over any default behavior.
2. Otherwise, if `rule.decision == ALLOW` and `can_attenuate` returns true,
   return ATTENUATE.
3. Otherwise, return DENY.

This precedence makes `on_constraint_fail` operationally meaningful for ALLOW
rules with numeric constraints. An author who writes
`decision: ALLOW, constraints: [LTE 50], on_constraint_fail: DENY` gets DENY
on constraint failure, not ATTENUATE. To explicitly request attenuation,
authors omit `on_constraint_fail` (or set it to null).

Attenuation is defined only for ALLOW rules. Setting
`on_constraint_fail: ATTENUATE` is forbidden — attenuation is determined by
the algorithm, not by author override.

The full decision matrix for ALLOW rules with non-empty constraints whose
constraints fail:

| `can_attenuate` | `on_constraint_fail` | Result |
|---|---|---|
| true  | null      | ATTENUATE |
| true  | DENY      | DENY |
| true  | ALLOW     | ALLOW |
| true  | ESCALATE  | ESCALATE |
| false | null      | DENY |
| false | DENY      | DENY |
| false | ALLOW     | ALLOW |
| false | ESCALATE  | ESCALATE |

For non-ALLOW rules (DENY, ESCALATE), the `can_attenuate` column is always
false because attenuation is defined only for ALLOW rules; only the
`on_constraint_fail or DENY` branch is reachable.

Implementations MUST reject at policy-load time:
- Rules with `on_constraint_fail` set when `constraints` is empty (the field
  would be unreachable — silent no-op).
- Rules with `on_constraint_fail == ATTENUATE`.

Implementations MUST detect run-time re-evaluation cycles in the
escalation → modify → re-evaluate path (per Section 3.8 and C.7
`requires_reevaluation`) and break them with DENY after a configurable
maximum re-entry count (RECOMMENDED: 3). Static rejection of cycle-prone
policies is RECOMMENDED but not REQUIRED — the static analysis is generally
undecidable.

### Attenuation Eligibility

A rule's failing constraints are attenuable only when ALL failing constraints
are non-strict numeric bounds on finite numeric values. If any failing
constraint is categorical, strict-inequality, operates on a non-numeric/
NaN/infinite value, or failed because of variable-resolution failure, the
rule is NOT attenuable.

```
function can_attenuate(constraints: ParameterConstraint[], params: object) -> boolean:
    any_failed = false
    for c in constraints:
        if evaluate_constraint(c, params):
            continue
        any_failed = true
        // Variable-resolution failure: not attenuable (failure is not value-out-of-bound)
        if c.value contains an unresolved variable reference at evaluation time:
            return false
        // Operator must be a non-strict numeric bound
        if c.operator not in {LESS_THAN_OR_EQUAL, GREATER_THAN_OR_EQUAL}:
            return false
        // Both sides must be finite numbers
        actual = resolve_field(c.field, params)
        if not is_finite_number(actual) or not is_finite_number(c.value):
            return false
    return any_failed
```

Strict inequalities (LESS_THAN, GREATER_THAN) are excluded because their
attenuated values are not well-defined over the reals — there is no maximum
value strictly less than X for general numeric types.

`is_finite_number(x)` is true if and only if `x` is a JSON number per RFC
8259, is not NaN, is not ±∞, and is not a boolean. Strings parseable as
numbers are non-numeric for this purpose. Booleans are explicitly excluded
to avoid the bool-as-int hazard in language runtimes where `True == 1`.

When the gate returns ATTENUATE, the failing parameter values are clamped:
- `LESS_THAN_OR_EQUAL(x)` with `value > x` → clamp to `x`
- `GREATER_THAN_OR_EQUAL(x)` with `value < x` → clamp to `x`

Clamped values MUST preserve the JSON numeric type of the constraint bound
(e.g., a constraint with integer `value: 50` produces an integer clamp; a
constraint with float `value: 50.0` produces a float clamp). This ensures
audit-record JCS canonicalization is deterministic across implementations.

If multiple failing constraints reference the same field, the clamp must
satisfy all of them. For two same-field LTE/GTE constraints with empty
intersection (e.g., `LTE(10) AND GTE(20)` on the same field), no satisfying
clamp exists; the gate returns DENY. Implementations SHOULD reject such
rules at policy-load time (this case is tractable). Detecting empty
intersections in richer constraint compositions is undecidable in general
and is not required.

The Policy Gate MUST emit an `ActionEvaluated` event with `decision: ATTENUATE`
and a non-null `attenuation` field (per `schemas/events.schema.json`)
recording the original parameter values, the clamped values, and the list of
constraints that triggered the clamping. Implementations MUST NOT substitute
clamped values without this audit record. The events schema enforces this
coupling via an `if/then` constraint.

v0.5 restricts ATTENUATE to numeric LTE/GTE clamping. Section 3.3's broader
narrative ("read-only instead of read-write, redacted data instead of full
data") describes attenuation patterns out of scope for this revision; future
revisions MAY define structured attenuation for non-numeric fields.

### Constraint Evaluation

```
function evaluate_constraint(constraint: ParameterConstraint, params: object) -> boolean:
    value = resolve_field(constraint.field, params)    // Dot-notation traversal
    target = resolve_value(constraint.value)           // May contain ${} variable refs

    switch constraint.operator:
        EQUALS:                 return value == target
        NOT_EQUALS:             return value != target
        LESS_THAN:              return value < target
        LESS_THAN_OR_EQUAL:     return value <= target
        GREATER_THAN:           return value > target
        GREATER_THAN_OR_EQUAL:  return value >= target
        IN:                     return value is in target    // target is array
        NOT_IN:                 return value is not in target
        MATCHES:                return regex_match(target, value)
        NOT_MATCHES:            return not regex_match(target, value)
        EXISTS:                 return value is not null/undefined
        NOT_EXISTS:             return value is null/undefined
```

### Variable Resolution

Fields may contain variable references:
- `${agent.task_context.user_id}` — resolved from the agent's task context
- `${agent.instance_id}` — the evaluating agent's instance ID
- `${env.current_time}` — current timestamp

Variable resolution occurs at evaluation time. Unresolvable variables cause the constraint to evaluate to `false` (fail-closed).

---

## D.3 Scope Subset Comparison

The Identity Service uses this algorithm to enforce Guarantee 3 (Authority Only Attenuates) during delegation.

A child scope C is a **subset** of a parent's delegatable scope P if and only if all of the following hold:

### Step 1: Action Coverage

Every action pattern in C must be covered by at least one pattern in P.

```
function actions_are_subset(child_actions: ActionPattern[], parent_actions: ActionPattern[]) -> boolean:
    for child_rule in child_actions:
        if not any(pattern_covers(parent.pattern, child_rule.pattern) for parent in parent_actions):
            return false
    return true

function pattern_covers(parent_pattern: string, child_pattern: string) -> boolean:
    // parent_pattern covers child_pattern if every action_type matched
    // by child_pattern would also be matched by parent_pattern.
    if parent_pattern == "*":
        return true
    if parent_pattern == child_pattern:
        return true
    if parent_pattern ends with ".*":
        parent_prefix = parent_pattern without ".*"
        if child_pattern == parent_prefix:
            return true
        if child_pattern starts with (parent_prefix + "."):
            return true
        if child_pattern ends with ".*":
            child_prefix = child_pattern without ".*"
            return child_prefix starts with (parent_prefix + ".")
                   OR child_prefix == parent_prefix
    return false
```

### Step 2: Constraint Tightness

For each action pattern present in both C and P, every constraint in C must be equal to or more restrictive than the corresponding constraint in P.

```
function constraints_are_tighter(child_constraints, parent_constraints) -> boolean:
    // Every parent constraint must have a corresponding child constraint
    // that is at least as restrictive
    for pc in parent_constraints:
        matching_child = find(cc in child_constraints where cc.field == pc.field)
        if matching_child is null:
            // Child has no constraint on this field — less restrictive
            return false
        if not is_at_least_as_restrictive(matching_child, pc):
            return false
    return true
```

Restrictiveness comparison by operator:

| Parent Operator | Child is at least as restrictive if |
|---|---|
| LESS_THAN_OR_EQUAL(X) | Child has LESS_THAN_OR_EQUAL(Y) where Y <= X |
| IN(list) | Child has IN(sublist) where sublist is a subset of list |
| NOT_IN(list) | Child has NOT_IN(superlist) where superlist is a superset of list |
| EQUALS(X) | Child has EQUALS(X) — same value only |

### Step 3: Delegation Narrowing

```
function delegation_is_subset(child_delegation, parent_delegation) -> boolean:
    if child_delegation.can_delegate and not parent_delegation.can_delegate:
        return false
    if child_delegation.max_depth > parent_delegation.max_depth - 1:
        return false   // Each delegation level reduces remaining depth by 1
    return true
```

### Step 4: Resource Constraints

Every resource constraint in C must be equal to or more restrictive than the corresponding constraint in P (same logic as parameter constraints, applied to resource patterns).

### Step 5: Output Policy

C's authorized output types must be a subset of P's authorized output types.

### Combined Check

```
function is_subset(child_scope: PolicyScope, parent_scope: PolicyScope) -> boolean:
    return actions_are_subset(child_scope.authorized_actions, parent_scope.authorized_actions)
       and constraints_are_tighter(child_scope.parameter_constraints, parent_scope.parameter_constraints)
       and delegation_is_subset(child_scope.delegation, parent_scope.delegation)
       and resource_constraints_are_subset(child_scope.resource_constraints, parent_scope.resource_constraints)
       and set(child_scope.output_policy.authorized_output_types)
           is subset of set(parent_scope.output_policy.authorized_output_types)
```

---

## D.4 Rate Limit Evaluation

### Sliding Window

```
function check_rate_limit_sliding(agent_id, action_type, rate_limit, action_log) -> boolean:
    window_start = now() - rate_limit.window
    count = count(
        entries in action_log
        where entry.agent_id == agent_id          // or type/tree depending on scope
          and entry.action_type matches rate_limit.action_pattern
          and entry.timestamp >= window_start
    )
    return count < rate_limit.max_count
```

### Fixed Window

```
function check_rate_limit_fixed(agent_id, action_type, rate_limit, action_log) -> boolean:
    window_start = floor(now(), rate_limit.window)   // e.g., start of current hour
    count = count(
        entries in action_log
        where entry.agent_id == agent_id
          and entry.action_type matches rate_limit.action_pattern
          and entry.timestamp >= window_start
    )
    return count < rate_limit.max_count
```

### Scope Resolution

| Scope | Counts actions by |
|---|---|
| INSTANCE | This specific agent instance |
| TYPE | All active instances of this agent type |
| DELEGATION_TREE | This agent and all agents in its delegation tree (ancestors + descendants) |

---

## D.5 Hash Chain Integrity

### Hash Input: Canonical Entry Serialization

The chain hash covers a **canonical serialization of the full immutable entry**, not a subset of fields. This ensures that any change to any field — decision, reason, outcome, policy_version, trust_state, causal_parent — is detectable.

The canonical form is **RFC 8785 (JSON Canonicalization Scheme, JCS)** applied to the entry object with `chain_hash` omitted. JCS defines a deterministic JSON serialization: object keys sorted lexicographically (recursively for nested objects), no whitespace between tokens, UTF-8 without byte-order mark, standard JSON string escaping, and canonical number formatting.

Audit entries SHOULD restrict field values to strings, integers, booleans, nulls, and arrays or objects of these types. This avoids edge cases in JCS floating-point number normalization. Timestamps are strings in ISO 8601 UTC form (e.g., `"2026-04-11T12:00:00Z"`).

```
function canonical_entry_string(entry: AuditEntry) -> string:
    // Produce RFC 8785 canonical JSON of the entry with chain_hash excluded.
    filtered = {field: value for each (field, value) in entry where field != "chain_hash"}
    return jcs_serialize(filtered)
```

Conforming implementations MUST produce byte-identical canonical strings for identical entry content. Earlier revisions of this specification defined a pipe-delimited key=value serialization; that form was ambiguous when field values contained `|` or `=` characters and has been replaced by JCS.

**Simplified example:**

For an entry with:
- `entry_id`: "evt-001"
- `event_type`: "ActionEvaluated"
- `agent_id`: "agent-abc"
- `decision`: "ALLOW"
- `tier`: 1
- `policy_version`: "2.1.0"
- `timestamp`: "2026-04-11T12:00:00Z"
- `causal_parent`: "evt-000"

The canonical JSON string is:
```
{"agent_id":"agent-abc","causal_parent":"evt-000","decision":"ALLOW","entry_id":"evt-001","event_type":"ActionEvaluated","policy_version":"2.1.0","tier":1,"timestamp":"2026-04-11T12:00:00Z"}
```

### Chain Verification

```
function verify_chain(entries: AuditEntry[], algorithm: HashAlgorithm, genesis: GenesisEntry) -> boolean:
    if entries is empty:
        return true
    prev_hash = genesis.signature
    for entry in entries:
        canonical = canonical_entry_string(entry)
        hash_input = prev_hash + "|" + canonical
        expected = hash(algorithm, hash_input.encode("utf-8"))
        if entry.chain_hash != expected:
            return false
        prev_hash = entry.chain_hash
    return true
```

### Why Full Entry Hashing

The previous design hashed only `{entry_id}|{event_type}|{agent_id}`. Under that scheme, an attacker with ledger access could change the `decision` from DENY to ALLOW, change `policy_version`, alter `causal_parent` links, or modify `trust_state` without breaking the chain. For a ledger positioned as tamper-evident evidence infrastructure, that gap is unacceptable. Hashing the full canonical entry ensures any field modification breaks the chain.

---

## D.6 Trust State Management

The Trust Engine is an Extension Profile component. Conforming implementations of the Extension Profile MUST maintain per-`(agent_id, capability)` trust scores in `[0.0, 1.0]` and MUST apply event-driven adjustments identically to the function below.

### Trust Model

Trust adjusts scrutiny, never authority. A score of 1.0 does not grant permissions. A score of 0.0 does not revoke them. Trust selects the level of evaluation applied within the bounds already established by the Authority Registry.

### State Container

```
TrustState {
  scores: Map<(agent_id, capability) -> score>,   // score in [0.0, 1.0]
  events: Map<(agent_id, capability) -> list<event_type>>,  // recent event history
}
```

### Event-Driven Updates

```
function update_trust(state, agent_id, capability, event_type):
    current = state.scores.get((agent_id, capability)) or TRUST_INITIAL
    if event_type == "TAMPER":
        new = 0.0
    else if event_type in { "ALLOW": +0.02, "DENY": -0.05, "ESCALATE": -0.03 }:
        new = clamp(current + delta(event_type), 0.0, 1.0)
    else:
        new = current
    state.scores[(agent_id, capability)] = new
    state.events.setdefault((agent_id, capability), []).append(event_type)
    return new
```

Design choice: trust gains slowly and loses quickly. A compromised agent that has accumulated high trust can only amplify its blast radius slowly on the way up; the governance layer can revoke it in two or three adverse events.

### Decay

```
function decay_trust(state, ticks):
    for each (agent_cap, score) in state.scores:
        for i in 1..ticks:
            if score > 0.5: score = max(0.5, score - 0.01)
            else if score < 0.5: score = min(0.5, score + 0.01)
        state.scores[agent_cap] = score
```

Scores drift toward the midpoint (0.5) with inactivity. Implementations choose the tick rate; the specification does not prescribe one.

### Scrutiny Tier Mapping

```
function scrutiny_tier(trust_score):
    if trust_score < 0.3:  return "high"
    if trust_score < 0.7:  return "normal"
    return "fast"
```

The tier label is consumed by Policy Gate Tier 3 (see D.7).

### Initial Conditions

- New `(agent, capability)` pairs start at `TRUST_INITIAL = 0.5` (neutral).
- Trust state is durable across sessions. Implementations MUST persist `scores` and SHOULD persist `events`.
- Trust state is a governance-layer artifact and MUST be agent-inaccessible.

---

## D.7 Policy Gate Tier 3 — Behavioral Pattern Analysis

Tier 3 is an Extension Profile component. Conforming implementations of the Extension Profile MUST run Tier 3 only after Tier 1 (deterministic rule check) and Tier 2 (parameter inspection) have not produced a terminal decision, and MUST produce decisions that are deterministic functions of the declared inputs.

### Inputs and Decision Surface

```
function tier3_evaluate(agent_id, action_type, capability, trust_state) -> Decision:
    // Pre-condition: Tier 1 and Tier 2 produced neither ALLOW nor DENY.
    //
    // Returns: Decision { decision, reason, tier: 3, trust, scrutiny }
    // where decision is one of ALLOW, DENY, ESCALATE, ATTENUATE.

    trust = get_trust(trust_state, agent_id, capability)
    scrutiny = scrutiny_tier(trust)
    escalate_count = recent_event_count(trust_state, agent_id, capability,
                                         "ESCALATE", window = 10)

    // Rule 1: Behavioral escalation pattern overrides trust.
    if escalate_count > 3:
        return { decision: ESCALATE, reason: "escalation_pattern", ... }

    mutating = is_mutating_action(action_type)

    // Rule 2: Low trust plus a mutating action → attenuate to read-only.
    if scrutiny == "high" and mutating:
        return { decision: ATTENUATE, reason: "low_trust_mutating", ... }

    // Rule 3: Low trust plus read-only action → allow with logging.
    if scrutiny == "high" and not mutating:
        return { decision: ALLOW, reason: "low_trust_readonly", ... }

    // Rule 4: Normal trust → allow with audit flag.
    if scrutiny == "normal":
        return { decision: ALLOW, audit_flag: true, ... }

    // Rule 5: Fast path.
    return { decision: ALLOW, reason: "fast_path", ... }
```

### Mutating Action Detection

An action is mutating if any dot-delimited segment of its `action_type` matches a verb in:

```
{ create, update, delete, send, execute, publish, transfer, grant }
```

Implementations MAY extend the verb set. Extensions to this list MUST be documented.

### Behavioral Signals

Tier 3 reads only two signals from trust state:

1. **Trust score** for `(agent_id, capability)`.
2. **Recent ESCALATE count** over the last 10 events for `(agent_id, capability)`.

This specification does not define additional behavioral signals for Tier 3. Extensions MAY add signals, provided the decision function remains deterministic and signal inputs are auditable.

### Why Deterministic

A Tier 3 that uses machine-learned classifiers, probabilistic scoring, or opaque heuristics produces decisions that cannot be reliably reproduced in an audit. The specification requires Tier 3 to be deterministic so that a decision recorded in the Audit Ledger can be re-derived by an auditor with access to the same inputs.

---

## D.8 Output Evaluator — Scope Alignment

The Output Evaluator is an Extension Profile component. Two alignment methods are defined. Conforming implementations of the Extension Profile MUST support at least one and MAY support both.

Both methods run the same uniform checks before alignment scoring:

- **Credential-pattern detection:** regex match against known secret shapes (API keys, bearer tokens, private-key blocks, inline passwords).
- **Out-of-scope capability reference:** capability-shaped tokens in the output that are not within the agent's granted capability set.

### Common Return Shape

```
{
  scope_alignment: float in [0.0, 1.0],
  findings: list of { type, detail, severity in {critical, high, medium} },
  recommendation: "PASS" | "FLAG" | "BLOCK",
  method: "keyword_overlap" | "slot_match"
}
```

Any finding of severity `critical` (e.g., credential leak) MUST drive `scope_alignment` to `0.0` and `recommendation` to `BLOCK`.

### D.8.1 Keyword Overlap

```
function evaluate_keyword_overlap(output, task_keywords, granted_capabilities):
    findings = detect_credentials(output)
    findings += detect_out_of_scope(output, granted_capabilities)

    if task_keywords is empty:
        alignment = 1.0  // no declared constraint
    else:
        matched = count(kw for kw in task_keywords where kw appears in output)
        alignment = matched / len(task_keywords)

    alignment = 0.0 if any finding.severity == critical
    alignment -= 0.2 * count(finding.severity == high)
    alignment = clamp(alignment, 0.0, 1.0)

    return { scope_alignment, findings, recommendation, method: "keyword_overlap" }
```

Keyword overlap is the baseline method. It requires no structured task declaration and works with any agent framework that can tag an action with a short list of task-defining terms.

### D.8.2 Slot Match

```
TaskDeclaration {
  required_topics: list<string>,    // output MUST mention each
  forbidden_topics: list<string>,   // output MUST NOT mention any
  allowed_resources: list<string>,  // capability-shaped tokens the task is scoped to
}
```

```
function evaluate_slot_match(output, task_declaration, granted_capabilities):
    findings = detect_credentials(output)
    findings += detect_out_of_scope(output, granted_capabilities)

    for each topic in task_declaration.required_topics:
        if topic not in output:
            findings += { type: "missing_required_topic", severity: "medium" }

    for each topic in task_declaration.forbidden_topics:
        if topic in output:
            findings += { type: "forbidden_topic_mention", severity: "high" }

    if task_declaration.allowed_resources is non-empty:
        for each capability-token in output:
            if token is not in allowed_resources (nor a descendant):
                findings += { type: "resource_outside_task_scope", severity: "high" }

    alignment = 0.0 if any finding.severity == critical
    else alignment = clamp(1.0 - 0.3 * high_count - 0.1 * medium_count, 0.0, 1.0)

    return { scope_alignment, findings, recommendation, method: "slot_match" }
```

Slot match requires the calling agent framework to produce a structured `TaskDeclaration` at action time. This is a heavier integration requirement than keyword overlap, but it produces richer findings and catches resource-scope violations that keyword overlap cannot see.

### Method Selection

Implementations MAY run both methods and combine findings. A call that supplies only `task_keywords` uses D.8.1. A call that supplies a `TaskDeclaration` uses D.8.2. A call that supplies both MAY use either or both.

### What the Evaluator Does Not Do

- It does not run a large-language-model classifier against the output. Any ML-based alignment mechanism is an Extension to this Extension Profile.
- It does not guarantee detection of injection-crafted outputs. Prompt-injection defense at the model layer is out of scope (see Section 1.3).
- It does not enforce blocking. The `recommendation` field is advisory; the Escalation Router or a downstream enforcement policy decides whether a `BLOCK` recommendation halts delivery.
