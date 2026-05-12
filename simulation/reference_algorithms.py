"""
Agent Governance Specification — Reference Algorithm Implementation

Complete canonical implementations of every algorithm defined in Appendix D.
These are normative: conforming implementations MUST produce identical
results for identical inputs.

Coverage:
  D.1  Action pattern matching
  D.2  Policy rule evaluation (first-match-wins) with full constraint
       evaluation including MATCHES/NOT_MATCHES and variable resolution
  D.3  Full scope subset comparison (action coverage, constraint tightness,
       delegation narrowing, resource constraints, output policy)
  D.4  Rate limit evaluation (sliding window, fixed window, scope resolution)
  D.5  Hash chain integrity verification
  D.6  Trust state management (score updates, decay, scrutiny tier)
  D.7  Policy Gate Tier 3 behavioral pattern analysis
  D.8  Output scope alignment (D.8.1 keyword overlap, D.8.2 slot match)

Run: python3 reference_algorithms.py
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════════
# D.1 Action Pattern Matching
# ═══════════════════════════════════════════════════════════════════

def matches(action_type: str, pattern: str) -> bool:
    """
    Determine whether an action_type matches a pattern.

    Patterns:
      "gmail.drafts.create"  — exact match only
      "gmail.drafts.*"       — matches gmail.drafts and any gmail.drafts.X
      "gmail.*"              — matches gmail and any gmail.X.Y.Z
      "*"                    — matches everything

    No regex. Only exact match and prefix wildcard.
    """
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return action_type == prefix or action_type.startswith(prefix + ".")
    return action_type == pattern


def pattern_covers(parent_pattern: str, child_pattern: str) -> bool:
    """
    Determine whether every action_type matched by child_pattern
    would also be matched by parent_pattern.

    Used in scope subset comparison (D.3).
    """
    if parent_pattern == "*":
        return True
    if parent_pattern == child_pattern:
        return True
    if parent_pattern.endswith(".*"):
        parent_prefix = parent_pattern[:-2]
        if child_pattern == parent_prefix:
            return True
        if child_pattern.startswith(parent_prefix + "."):
            return True
        if child_pattern.endswith(".*"):
            child_prefix = child_pattern[:-2]
            return (child_prefix == parent_prefix or
                    child_prefix.startswith(parent_prefix + "."))
    return False


# ═══════════════════════════════════════════════════════════════════
# D.2 Constraint Evaluation with Variable Resolution
# ═══════════════════════════════════════════════════════════════════

def resolve_field(field_path: str, params: dict) -> any:
    """Dot-notation field traversal into nested dicts."""
    parts = field_path.split(".")
    current = params
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def resolve_value(value, context: dict) -> any:
    """
    Resolve variable references in constraint values.

    Variables:
      ${agent.task_context.user_id}  — from agent identity context
      ${agent.instance_id}           — agent's instance ID
      ${env.current_time}            — current ISO timestamp

    If value is a string containing ${...}, resolve it.
    If value is a list, resolve each element.
    Otherwise return as-is.
    """
    if isinstance(value, str) and "${" in value:
        var_match = re.fullmatch(r'\$\{(.+)\}', value)
        if var_match:
            var_path = var_match.group(1)
            if var_path == "env.current_time":
                return datetime.now().isoformat()
            resolved = resolve_field(var_path, context)
            if resolved is None:
                return None  # Unresolvable — will cause constraint to fail-closed
            return resolved
        return value
    if isinstance(value, list):
        return [resolve_value(v, context) for v in value]
    return value


def evaluate_constraint(field: str, operator: str, value, params: dict,
                        context: dict = None) -> bool:
    """
    Evaluate a single constraint against action parameters.
    Implements all 12 operators from Appendix C.1 ConstraintOperator.
    """
    context = context or {}
    actual = resolve_field(field, params)
    target = resolve_value(value, context)

    # Unresolvable variable → fail-closed
    if target is None and "${" in str(value):
        return False

    if operator == "EQUALS":
        return actual == target
    elif operator == "NOT_EQUALS":
        return actual != target
    elif operator == "LESS_THAN":
        return actual is not None and target is not None and actual < target
    elif operator == "LESS_THAN_OR_EQUAL":
        return actual is not None and target is not None and actual <= target
    elif operator == "GREATER_THAN":
        return actual is not None and target is not None and actual > target
    elif operator == "GREATER_THAN_OR_EQUAL":
        return actual is not None and target is not None and actual >= target
    elif operator == "IN":
        return target is not None and actual in target
    elif operator == "NOT_IN":
        return target is not None and actual not in target
    elif operator == "MATCHES":
        if actual is None or target is None:
            return False
        try:
            return bool(re.search(target, str(actual)))
        except re.error:
            return False  # Invalid regex — fail-closed
    elif operator == "NOT_MATCHES":
        if actual is None or target is None:
            return True  # No value to match against — constraint satisfied
        try:
            return not bool(re.search(target, str(actual)))
        except re.error:
            return False  # Invalid regex — fail-closed
    elif operator == "EXISTS":
        return actual is not None
    elif operator == "NOT_EXISTS":
        return actual is None
    else:
        return False  # Unknown operator — fail-closed


# ═══════════════════════════════════════════════════════════════════
# D.2 Policy Rule Evaluation (First-Match-Wins)
# ═══════════════════════════════════════════════════════════════════

def is_finite_number(x) -> bool:
    """
    True iff x is a finite numeric per D.2 Attenuation Eligibility:
    JSON number, not NaN, not ±∞, not a boolean. Strings are non-numeric.
    """
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return True
    if isinstance(x, float):
        import math
        return math.isfinite(x)
    return False


def can_attenuate(constraints: list[dict], params: dict, context: dict = None) -> bool:
    """
    D.2 Attenuation Eligibility (v0.5.0-draft).

    Returns True iff at least one constraint failed AND every failing
    constraint is a non-strict numeric bound (LTE/GTE) on finite numeric
    values. Variable-resolution failures, categorical operators, strict
    inequalities, and non-finite-numeric values disqualify the rule.
    """
    context = context or {}
    any_failed = False
    for c in constraints:
        # Detect variable-resolution failure: try to resolve the value first.
        target = resolve_value(c["value"], context)
        var_unresolved = target is None and "${" in str(c["value"])

        satisfied = evaluate_constraint(
            c["field"], c["operator"], c["value"], params, context
        )
        if satisfied:
            continue

        any_failed = True

        # Variable-resolution failure: not attenuable (failure is not value-out-of-bound).
        if var_unresolved:
            return False

        # Operator must be a non-strict numeric bound.
        if c["operator"] not in ("LESS_THAN_OR_EQUAL", "GREATER_THAN_OR_EQUAL"):
            return False

        # Both sides must be finite numbers.
        actual = resolve_field(c["field"], params)
        if not is_finite_number(actual) or not is_finite_number(target):
            return False

    return any_failed


def evaluate_rules(rules: list[dict], action_type: str, params: dict,
                   context: dict = None) -> tuple[str, int, str | None]:
    """
    Evaluate action against ordered rules using first-match-wins.
    Returns (decision, tier, reason_code).

    Constraint failure precedence (D.2 v0.5.0-draft):
    1. on_constraint_fail (when explicitly set, non-null) wins
    2. ATTENUATE for ALLOW rules with attenuable failures
    3. DENY otherwise

    Context is the variable resolution context (agent identity, env).
    """
    context = context or {}

    for rule in rules:
        if not matches(action_type, rule["pattern"]):
            continue

        constraints = rule.get("constraints", [])
        ocf = rule.get("on_constraint_fail")

        if not constraints:
            tier = 1
            if rule["decision"] == "DENY":
                return "DENY", tier, "POLICY_MATCH_DENY"
            elif rule["decision"] == "ESCALATE":
                return "ESCALATE", tier, "ESCALATION_REQUIRED"
            else:
                return rule["decision"], tier, None

        # Has constraints — evaluate at Tier 2
        all_satisfied = all(
            evaluate_constraint(c["field"], c["operator"], c["value"], params, context)
            for c in constraints
        )

        if all_satisfied:
            return rule["decision"], 2, None

        # Constraints failed. Apply precedence.
        if ocf is not None:
            # Author-declared decision wins. Reason depends on the routed value.
            reason = {
                "ALLOW": None,
                "DENY": "CONSTRAINT_VIOLATION",
                "ESCALATE": "ESCALATION_REQUIRED",
            }.get(ocf, "CONSTRAINT_VIOLATION")
            return ocf, 2, reason

        if rule["decision"] == "ALLOW" and can_attenuate(constraints, params, context):
            return "ATTENUATE", 2, "CONSTRAINT_VIOLATION"

        return "DENY", 2, "CONSTRAINT_VIOLATION"

    return "DENY", 1, "UNMATCHED_ACTION"


def validate_action_pattern(rule: dict) -> None:
    """
    Policy-load-time validation per D.2 v0.5.0-draft.
    Raises ValueError on malformed rules.
    """
    constraints = rule.get("constraints") or []
    ocf = rule.get("on_constraint_fail")

    if ocf is not None and not constraints:
        raise ValueError(
            f"Rule pattern {rule.get('pattern')!r}: on_constraint_fail is set "
            f"but constraints is empty (silent no-op forbidden)."
        )
    if ocf == "ATTENUATE":
        raise ValueError(
            f"Rule pattern {rule.get('pattern')!r}: on_constraint_fail must not "
            f"be ATTENUATE (attenuation is algorithmic, not author-controlled)."
        )


# ═══════════════════════════════════════════════════════════════════
# D.3 Full Scope Subset Comparison
# ═══════════════════════════════════════════════════════════════════

def actions_are_subset(child_patterns: list[str], parent_patterns: list[str]) -> bool:
    """Step 1: Every child action pattern must be covered by a parent pattern."""
    for child_pat in child_patterns:
        if not any(pattern_covers(pp, child_pat) for pp in parent_patterns):
            return False
    return True


def constraint_is_at_least_as_restrictive(child: dict, parent: dict) -> bool:
    """
    Step 2: Determine whether a child constraint is at least as restrictive
    as the corresponding parent constraint on the same field.
    """
    if child["field"] != parent["field"]:
        return False

    cop = child["operator"]
    pop = parent["operator"]
    cv = child["value"]
    pv = parent["value"]

    # Same operator — compare values
    if cop == pop:
        if cop in ("LESS_THAN", "LESS_THAN_OR_EQUAL"):
            return cv <= pv  # Lower ceiling = more restrictive
        if cop in ("GREATER_THAN", "GREATER_THAN_OR_EQUAL"):
            return cv >= pv  # Higher floor = more restrictive
        if cop == "IN":
            return set(cv).issubset(set(pv))  # Smaller list = more restrictive
        if cop == "NOT_IN":
            return set(cv).issuperset(set(pv))  # Larger blocklist = more restrictive
        if cop == "EQUALS":
            return cv == pv  # Must be same value
        if cop == "MATCHES":
            return cv == pv  # Regex equivalence is undecidable; require exact match
        return cv == pv  # Default: must be identical

    # Cross-operator: EQUALS is more restrictive than range operators
    if cop == "EQUALS":
        if pop == "LESS_THAN_OR_EQUAL":
            return cv <= pv
        if pop == "GREATER_THAN_OR_EQUAL":
            return cv >= pv
        if pop == "IN":
            return cv in pv
    return False


def constraints_are_tighter(child_constraints: list[dict],
                            parent_constraints: list[dict]) -> bool:
    """
    Step 2: For every parent constraint, the child must have a corresponding
    constraint that is at least as restrictive.
    """
    for pc in parent_constraints:
        matching = [cc for cc in child_constraints if cc["field"] == pc["field"]]
        if not matching:
            return False  # Child has no constraint on this field — less restrictive
        if not any(constraint_is_at_least_as_restrictive(cc, pc) for cc in matching):
            return False
    return True


def delegation_is_subset(child_delegation: dict, parent_delegation: dict) -> bool:
    """Step 3: Child delegation must be equal or more restrictive than parent."""
    if child_delegation.get("can_delegate", False) and not parent_delegation.get("can_delegate", False):
        return False
    child_depth = child_delegation.get("max_depth", 0)
    parent_depth = parent_delegation.get("max_depth", 0)
    if child_depth > max(0, parent_depth - 1):
        return False
    return True


def resource_constraints_are_subset(child_resources: list[dict],
                                     parent_resources: list[dict]) -> bool:
    """Step 4: Every child resource constraint must be covered by a parent constraint."""
    if not child_resources:
        return True
    if not parent_resources:
        return len(child_resources) == 0

    access_order = {"ACCESS_READ": 0, "ACCESS_WRITE": 1, "ACCESS_DELETE": 2, "ACCESS_EXECUTE": 3}

    for cr in child_resources:
        covered = False
        for pr in parent_resources:
            if matches(cr.get("resource_pattern", ""), pr.get("resource_pattern", "")):
                child_level = access_order.get(cr.get("access_level", ""), 99)
                parent_level = access_order.get(pr.get("access_level", ""), 99)
                if child_level <= parent_level:
                    covered = True
                    break
        if not covered:
            return False
    return True


def output_types_are_subset(child_types: list[str], parent_types: list[str]) -> bool:
    """Step 5: Child output types must be a subset of parent output types."""
    return set(child_types).issubset(set(parent_types))


def is_subset(child_scope: dict, parent_scope: dict) -> bool:
    """
    Full scope subset comparison as defined in Appendix D.3.
    All five steps must pass.
    """
    # Step 1: Action coverage
    child_actions = [r["pattern"] for r in child_scope.get("authorized_actions", [])]
    parent_actions = [r["pattern"] for r in parent_scope.get("authorized_actions", [])]
    if not actions_are_subset(child_actions, parent_actions):
        return False

    # Step 2: Constraint tightness
    child_constraints = child_scope.get("parameter_constraints", [])
    parent_constraints = parent_scope.get("parameter_constraints", [])
    if not constraints_are_tighter(child_constraints, parent_constraints):
        return False

    # Step 3: Delegation narrowing
    child_deleg = child_scope.get("delegation", {})
    parent_deleg = parent_scope.get("delegation", {})
    if not delegation_is_subset(child_deleg, parent_deleg):
        return False

    # Step 4: Resource constraints
    child_resources = child_scope.get("resource_constraints", [])
    parent_resources = parent_scope.get("resource_constraints", [])
    if not resource_constraints_are_subset(child_resources, parent_resources):
        return False

    # Step 5: Output policy
    child_output = child_scope.get("output_policy", {}).get("authorized_output_types", [])
    parent_output = parent_scope.get("output_policy", {}).get("authorized_output_types", [])
    if child_output:
        # Child claims output types — parent must authorize at least those types.
        # Empty parent list means no output types authorized.
        if not parent_output:
            return False
        if not output_types_are_subset(child_output, parent_output):
            return False

    return True


# ═══════════════════════════════════════════════════════════════════
# D.4 Rate Limit Evaluation
# ═══════════════════════════════════════════════════════════════════

def parse_duration(duration_str: str) -> timedelta:
    """Parse simple duration strings: '1h', '30m', '8h', '1d'."""
    if duration_str.endswith("h"):
        return timedelta(hours=int(duration_str[:-1]))
    if duration_str.endswith("m"):
        return timedelta(minutes=int(duration_str[:-1]))
    if duration_str.endswith("d"):
        return timedelta(days=int(duration_str[:-1]))
    if duration_str.endswith("s"):
        return timedelta(seconds=int(duration_str[:-1]))
    raise ValueError(f"Unknown duration format: {duration_str}")


def check_rate_limit_sliding(action_log: list[dict], agent_id: str,
                              action_type: str, rate_limit: dict,
                              now: datetime = None) -> bool:
    """
    Sliding window rate limit check.
    Returns True if within limit, False if exceeded.
    """
    now = now or datetime.now()
    window = parse_duration(rate_limit["window"])
    window_start = now - window
    scope = rate_limit.get("scope", "INSTANCE")

    count = 0
    for entry in action_log:
        if entry["timestamp"] < window_start:
            continue
        if not matches(entry.get("action_type", ""), rate_limit["action_pattern"]):
            continue
        if scope == "INSTANCE" and entry.get("agent_id") != agent_id:
            continue
        if scope == "TYPE" and entry.get("agent_type") != rate_limit.get("agent_type"):
            continue
        # DELEGATION_TREE requires lineage check — agent_id is in the tree
        if scope == "DELEGATION_TREE":
            tree_ids = entry.get("delegation_tree_ids", [])
            if agent_id not in tree_ids and entry.get("agent_id") != agent_id:
                continue
        count += 1

    return count < rate_limit["max_count"]


def check_rate_limit_fixed(action_log: list[dict], agent_id: str,
                            action_type: str, rate_limit: dict,
                            now: datetime = None) -> bool:
    """
    Fixed window rate limit check. Window resets at interval boundaries.
    Returns True if within limit, False if exceeded.
    """
    now = now or datetime.now()
    window = parse_duration(rate_limit["window"])
    window_seconds = window.total_seconds()

    # Calculate current window start (floor to window boundary)
    epoch = datetime(2000, 1, 1)
    elapsed = (now - epoch).total_seconds()
    window_num = int(elapsed // window_seconds)
    window_start = epoch + timedelta(seconds=window_num * window_seconds)

    scope = rate_limit.get("scope", "INSTANCE")

    count = 0
    for entry in action_log:
        if entry["timestamp"] < window_start:
            continue
        if not matches(entry.get("action_type", ""), rate_limit["action_pattern"]):
            continue
        if scope == "INSTANCE" and entry.get("agent_id") != agent_id:
            continue
        count += 1

    return count < rate_limit["max_count"]


# ═══════════════════════════════════════════════════════════════════
# D.5 Hash Chain Integrity Verification
# ═══════════════════════════════════════════════════════════════════

SUPPORTED_ALGORITHMS = {"SHA256": hashlib.sha256, "SHA384": hashlib.sha384, "SHA512": hashlib.sha512}


def canonical_value(value) -> str:
    """Serialize a value to its canonical string form."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[" + ",".join(canonical_value(v) for v in value) + "]"
    if isinstance(value, dict):
        sorted_keys = sorted(value.keys())
        return "{" + ",".join(f"{k}={canonical_value(value[k])}" for k in sorted_keys) + "}"
    return str(value)


