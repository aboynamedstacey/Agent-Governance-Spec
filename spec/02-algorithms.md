# Appendix D: Canonical Algorithms

This appendix defines the reference algorithms for action pattern matching, policy rule evaluation, and scope subset comparison. These algorithms are **normative**, and conforming implementations MUST produce identical results for identical inputs.

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
`on_constraint_fail: ATTENUATE` is forbidden, because attenuation is determined by
the algorithm and not by author override.

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
  would be unreachable, a silent no-op).
- Rules with `on_constraint_fail == ATTENUATE`.

Implementations MUST detect run-time re-evaluation cycles in the
escalation → modify → re-evaluate path (per Section 3.8 and C.7
`requires_reevaluation`) and break them with DENY after a configurable
maximum re-entry count (RECOMMENDED: 3). Static rejection of cycle-prone
policies is RECOMMENDED but not REQUIRED, since the static analysis is generally
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
attenuated values are not well-defined over the reals, since there is no maximum
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
- `${agent.task_context.user_id}` resolves from the agent's task context
- `${agent.instance_id}` is the evaluating agent's instance ID
- `${env.current_time}` is the current timestamp

Variable resolution occurs at evaluation time. Unresolvable variables cause the constraint to evaluate to `false` (fail-closed).

---

## D.3 Scope Subset Comparison

Delegation MUST preserve effective authority under ordered, first-match rules.
Pattern coverage alone is insufficient: a DENY exception can be hidden by a
broader ALLOW rule, and an identical action pattern can carry a different cap.

### Rule refinement

For every action namespace region, select the first matching rule in each
policy. A missing child rule or an unconditional child DENY narrows authority.
Otherwise the parent MUST have a matching rule, and the child MUST preserve:

- The parent's decision, escalation configuration, and `on_constraint_fail`.
- Every rule-local parameter constraint, identically or more restrictively.
- Identical constraint predicates when the failure branch is ALLOW or ESCALATE;
  changing those predicates could widen the permissive branch.

The reference algorithm `rules_are_subset` partitions exact/prefix patterns
using every pattern's base action and one fresh descendant per base, plus a
fresh root action. The fresh segment appears in no policy pattern. First-match
rule selection is constant within each resulting region, so checking these
representatives covers the namespace, including exceptions and rule order.
This construction applies only to exact names, `prefix.*`, and `*`.
Names comprise dot-delimited nonempty ASCII letters, digits, underscores, or
hyphens. Unknown decisions, unsupported patterns, and missing decisions fail
closed. ATTENUATE is a computed outcome, not a delegatable rule decision.

This is a conservative proof procedure, not a complete implication solver.
It may reject a safe but non-comparable policy. Implementers MUST NOT fall back
to pattern-only authorization when proof fails. `actions_are_subset` remains a
pattern utility; it MUST NOT be used as the identity service's authorization check.

### Constraint implication

For every parent constraint, a corresponding child constraint MUST prove an
equal or narrower accepted value set. Same-operator numeric bounds tighten in
the natural direction; IN lists shrink; NOT_IN lists grow; EQUALS values and
uninterpreted predicates must remain identical. EQUALS may refine LTE, GTE, or
IN when its literal value satisfies the parent predicate. Numeric bounds use
finite JSON numbers and exclude booleans. Unsupported implications fail closed.

Identity-relative `${...}` values MUST be resolved and bound to immutable
literals before delegation comparison. Identical expressions can resolve to
different values for parent and child and are not evidence of narrowing.

### Remaining scope fields

- Scope-level parameter constraints use the same implication check.
- `can_delegate` cannot become true when false in the parent. Child remaining
  depth is at most `max(0, parent.max_depth - 1)`; actual spawning additionally
  requires parent `can_delegate=true` and remaining depth greater than zero.
- Resource permissions form an allowlist. An empty list permits no explicit
  resource access. Each child resource pattern must be covered by a parent
  pattern with the **same access operation**, classification ceiling, and
  conditions. READ, WRITE, DELETE, and EXECUTE do not imply each other.
  Classification and conditions require equality until an implication model
  is specified. Tool parameters may carry additional resource restrictions.
- Child output types must be a subset of parent output types. Other output
  controls must be preserved exactly until a refinement relation is defined.

### Identity-service obligations

Both the parent's actual authority and any explicit delegatable envelope MUST
bound a child's scope. Execution rules MUST be the validated rules, not a
separately supplied unchecked list. Grant and identity inputs MUST be copied or
made immutable. A terminated or expired parent or ancestor cannot spawn.
Expiration is exclusive: at `now >= expires_at`, authority is invalid.
Delegatable envelopes confer no authority absent from the current identity;
every subsequent spawn repeats both checks and decrements remaining depth.

The `delegation_semantics` vectors cover decision substitution, cap removal,
ordered exceptions, permissive failure paths, and unresolved identity variables.

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