def canonical_entry_string(entry: dict) -> str:
    """
    Produce a canonical JSON serialization of an audit entry for hashing.
    Excludes chain_hash. Follows RFC 8785 (JSON Canonicalization Scheme, JCS)
    principles: lexicographically sorted keys (recursively), no whitespace,
    UTF-8, standard JSON escaping.

    Python's json.dumps with sort_keys=True, ensure_ascii=False, and compact
    separators produces RFC 8785-equivalent output for audit entries whose
    values are strings, integers, booleans, nulls, or arrays/objects of these.
    Full RFC 8785 number normalization (ES6 ToString for floats) is not
    required by this specification; audit entries should use integer numeric
    values to avoid the edge case.

    This ensures any field change — decision, reason, outcome, policy_version,
    trust_state, causal_parent — breaks the chain.
    """
    filtered = {k: v for k, v in entry.items() if k != "chain_hash"}
    return json.dumps(
        filtered,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def hash_entry(algorithm: str, prev_hash: str, entry: dict) -> str:
    """Compute the chain hash for a single audit entry using full canonical serialization."""
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    hash_fn = SUPPORTED_ALGORITHMS[algorithm]
    canonical = canonical_entry_string(entry)
    chain_input = f"{prev_hash}|{canonical}"
    return hash_fn(chain_input.encode("utf-8")).hexdigest()


def _hash_simple(algorithm: str, input_str: str) -> str:
    """Hash a simple string. Used for genesis signature."""
    hash_fn = SUPPORTED_ALGORITHMS[algorithm]
    return hash_fn(input_str.encode("utf-8")).hexdigest()


def create_genesis(algorithm: str, initialized_by: str, chain_id: str) -> dict:
    """Create the genesis entry that anchors the hash chain."""
    genesis_id = f"genesis-{chain_id}"
    sig_input = f"NULL|{genesis_id}|GENESIS|{initialized_by}"
    signature = _hash_simple(algorithm, sig_input)
    return {
        "entry_id": genesis_id,
        "timestamp": datetime.now().isoformat(),
        "initialized_by": initialized_by,
        "algorithm": algorithm,
        "chain_id": chain_id,
        "signature": signature,
    }


def append_to_chain(chain: list[dict], algorithm: str, genesis: dict,
                     entry_id: str, event_type: str, agent_id: str,
                     **extra_fields) -> dict:
    """Append an entry to the hash chain. Extra fields are included in the canonical hash."""
    if not chain:
        prev_hash = genesis["signature"]
    else:
        prev_hash = chain[-1]["chain_hash"]

    entry = {
        "entry_id": entry_id,
        "event_type": event_type,
        "agent_id": agent_id,
        "timestamp": datetime.now().isoformat(),
        **extra_fields,
    }
    entry["chain_hash"] = hash_entry(algorithm, prev_hash, entry)
    chain.append(entry)
    return entry


def verify_chain(chain: list[dict], algorithm: str, genesis: dict) -> tuple[bool, str]:
    """
    Verify hash chain integrity using full canonical entry serialization.
    Returns (is_valid, error_message).
    """
    if not chain:
        return True, ""

    prev_hash = genesis["signature"]
    for i, entry in enumerate(chain):
        expected = hash_entry(algorithm, prev_hash, entry)
        if entry["chain_hash"] != expected:
            return False, f"Chain broken at entry {i} ({entry['entry_id']}): expected {expected[:16]}..., got {entry['chain_hash'][:16]}..."
        prev_hash = entry["chain_hash"]

    return True, ""


# ═══════════════════════════════════════════════════════════════════
# D.6 Trust State Management
# ═══════════════════════════════════════════════════════════════════
#
# Per-(agent_id, capability) trust scores in [0.0, 1.0]. Trust adjusts
# scrutiny level — it never creates new authority or expands scope. A
# deceived or compromised agent cannot gain permissions through trust
# increase; it can only trigger tighter review.

TRUST_INITIAL = 0.5
TRUST_MIN = 0.0
TRUST_MAX = 1.0

# Event-driven deltas. Slow to gain, faster to lose.
TRUST_DELTAS = {
    "ALLOW": +0.02,
    "DENY": -0.05,
    "ESCALATE": -0.03,
}
TRUST_TAMPER_RESET = 0.0

# Decay toward the neutral midpoint with inactivity. Applied once per
# logical tick; implementations choose the tick rate.
TRUST_DECAY_RATE = 0.01

# Scrutiny tier thresholds.
SCRUTINY_HIGH_MAX = 0.3
SCRUTINY_NORMAL_MAX = 0.7


def clamp_trust(score: float) -> float:
    """Clamp a trust score to the valid range [0.0, 1.0]."""
    return max(TRUST_MIN, min(TRUST_MAX, score))


def init_trust_state() -> dict:
    """Create an empty trust state container."""
    return {"scores": {}, "events": {}}


def _trust_key(agent_id: str, capability: str) -> str:
    return f"{agent_id}::{capability}"


def get_trust(state: dict, agent_id: str, capability: str) -> float:
    """Return the current trust score for (agent, capability), or initial."""
    return state["scores"].get(_trust_key(agent_id, capability), TRUST_INITIAL)


def update_trust(state: dict, agent_id: str, capability: str, event_type: str) -> float:
    """
    Apply a governance event to the trust score for (agent, capability).
    Returns the updated score.

    event_type is one of: 'ALLOW', 'DENY', 'ESCALATE', 'TAMPER'.
    Other event types are ignored (trust is not affected).
    """
    key = _trust_key(agent_id, capability)
    current = state["scores"].get(key, TRUST_INITIAL)

    if event_type == "TAMPER":
        new_score = TRUST_TAMPER_RESET
    elif event_type in TRUST_DELTAS:
        new_score = clamp_trust(current + TRUST_DELTAS[event_type])
    else:
        new_score = current

    state["scores"][key] = new_score
    state["events"].setdefault(key, []).append(event_type)
    return new_score


def decay_trust(state: dict, ticks: int = 1) -> None:
    """
    Decay all trust scores toward the neutral midpoint (0.5) over `ticks`
    units of inactivity. Scores above 0.5 decay down; scores below decay up.
    """
    for _ in range(ticks):
        for key, score in state["scores"].items():
            if score > TRUST_INITIAL:
                state["scores"][key] = max(TRUST_INITIAL, score - TRUST_DECAY_RATE)
            elif score < TRUST_INITIAL:
                state["scores"][key] = min(TRUST_INITIAL, score + TRUST_DECAY_RATE)


def scrutiny_tier(trust_score: float) -> str:
    """Map a trust score to a scrutiny tier label: 'high', 'normal', or 'fast'."""
    if trust_score < SCRUTINY_HIGH_MAX:
        return "high"
    if trust_score < SCRUTINY_NORMAL_MAX:
        return "normal"
    return "fast"


def recent_event_count(state: dict, agent_id: str, capability: str,
                       event_type: str, window: int = 10) -> int:
    """
    Count occurrences of an event type in the most-recent-N events for
    (agent, capability). Window is event-count-based, not time-based;
    implementations can substitute a time-based window.
    """
    key = _trust_key(agent_id, capability)
    events = state["events"].get(key, [])
    recent = events[-window:]
    return sum(1 for e in recent if e == event_type)


# ═══════════════════════════════════════════════════════════════════
# D.7 Policy Gate Tier 3 — Behavioral Pattern Analysis
# ═══════════════════════════════════════════════════════════════════
#
# Tier 3 runs only after Tier 1 (deterministic rules) and Tier 2
# (parameter inspection) have not resolved. Deterministic function of
# the trust score and a small set of behavioral signals — no ML, no
# scoring model, no hidden state. Implementations may substitute richer
# behavioral models as an Extension, but any conforming Tier 3 MUST
# produce identical decisions for identical inputs.

TIER3_ESCALATE_THRESHOLD = 3
TIER3_WINDOW = 10

# Mutating actions write, modify, or send. Read-only actions can be
# permitted even under low trust because blast radius is bounded by
# the underlying store's own access controls.
MUTATING_VERBS = {"create", "update", "delete", "send", "execute",
                  "publish", "transfer", "grant"}


def is_mutating_action(action_type: str) -> bool:
    """Return True if the action type performs a write or side-effecting call."""
    parts = action_type.lower().split(".")
    return any(v in parts for v in MUTATING_VERBS)


def tier3_evaluate(agent_id: str, action_type: str, capability: str,
                   trust_state: dict) -> dict:
    """
    Evaluate Tier 3 for an action. Callers MUST honor the Tier 1 → Tier 2
    → Tier 3 order; this function assumes Tier 1 and 2 did not resolve.

    Returns a decision dict with keys: decision, reason, tier, trust, scrutiny.
    decision is one of 'ALLOW', 'DENY', 'ESCALATE', 'ATTENUATE'.
    """
    trust = get_trust(trust_state, agent_id, capability)
    scrutiny = scrutiny_tier(trust)

    escalate_count = recent_event_count(
        trust_state, agent_id, capability, "ESCALATE", TIER3_WINDOW
    )

    if escalate_count > TIER3_ESCALATE_THRESHOLD:
        return {
            "decision": "ESCALATE",
            "reason": f"recent_escalates={escalate_count} exceeds threshold "
                      f"{TIER3_ESCALATE_THRESHOLD} in window of {TIER3_WINDOW}",
            "tier": 3,
            "trust": trust,
            "scrutiny": scrutiny,
        }

    mutating = is_mutating_action(action_type)

    if scrutiny == "high":
        if mutating:
            return {
                "decision": "ATTENUATE",
                "reason": f"trust={trust:.2f} below high-scrutiny threshold; "
                          f"mutating action attenuated",
                "tier": 3,
                "trust": trust,
                "scrutiny": scrutiny,
            }
        return {
            "decision": "ALLOW",
            "reason": f"trust={trust:.2f} low but action is read-only",
            "tier": 3,
            "trust": trust,
            "scrutiny": scrutiny,
        }

    if scrutiny == "normal":
        return {
            "decision": "ALLOW",
            "reason": f"trust={trust:.2f} within normal range",
            "tier": 3,
            "trust": trust,
            "scrutiny": scrutiny,
            "audit_flag": True,
        }

    return {
        "decision": "ALLOW",
        "reason": f"trust={trust:.2f} in fast-path range",
        "tier": 3,
        "trust": trust,
        "scrutiny": scrutiny,
    }


# ═══════════════════════════════════════════════════════════════════
# D.8 Output Evaluator — Scope Alignment
# ═══════════════════════════════════════════════════════════════════
#
# Checks agent-produced outputs against declared task intent and the
# agent's granted capabilities. Two alignment methods are supported:
#
#   D.8.1  Keyword overlap — baseline, requires only a list of task keywords
#   D.8.2  Slot match       — structured, requires a TaskDeclaration with
#                             typed slots (required_topics, forbidden_topics,
#                             allowed_resources)
#
# Both methods run uniform credential-pattern detection and out-of-scope
# capability-reference detection before alignment scoring.
#
# Return shape is identical across methods: {scope_alignment, findings,
# recommendation, method}.

CREDENTIAL_PATTERNS = [
    (r"\bAKIA[0-9A-Z]{16}\b", "aws_access_key_id"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "api_key_sk"),
    (r"\bgh[ps]_[A-Za-z0-9]{36,}\b", "github_token"),
    (r"\bBearer\s+[A-Za-z0-9._~+/=\-]{20,}\b", "bearer_token"),
    (r"(?i)password\s*[:=]\s*[A-Za-z0-9!@#$%^&*()_+\-]{6,}", "password_literal"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "private_key"),
]


def detect_credentials(output: str) -> list:
    """Scan output for credential-like patterns. Returns list of findings."""
    findings = []
    for pattern, label in CREDENTIAL_PATTERNS:
        for match in re.finditer(pattern, output):
            findings.append({
                "type": "credential_leak",
                "detail": f"detected pattern {label!r}",
                "severity": "critical",
            })
    return findings


def detect_out_of_scope_references(output: str, granted_capabilities: list) -> list:
    """
    Flag capability-shaped tokens in the output that are not within the
    agent's granted capability set. Capability tokens are dot-delimited
    lowercase sequences like 'gmail.drafts.create'.
    """
    findings = []
    mentions = set(re.findall(
        r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,4}\b", output
    ))
    granted_set = set(granted_capabilities)
    for mention in mentions:
        if mention in granted_set:
            continue
        if any(mention.startswith(g + ".") or g.startswith(mention + ".")
               for g in granted_set):
            continue
        findings.append({
            "type": "out_of_scope_reference",
            "detail": f"output references {mention!r} which is not in granted scope",
            "severity": "high",
        })
    return findings


def _recommend(alignment: float, findings: list) -> str:
    """Map alignment score + findings to PASS / FLAG / BLOCK."""
    if any(f["severity"] == "critical" for f in findings):
        return "BLOCK"
    if alignment < 0.5 or any(f["severity"] == "high" for f in findings):
        return "FLAG"
    return "PASS"


def evaluate_output_keyword_overlap(output: str, task_keywords: list,
                                    granted_capabilities: list) -> dict:
    """
    D.8.1 Baseline keyword-overlap scoring.

    Alignment = fraction of declared task keywords appearing in the output.
    Credential and out-of-scope checks run uniformly; critical findings
    drive alignment to 0.0, high findings dock by 0.2 each.
    """
    findings = []
    findings.extend(detect_credentials(output))
    findings.extend(detect_out_of_scope_references(output, granted_capabilities))

    output_lower = output.lower()
    if task_keywords:
        matched = sum(1 for kw in task_keywords if kw.lower() in output_lower)
        alignment = matched / len(task_keywords)
    else:
        alignment = 1.0

    critical_count = sum(1 for f in findings if f["severity"] == "critical")
    high_count = sum(1 for f in findings if f["severity"] == "high")
    if critical_count > 0:
        alignment = 0.0
    elif high_count > 0:
        alignment = max(0.0, alignment - 0.2 * high_count)

    return {
        "scope_alignment": round(alignment, 3),
        "findings": findings,
        "recommendation": _recommend(alignment, findings),
        "method": "keyword_overlap",
    }