The chain hash covers a **canonical serialization of the full immutable entry**, not a subset of fields. This ensures that any change to any field, whether decision, reason, outcome, policy_version, trust_state, or causal_parent, is detectable.

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

The Trust Engine is an Extension Profile. Scores are per `(agent_id, capability)`
in `[0, 1]`, initially `0.5`. They route scrutiny within existing authority and
MUST NOT enlarge permissions. The constants below are deterministic reference
parameters, not empirically calibrated estimates of reliability.

### Verified outcomes, not permission decisions

| Input | Score effect |
|---|---|
| ALLOW, DENY, ESCALATE, ATTENUATE | None |
| VERIFIED_SUCCESS | +0.02, capped at 1.0 |
| VERIFIED_FAILURE | -0.05, floored at 0.0 |
| TAMPER | 0.0 and persistent quarantine |

A successful API response is not by itself VERIFIED_SUCCESS. An authenticated
observer outside the agent's control must assess the completed action against
a declared, versioned criterion (for example, correct recipient and correct
record updates). The immutable evidence record MUST identify `evidence_id`,
`action_id`, `observer_id`, `criterion`, `agent_id`, `capability`, and `outcome`.
The subject, capability, and outcome MUST match the requested score update.
The observer's authentication and access to the outcome record are deployment
obligations; the Python function validates evidence structure, not authenticity.

Replaying identical evidence is idempotent. Reusing an evidence ID with changed
content is rejected. A new evidence ID cannot credit or debit the same action
and outcome again. Store evidence references and deduplication state durably
alongside scores. Serialize updates per subject/capability. Permission events
must neither change scores nor displace verified outcomes from the history.

Tamper quarantine survives successful outcomes and inactivity. Clearing it
requires a separate authenticated incident-resolution process and audit entry;
the reference implementation deliberately supplies no automatic reset.

### Decay and scrutiny

Each declared inactivity tick reduces scores above 0.5 by 0.01 toward 0.5.
Scores at or below 0.5 never increase through inactivity. Operators MUST declare
the tick duration; portability comparisons must supply the same tick inputs.

Scores below 0.3 select high scrutiny; below 0.7 select normal scrutiny;
otherwise select fast scrutiny. These labels are not permissions. Calibration,
observer quality, task difficulty, and resistance to easy-task farming remain
requirements for deployment validation. High-impact actions SHOULD retain
mandatory review regardless of historical score.

---

## D.7 Policy Gate Tier 3: Scrutiny Routing

Tier 3 MUST receive affirmative authority confirmation from Tiers 1-2 and an
explicit `action_effect` (`read` or `write`) from a trusted tool registry.
Unknown authority or effects produce ESCALATE. A name such as `read` is not
proof of an operation's effects. `is_mutating_action` is informational only.
An unresolved authority decision MUST NOT become ALLOW because trust is high.

Apply these rules in order:

1. Quarantined agent/capability: DENY.
2. Authority not confirmed or effect metadata absent/unknown: ESCALATE.
3. More than three VERIFIED_FAILURE events among the ten most recent verified
   outcomes, or high scrutiny with a write operation: ESCALATE.
4. Otherwise: ALLOW within the already-established authority, with an audit flag.

There is no automatic conversion of a write into a read. D.2 numeric attenuation
remains available; other transformations need separately defined semantics.
Appropriate human escalation is not an adverse outcome and carries no penalty.

---

## D.8 Output Evaluator: Lexical Checks and Delivery Control

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
  method: "keyword_overlap" | "slot_match",
  assessment_scope: "lexical_only",
  semantic_assurance: false
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
- It does not establish semantic scope alignment, factual accuracy, instruction
  integrity, or correctness. Keyword stuffing may receive PASS.
- It does not release outputs. The delivery adapter MUST apply the gate below.

### D.8.3 Delivery gate

The reference `output_delivery_decision` returns BLOCK for a BLOCK assessment;
REVIEW for missing/unknown assessments, any findings, FLAG, or any high-risk
channel; and DELIVER only for a clean lexical PASS on an explicitly low-risk
channel. Map BLOCK to SUPPRESS, REVIEW to ESCALATE, and DELIVER to RELEASE in
`OutputEvaluationResponse`. A lexical PASS alone MUST NOT release high-risk
outputs. Any downstream human or semantic review must be authenticated, audited,
and bound to the exact output digest, task, policy, and audience; revisions
invalidate that approval. The reference gate has no caller-supplied bypass.

Task declarations and channel risk classification MUST originate from trusted
authority configuration. Agents cannot remove required topics or label their
own customer-facing outputs low risk. Scores retain the `scope_alignment` name
for compatibility but measure only lexical checks, never semantic assurance.
The adapter records assessment scope and evidence limits in its audit record.