def evaluate_output_slot_match(output: str, task_declaration: dict,
                               granted_capabilities: list) -> dict:
    """
    D.8.2 Structured slot-match scoring.

    TaskDeclaration slots:
      required_topics    — output MUST mention each (missing → medium finding)
      forbidden_topics   — output MUST NOT mention any (mention → high finding)
      allowed_resources  — capability-shaped tokens permitted by the task;
                           a subset of granted_capabilities, task-narrowed
    """
    findings = []
    findings.extend(detect_credentials(output))
    findings.extend(detect_out_of_scope_references(output, granted_capabilities))

    output_lower = output.lower()
    required_topics = task_declaration.get("required_topics", [])
    forbidden_topics = task_declaration.get("forbidden_topics", [])
    allowed_resources = set(r.lower() for r in task_declaration.get("allowed_resources", []))

    for topic in required_topics:
        if topic.lower() not in output_lower:
            findings.append({
                "type": "missing_required_topic",
                "detail": f"output does not mention required topic {topic!r}",
                "severity": "medium",
            })

    for topic in forbidden_topics:
        if topic.lower() in output_lower:
            findings.append({
                "type": "forbidden_topic_mention",
                "detail": f"output mentions forbidden topic {topic!r}",
                "severity": "high",
            })

    if allowed_resources:
        mentions = set(re.findall(
            r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,4}\b", output_lower
        ))
        for mention in mentions:
            if mention in allowed_resources:
                continue
            if any(mention.startswith(r + ".") for r in allowed_resources):
                continue
            findings.append({
                "type": "resource_outside_task_scope",
                "detail": f"output references {mention!r} outside task's allowed_resources",
                "severity": "high",
            })

    critical_count = sum(1 for f in findings if f["severity"] == "critical")
    high_count = sum(1 for f in findings if f["severity"] == "high")
    medium_count = sum(1 for f in findings if f["severity"] == "medium")

    if critical_count > 0:
        alignment = 0.0
    else:
        alignment = max(0.0, 1.0 - 0.3 * high_count - 0.1 * medium_count)

    return {
        "scope_alignment": round(alignment, 3),
        "findings": findings,
        "recommendation": _recommend(alignment, findings),
        "method": "slot_match",
    }


# ═══════════════════════════════════════════════════════════════════
# Test Runner
# ═══════════════════════════════════════════════════════════════════

def run_tests():
    """Run conformance test vectors. Reports pass/fail/skip separately."""
    try:
        with open("tests/conformance-vectors.json", "r") as f:
            test_data = json.load(f)
    except FileNotFoundError:
        print("  Test vectors file not found. Run from repo root.")
        return False

    passed = 0
    failed = 0
    skipped = 0

    for suite in test_data["test_suites"]:
        print(f"\n  Suite: {suite['suite']}")
        print(f"  {suite['description']}")
        print()

        if suite["suite"] == "pattern_matching":
            for test in suite["tests"]:
                result = matches(test["input"]["action_type"], test["input"]["pattern"])
                ok = result == test["expected"]
                if ok:
                    passed += 1
                    print(f"    [PASS] {test['id']}: {test['description']}")
                else:
                    failed += 1
                    print(f"    [FAIL] {test['id']}: {test['description']}")
                    print(f"           Expected: {test['expected']}, Got: {result}")

        elif suite["suite"] == "scope_subset":
            for test in suite["tests"]:
                result = actions_are_subset(test["child_patterns"], test["parent_patterns"])
                ok = result == test["expected"]
                if ok:
                    passed += 1
                    print(f"    [PASS] {test['id']}: {test['description']}")
                else:
                    failed += 1
                    print(f"    [FAIL] {test['id']}: {test['description']}")
                    print(f"           Expected: {test['expected']}, Got: {result}")

        elif suite["suite"] == "policy_evaluation":
            suite_rules = suite["policy"]["rules"]
            for test in suite["tests"]:
                if "identity_state" in test:
                    skipped += 1
                    print(f"    [SKIP] {test['id']}: {test['description']}")
                    print(f"           Reason: requires stateful identity simulation (see integration tests)")
                    continue

                # Per-test policy override (v0.5.0-draft): test-local rules
                rules = test.get("policy_override", suite_rules)

                # Multi-case vector (v0.5.0-draft): each case has its own action/params/expected
                cases = test.get("cases")
                if cases is None:
                    cases = [test]

                test_passed_count = 0
                test_failed_count = 0
                fail_msgs = []
                for case in cases:
                    decision, tier, reason = evaluate_rules(rules, case["action_type"], case["params"])
                    ok = decision == case["expected_decision"]
                    if "expected_tier" in case:
                        ok = ok and tier == case["expected_tier"]
                    if "expected_reason" in case:
                        ok = ok and reason == case.get("expected_reason")
                    if ok:
                        test_passed_count += 1
                    else:
                        test_failed_count += 1
                        fail_msgs.append(
                            f"           {case.get('id', test['id'])}: "
                            f"expected {case['expected_decision']} "
                            f"Tier {case.get('expected_tier', '?')} "
                            f"{case.get('expected_reason', '')} | "
                            f"got {decision} Tier {tier} {reason or ''}"
                        )

                if test_failed_count == 0:
                    passed += 1
                    print(f"    [PASS] {test['id']}: {test['description']}")
                else:
                    failed += 1
                    print(f"    [FAIL] {test['id']}: {test['description']}")
                    for m in fail_msgs:
                        print(m)

        elif suite["suite"] in ("delegation", "escalation_lifecycle"):
            # These require the integration harness — see simulation/integration_tests.py
            skipped += len(suite["tests"])
            print(f"    [{len(suite['tests'])} tests] Behavioral suite — requires integration harness")
            print(f"    Run: python3 simulation/integration_tests.py")

    # ── Additional algorithm tests not in conformance-vectors.json ──

    print(f"\n  Suite: variable_resolution")
    print(f"  Variable resolution in constraint evaluation (Appendix D.2)")
    print()

    # Variable resolution tests
    var_tests = [
        ("VR-001", "Resolve agent context variable",
         "owner", "EQUALS", "${agent.task_context.user_id}",
         {"owner": "user-123"}, {"agent": {"task_context": {"user_id": "user-123"}}}, True),
        ("VR-002", "Unresolvable variable fails closed",
         "owner", "EQUALS", "${agent.nonexistent.field}",
         {"owner": "user-123"}, {"agent": {}}, False),
        ("VR-003", "MATCHES with valid regex",
         "email", "MATCHES", r"^[a-z]+@partner\.com$",
         {"email": "alice@partner.com"}, {}, True),
        ("VR-004", "MATCHES with non-matching value",
         "email", "MATCHES", r"^[a-z]+@partner\.com$",
         {"email": "alice@competitor.com"}, {}, False),
        ("VR-005", "NOT_MATCHES succeeds when no match",
         "email", "NOT_MATCHES", r"@competitor\.com$",
         {"email": "alice@partner.com"}, {}, True),
        ("VR-006", "NOT_MATCHES fails when matches",
         "email", "NOT_MATCHES", r"@competitor\.com$",
         {"email": "alice@competitor.com"}, {}, False),
        ("VR-007", "Invalid regex fails closed (MATCHES)",
         "value", "MATCHES", r"[invalid",
         {"value": "test"}, {}, False),
        ("VR-008", "Invalid regex fails closed (NOT_MATCHES)",
         "value", "NOT_MATCHES", r"[invalid",
         {"value": "test"}, {}, False),
    ]
    for tid, desc, field, op, val, params, ctx, expected in var_tests:
        result = evaluate_constraint(field, op, val, params, ctx)
        if result == expected:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            print(f"    [FAIL] {tid}: {desc}")
            print(f"           Expected: {expected}, Got: {result}")

    # ── Full scope subset tests ──

    print(f"\n  Suite: full_scope_subset")
    print(f"  Complete scope subset comparison (all 5 steps, Appendix D.3)")
    print()

    scope_tests = [
        ("FS-001", "Identical full scopes are subsets",
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 100}],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [{"resource_pattern": "db-prod", "access_level": "ACCESS_READ"}],
          "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY"]}},
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 100}],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [{"resource_pattern": "db-prod", "access_level": "ACCESS_READ"}],
          "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY"]}},
         True),
        ("FS-002", "Child with tighter constraints is subset",
         {"authorized_actions": [{"pattern": "db.query"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 50}],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 100}],
          "delegation": {"can_delegate": True, "max_depth": 2},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         True),
        ("FS-003", "Child with looser constraints is NOT subset",
         {"authorized_actions": [{"pattern": "db.query"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 200}],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [{"field": "limit", "operator": "LESS_THAN_OR_EQUAL", "value": 100}],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         False),
        ("FS-004", "Child requesting delegation when parent disallows it",
         {"authorized_actions": [{"pattern": "db.query"}],
          "parameter_constraints": [],
          "delegation": {"can_delegate": True, "max_depth": 1},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [], "output_policy": {"authorized_output_types": []}},
         False),
        ("FS-005", "Child with additional output types is NOT subset",
         {"authorized_actions": [{"pattern": "db.query"}],
          "parameter_constraints": [],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [],
          "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY", "CUSTOMER_FACING"]}},
         {"authorized_actions": [{"pattern": "db.*"}],
          "parameter_constraints": [],
          "delegation": {"can_delegate": False, "max_depth": 0},
          "resource_constraints": [],
          "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY"]}},
         False),
    ]

    for tid, desc, child, parent, expected in scope_tests:
        result = is_subset(child, parent)
        if result == expected:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            print(f"    [FAIL] {tid}: {desc}")
            print(f"           Expected: {expected}, Got: {result}")

    # ── Rate limit tests ──

    print(f"\n  Suite: rate_limits")
    print(f"  Rate limit evaluation (Appendix D.4)")
    print()

    now = datetime(2026, 4, 11, 12, 0, 0)
    action_log = [
        {"agent_id": "a1", "agent_type": "research", "action_type": "db.query",
         "timestamp": now - timedelta(minutes=10)},
        {"agent_id": "a1", "agent_type": "research", "action_type": "db.query",
         "timestamp": now - timedelta(minutes=5)},
        {"agent_id": "a1", "agent_type": "research", "action_type": "db.query",
         "timestamp": now - timedelta(minutes=2)},
        {"agent_id": "a2", "agent_type": "research", "action_type": "db.query",
         "timestamp": now - timedelta(minutes=3)},
    ]

    rl_tests = [
        ("RL-001", "Within sliding window limit",
         "a1", {"action_pattern": "db.query", "max_count": 5, "window": "1h", "scope": "INSTANCE"},
         True),
        ("RL-002", "Exceeds sliding window limit",
         "a1", {"action_pattern": "db.query", "max_count": 3, "window": "1h", "scope": "INSTANCE"},
         False),
        ("RL-003", "TYPE scope counts all instances",
         "a1", {"action_pattern": "db.query", "max_count": 4, "window": "1h",
                "scope": "TYPE", "agent_type": "research"},
         False),  # 4 total entries across a1 and a2
        ("RL-004", "Old entries outside window don't count",
         "a1", {"action_pattern": "db.query", "max_count": 2, "window": "3m", "scope": "INSTANCE"},
         False),  # Only 1 entry within 3 minutes, limit is 2 → within limit... wait
    ]

    # Fix RL-004: within 3 minutes of 'now', a1 has 1 entry (at -2m). Limit is 2. So within limit → True
    rl_tests[3] = ("RL-004", "Old entries outside window don't count",
                    "a1", {"action_pattern": "db.query", "max_count": 2, "window": "3m", "scope": "INSTANCE"},
                    True)

    for tid, desc, agent_id, limit, expected in rl_tests:
        result = check_rate_limit_sliding(action_log, agent_id, "db.query", limit, now)
        if result == expected:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            print(f"    [FAIL] {tid}: {desc}")
            print(f"           Expected: {expected}, Got: {result}")

    # ── Hash chain tests ──

    print(f"\n  Suite: hash_chain")
    print(f"  Hash chain integrity verification (Appendix D.5)")
    print()

    genesis = create_genesis("SHA256", "human:admin@org", "chain-001")
    chain = []
    append_to_chain(chain, "SHA256", genesis, "evt-001", "ActionRequested", "agent-abc",
                    decision=None, policy_version="1.0.0")
    append_to_chain(chain, "SHA256", genesis, "evt-002", "ActionEvaluated", "agent-abc",
                    decision="ALLOW", tier=1, policy_version="1.0.0", reason_code=None)
    append_to_chain(chain, "SHA256", genesis, "evt-003", "ActionExecuted", "agent-abc",
                    outcome="SUCCESS")

    valid, err = verify_chain(chain, "SHA256", genesis)
    if valid:
        passed += 1
        print(f"    [PASS] HC-001: Valid chain verifies")
    else:
        failed += 1
        print(f"    [FAIL] HC-001: Valid chain verifies — {err}")

    # Tamper with agent_id
    tampered_chain = [dict(e) for e in chain]
    tampered_chain[1]["agent_id"] = "agent-TAMPERED"
    valid, err = verify_chain(tampered_chain, "SHA256", genesis)
    if not valid:
        passed += 1
        print(f"    [PASS] HC-002: Tampered agent_id detected")
    else:
        failed += 1
        print(f"    [FAIL] HC-002: Tampered agent_id NOT detected")

    # Tamper with decision field (the critical fix — old hash didn't cover this)
    tampered_decision = [dict(e) for e in chain]
    tampered_decision[1]["decision"] = "DENY"  # Changed from ALLOW
    valid, err = verify_chain(tampered_decision, "SHA256", genesis)
    if not valid:
        passed += 1
        print(f"    [PASS] HC-002b: Tampered decision field detected")
    else:
        failed += 1
        print(f"    [FAIL] HC-002b: Tampered decision field NOT detected")

    # Tamper with policy_version
    tampered_policy = [dict(e) for e in chain]
    tampered_policy[1]["policy_version"] = "9.9.9"
    valid, err = verify_chain(tampered_policy, "SHA256", genesis)
    if not valid:
        passed += 1
        print(f"    [PASS] HC-002c: Tampered policy_version detected")
    else:
        failed += 1
        print(f"    [FAIL] HC-002c: Tampered policy_version NOT detected")

    # Empty chain is valid
    valid, err = verify_chain([], "SHA256", genesis)
    if valid:
        passed += 1
        print(f"    [PASS] HC-003: Empty chain is valid")
    else:
        failed += 1
        print(f"    [FAIL] HC-003: Empty chain should be valid — {err}")

    # SHA384 support
    genesis384 = create_genesis("SHA384", "human:admin@org", "chain-002")
    chain384 = []
    append_to_chain(chain384, "SHA384", genesis384, "evt-010", "ActionRequested", "agent-xyz")
    valid, err = verify_chain(chain384, "SHA384", genesis384)
    if valid:
        passed += 1
        print(f"    [PASS] HC-004: SHA384 chain verifies")
    else:
        failed += 1
        print(f"    [FAIL] HC-004: SHA384 chain verifies — {err}")

    # ── Trust engine tests ──

    print(f"\n  Suite: trust_engine")
    print(f"  Trust state management (Appendix D.6)")
    print()

    def _trust_check(tid, desc, ok):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            print(f"    [FAIL] {tid}: {desc}")

    ts = init_trust_state()
    _trust_check("TR-001", "Initial trust score is 0.5",
                 get_trust(ts, "a1", "cap.read") == 0.5)

    update_trust(ts, "a1", "cap.read", "ALLOW")
    _trust_check("TR-002", "ALLOW event increases trust by 0.02",
                 abs(get_trust(ts, "a1", "cap.read") - 0.52) < 1e-9)

    for _ in range(50):
        update_trust(ts, "a1", "cap.read", "ALLOW")
    _trust_check("TR-003", "Trust is clamped at 1.0 with repeated ALLOWs",
                 get_trust(ts, "a1", "cap.read") == 1.0)

    ts2 = init_trust_state()
    for _ in range(30):
        update_trust(ts2, "a2", "cap.write", "DENY")
    _trust_check("TR-004", "Trust is clamped at 0.0 with repeated DENYs",
                 get_trust(ts2, "a2", "cap.write") == 0.0)

    ts3 = init_trust_state()
    update_trust(ts3, "a3", "cap.x", "ALLOW")
    update_trust(ts3, "a3", "cap.y", "DENY")
    _trust_check("TR-005", "Per-capability isolation (same agent, different caps)",
                 get_trust(ts3, "a3", "cap.x") != get_trust(ts3, "a3", "cap.y"))

    update_trust(ts3, "a3", "cap.x", "TAMPER")
    _trust_check("TR-006", "TAMPER event drops trust to 0.0",
                 get_trust(ts3, "a3", "cap.x") == 0.0)

    ts4 = init_trust_state()
    for _ in range(10):
        update_trust(ts4, "a4", "cap.z", "ALLOW")
    before_decay = get_trust(ts4, "a4", "cap.z")
    decay_trust(ts4, ticks=5)
    after_decay = get_trust(ts4, "a4", "cap.z")
    _trust_check("TR-007", "Decay moves above-midpoint score toward 0.5",
                 after_decay < before_decay and after_decay >= 0.5)

    # ── Tier 3 policy evaluation tests ──

    print(f"\n  Suite: tier3_evaluation")
    print(f"  Policy Gate Tier 3 behavioral evaluation (Appendix D.7)")
    print()

    def _t3_check(tid, desc, ok, got=None):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            extra = f" (got {got!r})" if got is not None else ""
            print(f"    [FAIL] {tid}: {desc}{extra}")

    # Fast path: high trust → ALLOW
    ts_high = init_trust_state()
    for _ in range(20):
        update_trust(ts_high, "a1", "gmail.drafts", "ALLOW")
    r = tier3_evaluate("a1", "gmail.drafts.create", "gmail.drafts", ts_high)
    _t3_check("T3-001", "High trust yields ALLOW in fast-path",
              r["decision"] == "ALLOW" and r["scrutiny"] == "fast", r)

    # Normal trust: mid-range → ALLOW with audit flag
    ts_mid = init_trust_state()
    r = tier3_evaluate("a2", "gmail.drafts.create", "gmail.drafts", ts_mid)
    _t3_check("T3-002", "Normal trust yields ALLOW with audit flag",
              r["decision"] == "ALLOW" and r["scrutiny"] == "normal"
              and r.get("audit_flag") is True, r)

    # Low trust + mutating → ATTENUATE
    ts_low = init_trust_state()
    for _ in range(10):
        update_trust(ts_low, "a3", "db.records", "DENY")
    r = tier3_evaluate("a3", "db.records.update", "db.records", ts_low)
    _t3_check("T3-003", "Low trust on a mutating action yields ATTENUATE",
              r["decision"] == "ATTENUATE" and r["scrutiny"] == "high", r)

    # Low trust + read-only → ALLOW
    r = tier3_evaluate("a3", "db.records.read", "db.records", ts_low)
    _t3_check("T3-004", "Low trust on a read-only action yields ALLOW",
              r["decision"] == "ALLOW" and r["scrutiny"] == "high", r)

    # Escalation-count threshold → ESCALATE regardless of trust
    ts_esc = init_trust_state()
    for _ in range(20):
        update_trust(ts_esc, "a4", "api.calls", "ALLOW")  # push trust up
    for _ in range(4):
        update_trust(ts_esc, "a4", "api.calls", "ESCALATE")
    r = tier3_evaluate("a4", "api.calls.send", "api.calls", ts_esc)
    _t3_check("T3-005", "Exceeding escalate threshold forces ESCALATE",
              r["decision"] == "ESCALATE", r)

    # Mutating verb detection
    _t3_check("T3-006", "is_mutating_action detects 'update' as mutating",
              is_mutating_action("db.records.update"))
    _t3_check("T3-007", "is_mutating_action detects 'read' as non-mutating",
              not is_mutating_action("db.records.read"))

    # ── Output evaluator — keyword overlap tests ──

    print(f"\n  Suite: output_evaluator_keyword")
    print(f"  Output scope alignment via keyword overlap (Appendix D.8.1)")
    print()

    def _oe_check(tid, desc, ok, got=None):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"    [PASS] {tid}: {desc}")
        else:
            failed += 1
            extra = f" (got {got!r})" if got is not None else ""
            print(f"    [FAIL] {tid}: {desc}{extra}")

    r = evaluate_output_keyword_overlap(
        output="Invoice Q3 summary: total $45,000 across three line items.",
        task_keywords=["invoice", "Q3", "total"],
        granted_capabilities=["gmail.drafts"],
    )
    _oe_check("OE-K-001", "Full keyword coverage yields high alignment (PASS)",
              r["scope_alignment"] >= 0.99 and r["recommendation"] == "PASS", r)

    r = evaluate_output_keyword_overlap(
        output="The weather today is sunny and mild.",
        task_keywords=["invoice", "Q3", "total"],
        granted_capabilities=["gmail.drafts"],
    )
    _oe_check("OE-K-002", "No keyword coverage yields low alignment (FLAG)",
              r["scope_alignment"] == 0.0 and r["recommendation"] == "FLAG", r)

    r = evaluate_output_keyword_overlap(
        output="Your API key is sk-abcdefghij1234567890XYZ.",
        task_keywords=["summary"],
        granted_capabilities=["gmail.drafts"],
    )
    _oe_check("OE-K-003", "Credential leak forces alignment to 0 and BLOCK",
              r["scope_alignment"] == 0.0 and r["recommendation"] == "BLOCK"
              and any(f["type"] == "credential_leak" for f in r["findings"]), r)

    r = evaluate_output_keyword_overlap(
        output="I called db.records.delete to clean up after summary.",
        task_keywords=["summary"],
        granted_capabilities=["gmail.drafts"],
    )
    _oe_check("OE-K-004", "Out-of-scope capability reference flags alignment",
              any(f["type"] == "out_of_scope_reference" for f in r["findings"])
              and r["recommendation"] in ("FLAG", "BLOCK"), r)

    # ── Output evaluator — slot match tests ──

    print(f"\n  Suite: output_evaluator_slotmatch")
    print(f"  Output scope alignment via typed slots (Appendix D.8.2)")
    print()

    r = evaluate_output_slot_match(
        output="Invoice Q3 total: $45,000 across three line items.",
        task_declaration={
            "required_topics": ["invoice", "Q3"],
            "forbidden_topics": ["salary", "PII"],
            "allowed_resources": ["accounting.invoices"],
        },
        granted_capabilities=["accounting.invoices", "gmail.drafts"],
    )
    _oe_check("OE-S-001", "All required topics present, no forbidden, yields PASS",
              r["scope_alignment"] == 1.0 and r["recommendation"] == "PASS", r)

    r = evaluate_output_slot_match(
        output="Salary breakdown: employee earnings are in the attached invoice.",
        task_declaration={
            "required_topics": ["invoice"],
            "forbidden_topics": ["salary", "earnings"],
            "allowed_resources": ["accounting.invoices"],
        },
        granted_capabilities=["accounting.invoices"],
    )
    _oe_check("OE-S-002", "Forbidden-topic mentions produce high findings and FLAG",
              r["recommendation"] == "FLAG"
              and sum(1 for f in r["findings"] if f["type"] == "forbidden_topic_mention") >= 2, r)

    r = evaluate_output_slot_match(
        output="Summary complete. Referenced accounting.payroll.read during processing.",
        task_declaration={
            "required_topics": [],
            "forbidden_topics": [],
            "allowed_resources": ["accounting.invoices"],
        },
        granted_capabilities=["accounting.invoices", "accounting.payroll"],
    )
    _oe_check("OE-S-003", "Resource outside task scope flags even if agent holds the grant",
              any(f["type"] == "resource_outside_task_scope" for f in r["findings"])
              and r["recommendation"] == "FLAG", r)

    r = evaluate_output_slot_match(
        output="Invoice summary. Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefg",
        task_declaration={
            "required_topics": ["invoice"],
            "forbidden_topics": [],
            "allowed_resources": ["accounting.invoices"],
        },
        granted_capabilities=["accounting.invoices"],
    )
    _oe_check("OE-S-004", "Credential regex fires under slot-match and forces BLOCK",
              any(f["type"] == "credential_leak" for f in r["findings"])
              and r["recommendation"] == "BLOCK"
              and r["scope_alignment"] == 0.0, r)

    r = evaluate_output_slot_match(
        output="Q3 completed.",
        task_declaration={
            "required_topics": ["invoice", "total"],
            "forbidden_topics": [],
            "allowed_resources": [],
        },
        granted_capabilities=[],
    )
    _oe_check("OE-S-005", "Missing required topics produce medium findings and dock alignment",
              sum(1 for f in r["findings"] if f["type"] == "missing_required_topic") == 2
              and r["scope_alignment"] < 1.0, r)

    # ── Summary ──

    total = passed + failed + skipped
    print(f"\n  {'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"  Total:   {total} test cases")
    print()
    if skipped > 0:
        print(f"  Skipped tests require either stateful identity simulation")
        print(f"  or the integration test harness (simulation/integration_tests.py).")
    if failed == 0:
        print(f"  All executed tests passed.")
    print()
    return failed == 0


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Agent Governance Spec — Reference Algorithm Tests")
    print("  Covers Appendix D: D.1 through D.8")
    print("="*60)
    success = run_tests()
    sys.exit(0 if success else 1)
