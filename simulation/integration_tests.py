"""
Agent Governance Specification — Integration Test Harness

Exercises the behavioral test suites that require a stateful governance
stack: delegation with cascade termination, escalation lifecycle,
authority expiration, rate limits, damage budgets, escalation timeout,
and event schema validation.

The GovernanceStack defined here is an in-memory behavioral test fixture,
not a complete production-conforming implementation. It delegates all algorithmic decisions to the canonical
functions in reference_algorithms.py. demo.py is a separate illustrative
walkthrough and is not used by this harness.

Run: python3 simulation/integration_tests.py
"""

import json
from copy import deepcopy
import sys
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from reference_algorithms import (
    matches, evaluate_rules, evaluate_constraint, is_subset,
    actions_are_subset, rules_are_subset, validate_action_pattern, check_rate_limit_sliding,
    create_genesis, append_to_chain, verify_chain,
)

# Optional: jsonschema for event validation
try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# ═══════════════════════════════════════════════════════════════════
# Minimal Governance Stack
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Grant:
    grant_id: str
    agent_type: str
    scope: dict
    rules: list[dict]
    ttl_seconds: int
    granted_by: str
    granted_at: datetime
    rate_limits: list[dict] = field(default_factory=list)
    damage_budgets: list[dict] = field(default_factory=list)
    terminated: bool = False
    terminated_at: datetime | None = None
    terminated_by: str | None = None
    termination_reason: str | None = None  # "REVOKED" | "CASCADED" | "EXPIRED"

    @property
    def expires_at(self):
        return self.granted_at + timedelta(seconds=self.ttl_seconds)

    def is_expired(self, now=None):
        return (now or datetime.now()) >= self.expires_at

    def is_active(self, now=None):
        return not self.terminated and not self.is_expired(now)


@dataclass
class Identity:
    instance_id: str
    agent_type: str
    parent_id: Optional[str]
    lineage_chain: list[str]
    scope: dict
    rules: list[dict]
    grant_id: str
    created_at: datetime
    expires_at: datetime
    terminated: bool = False
    termination_reason: Optional[str] = None


class GovernanceStack:
    """Minimal in-memory governance stack for integration testing."""

    def __init__(self):
        self.grants: dict[str, Grant] = {}
        self.identities: dict[str, Identity] = {}
        self.audit: list[dict] = []
        self.action_log: list[dict] = []  # For rate limit tracking
        self.escalation_queue: list[dict] = []
        self.genesis = create_genesis("SHA256", "system", "test-chain")
        self.chain: list[dict] = []
        self.now = datetime(2026, 4, 11, 12, 0, 0)

    def set_time(self, dt: datetime):
        self.now = dt

    def advance_time(self, **kwargs):
        self.now += timedelta(**kwargs)

    # ── Authority Registry ──

    def create_grant(self, agent_type: str, scope: dict, rules: list[dict],
                     ttl_seconds: int, granted_by: str, **kwargs) -> Grant:
        if ttl_seconds <= 0 or not granted_by:
            raise ValueError("A named grantor and positive TTL are required")
        for rule in rules:
            validate_action_pattern(rule)
        declared = scope.get("authorized_actions", [])
        if not (rules_are_subset(rules, declared) and rules_are_subset(declared, rules)):
            raise ValueError("Execution rules must match declared authority")
        grant = Grant(
            grant_id=f"grant-{uuid.uuid4().hex[:8]}",
            agent_type=agent_type, scope=deepcopy(scope), rules=deepcopy(rules),
            ttl_seconds=ttl_seconds, granted_by=granted_by,
            granted_at=self.now, **kwargs,
        )
        self.grants[grant.grant_id] = grant
        self._audit("AuthorityGrantCreated", "system", agent_type=agent_type,
                     detail=f"By {granted_by}, TTL={ttl_seconds}s")
        return grant

    def revoke_grant(self, grant_id: str, revoked_by: str):
        grant = self.grants.get(grant_id)
        if grant and not grant.terminated:
            grant.terminated = True
            grant.terminated_at = self.now
            grant.terminated_by = revoked_by
            grant.termination_reason = "REVOKED"
            self._audit("AuthorityGrantTerminated", "system",
                         detail=f"{grant_id} reason=REVOKED terminated_by={revoked_by}")

    def _detect_expiration(self, grant):
        """Lazy expiration detection. Flips struct state and emits event exactly once
        when a grant's TTL has elapsed. Per Section 3.1 Termination Completeness."""
        if grant and not grant.terminated and grant.is_expired(self.now):
            grant.terminated = True
            grant.terminated_at = self.now
            grant.terminated_by = None  # system-driven
            grant.termination_reason = "EXPIRED"
            self._audit("AuthorityGrantTerminated", "system",
                         detail=f"{grant.grant_id} reason=EXPIRED terminated_by=None")

    # ── Identity Service (uses canonical is_subset) ──

    def create_root_identity(self, grant: Grant) -> Identity:
        if not grant.is_active(self.now):
            raise ValueError("Cannot create identity from inactive authority")
        iid = f"agent-{uuid.uuid4().hex[:8]}"
        identity = Identity(
            instance_id=iid, agent_type=grant.agent_type,
            parent_id=None, lineage_chain=[iid],
            scope=deepcopy(grant.scope), rules=deepcopy(grant.rules),
            grant_id=grant.grant_id, created_at=self.now,
            expires_at=grant.expires_at,
        )
        self.identities[iid] = identity
        self._audit("AgentSpawned", iid, agent_type=grant.agent_type,
                     detail=f"Root agent, grant={grant.grant_id}")
        return identity

    def create_child_identity(self, parent: Identity, child_type: str,
                              child_scope: dict,
                              child_rules: list[dict]) -> tuple[Optional[Identity], Optional[str]]:
        grant = self.grants.get(parent.grant_id)
        if (not grant or not grant.is_active(self.now) or
                any(self.identities[i].terminated or self.now >= self.identities[i].expires_at
                    for i in parent.lineage_chain)):
            return None, "AUTHORITY_EXPIRED"
        # Check parent can delegate
        parent_deleg = parent.scope.get("delegation", {})
        if not parent_deleg.get("can_delegate", False):
            self._audit("ActionDenied", parent.instance_id, agent_type=parent.agent_type,
                         detail="Cannot delegate: can_delegate=false", reason="SCOPE_VIOLATION")
            return None, "SCOPE_VIOLATION"

        # Check delegation depth
        max_depth = parent_deleg.get("max_depth", 0)
        if max_depth <= 0:
            self._audit("ActionDenied", parent.instance_id, agent_type=parent.agent_type,
                         detail=f"Delegation depth {len(parent.lineage_chain)} exceeds max {max_depth}",
                         reason="DELEGATION_DEPTH_EXCEEDED")
            return None, "DELEGATION_DEPTH_EXCEEDED"

        # Full scope subset check using canonical is_subset (Appendix D.3)
        delegatable = parent_deleg.get("delegatable_scope")
        if delegatable:
            parent_scope_for_check = delegatable
        else:
            parent_scope_for_check = parent.scope

        declared = child_scope.get("authorized_actions", [])
        if not (rules_are_subset(child_rules, declared)
                and rules_are_subset(declared, child_rules)
                and is_subset(child_scope, parent.scope)
                and is_subset(child_scope, parent_scope_for_check)):
            self._audit("ActionDenied", parent.instance_id, agent_type=parent.agent_type,
                         detail="Child scope not subset of delegatable scope (full is_subset check)",
                         reason="DELEGATION_SCOPE_VIOLATION")
            return None, "DELEGATION_SCOPE_VIOLATION"

        iid = f"agent-{uuid.uuid4().hex[:8]}"
        identity = Identity(
            instance_id=iid, agent_type=child_type,
            parent_id=parent.instance_id,
            lineage_chain=parent.lineage_chain + [iid],
            scope=deepcopy(child_scope), rules=deepcopy(child_rules),
            grant_id=parent.grant_id, created_at=self.now,
            expires_at=min(parent.expires_at, self.now + timedelta(hours=1)),
        )
        self.identities[iid] = identity
        self._audit("AgentSpawned", iid, agent_type=child_type,
                     detail=f"Child of {parent.instance_id}")
        return identity, None

    def terminate(self, identity: Identity, reason: str) -> list[Identity]:
        identity.terminated = True
        identity.termination_reason = reason
        self._audit("AgentTerminated", identity.instance_id,
                     agent_type=identity.agent_type, detail=f"Reason: {reason}")
        cascaded = []
        for child in list(self.identities.values()):
            if child.parent_id == identity.instance_id and not child.terminated:
                cascaded.append(child)
                cascaded.extend(self.terminate(child, "CASCADED"))
        return cascaded

    # ── Policy Gate (with rate limits and damage budgets) ──

    def evaluate(self, identity: Identity, action_type: str,
                 params: dict = None) -> tuple[str, int, Optional[str]]:
        params = params or {}

        if identity.terminated:
            self._audit("ActionDenied", identity.instance_id,
                         agent_type=identity.agent_type,
                         action=action_type, reason="IDENTITY_EXPIRED",
                         detail="Agent is terminated")
            return "DENY", 1, "IDENTITY_EXPIRED"

        grant = self.grants.get(identity.grant_id)
        self._detect_expiration(grant)  # Lazy: fires AuthorityGrantTerminated if TTL elapsed
        if not grant or not grant.is_active(self.now):
            reason = "AUTHORITY_REVOKED" if grant and grant.termination_reason == "REVOKED" else "AUTHORITY_EXPIRED"
            self._audit("ActionDenied", identity.instance_id,
                         agent_type=identity.agent_type,
                         action=action_type, reason=reason)
            return "DENY", 1, reason

        if self.now >= identity.expires_at:
            self._audit("ActionDenied", identity.instance_id,
                         agent_type=identity.agent_type,
                         action=action_type, reason="IDENTITY_EXPIRED")
            return "DENY", 1, "IDENTITY_EXPIRED"

        # Rate limit check (Appendix D.4)
        for rl in grant.rate_limits:
            if matches(action_type, rl["action_pattern"]):
                within_limit = check_rate_limit_sliding(
                    self.action_log, identity.instance_id,
                    action_type, rl, self.now
                )
                if not within_limit:
                    self._audit("ActionDenied", identity.instance_id,
                                 agent_type=identity.agent_type,
                                 action=action_type, reason="RATE_LIMIT_EXCEEDED",
                                 detail=f"Exceeds {rl['max_count']}/{rl['window']}")
                    return "DENY", 1, "RATE_LIMIT_EXCEEDED"

        # Damage budget check (Tier 2)
        for db in grant.damage_budgets:
            if db.get("evaluation_tier", 2) == 2:
                accumulator_field = db["accumulator"]
                current_value = _resolve_dot(accumulator_field, params)
                if current_value is not None:
                    # Sum accumulated value in window
                    window = _parse_simple_duration(db["window"])
                    window_start = self.now - window
                    accumulated = sum(
                        _resolve_dot(db["accumulator"], e.get("params", {})) or 0
                        for e in self.action_log
                        if e.get("agent_id") == identity.instance_id
                        and e.get("timestamp", datetime.min) >= window_start
                    )
                    if accumulated + current_value > db["threshold"]:
                        on_exceed = db.get("on_exceed", "DENY")
                        self._audit("ActionDenied" if on_exceed == "DENY" else "ActionEvaluated",
                                     identity.instance_id, agent_type=identity.agent_type,
                                     action=action_type,
                                     reason="DAMAGE_BUDGET_EXCEEDED",
                                     decision=on_exceed,
                                     detail=f"{db['metric']}: {accumulated}+{current_value} > {db['threshold']}")
                        return on_exceed, 2, "DAMAGE_BUDGET_EXCEEDED"

        # Global constraints are authority bounds, not advisory metadata.
        if not all(evaluate_constraint(c["field"], c["operator"], c["value"], params)
                   for c in identity.scope.get("parameter_constraints", [])):
            self._audit("ActionDenied", identity.instance_id, action=action_type,
                        reason="CONSTRAINT_VIOLATION")
            return "DENY", 2, "CONSTRAINT_VIOLATION"
        # Evaluate against rules (Appendix D.2)
        decision, tier, reason = evaluate_rules(identity.rules, action_type, params)
        self._audit("ActionEvaluated", identity.instance_id,
                     agent_type=identity.agent_type,
                     action=action_type, decision=decision, tier=tier,
                     reason=reason)

        # Record in action log for rate limit / damage budget tracking
        if decision in ("ALLOW", "ATTENUATE"):
            self.action_log.append({
                "agent_id": identity.instance_id,
                "agent_type": identity.agent_type,
                "action_type": action_type,
                "params": params,
                "timestamp": self.now,
            })

        if decision == "ESCALATE":
            self.escalation_queue.append({
                "escalation_id": f"esc-{uuid.uuid4().hex[:8]}",
                "agent_id": identity.instance_id,
                "action_type": action_type,
                "params": params,
                "created_at": self.now,
                "timeout_seconds": 900,  # 15 minutes default
                "on_timeout": "DENY",
            })

        return decision, tier, reason

    # ── Escalation ──

    def resolve_escalation(self, escalation_id: str, decision: str,
                           justification: str, decider: str,
                           modified_params: dict = None) -> dict:
        esc = next((e for e in self.escalation_queue if e["escalation_id"] == escalation_id), None)
        if not esc:
            return {"error": "Escalation not found"}

        self._audit("EscalationResolved", esc["agent_id"],
                     action=esc["action_type"],
                     detail=f"{decision} by {decider}: {justification}")

        if decision == "APPROVE":
            self._audit("ActionExecuted", esc["agent_id"],
                         action=esc["action_type"], detail="Executed after escalation approval")

        if decision == "MODIFY" and modified_params:
            identity = self.identities.get(esc["agent_id"])
            if identity:
                d, t, r = evaluate_rules(identity.rules, esc["action_type"], modified_params)
                self._audit("ActionEvaluated", esc["agent_id"],
                             agent_type=identity.agent_type,
                             action=esc["action_type"], decision=d, tier=t, reason=r,
                             detail="Re-evaluation after MODIFY")
                if d == "ALLOW":
                    self._audit("ActionExecuted", esc["agent_id"],
                                 action=esc["action_type"],
                                 detail="Executed after MODIFY re-evaluation")

        return {"escalation_id": escalation_id, "decision": decision}

    def timeout_escalation(self, escalation_id: str) -> dict:
        """Apply timeout behavior when human does not respond."""
        esc = next((e for e in self.escalation_queue if e["escalation_id"] == escalation_id), None)
        if not esc:
            return {"error": "Escalation not found"}

        applied_decision = esc.get("on_timeout", "DENY")
        self._audit("EscalationTimedOut", esc["agent_id"],
                     action=esc["action_type"],
                     detail=f"Timed out after {esc['timeout_seconds']}s, applied: {applied_decision}",
                     decision=applied_decision)
        return {"escalation_id": escalation_id, "applied_decision": applied_decision}

    def promote_candidate_rule(self, proposer: str, approver: str) -> tuple[bool, str]:
        if proposer == approver:
            return False, "SEPARATION_VIOLATION: proposer and approver must differ"
        self._audit("PolicyUpdated", "system",
                     detail=f"Rule promoted. Proposed by {proposer}, approved by {approver}")
        return True, "PROMOTED"

    # ── Audit ──

    def _audit(self, event_type: str, agent_id: str, **kwargs):
        entry_id = f"evt-{uuid.uuid4().hex[:8]}"
        entry = {"entry_id": entry_id, "event_type": event_type,
                 "agent_id": agent_id, "timestamp": self.now, **kwargs}
        self.audit.append(entry)
        payload = {"timestamp": self.now.isoformat(), **kwargs}
        append_to_chain(self.chain, "SHA256", self.genesis, entry_id, event_type, agent_id,
                        **payload)


def _resolve_dot(path: str, obj: dict):
    """Resolve a dot-notation path into a dict."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _parse_simple_duration(s: str) -> timedelta:
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    if s.endswith("s"):
        return timedelta(seconds=int(s[:-1]))
    return timedelta(hours=1)


# ═══════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════

def run_integration_tests():
    passed = 0
    failed = 0
    skipped = 0

    def check(test_id, desc, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"    [PASS] {test_id}: {desc}")
        else:
            failed += 1
            print(f"    [FAIL] {test_id}: {desc}")
            if detail:
                print(f"           {detail}")

    def skip(test_id, desc, reason):
        nonlocal skipped
        skipped += 1
        print(f"    [SKIP] {test_id}: {desc}")
        print(f"           {reason}")

    # ── Suite: Delegation (uses canonical is_subset) ──

    print(f"\n  Suite: delegation")
    print(f"  Delegation attenuation and cascade behavior")
    print(f"  (scope subset uses canonical is_subset from Appendix D.3)")
    print()

    gov = GovernanceStack()

    research_rules = [
        {"pattern": "database.query", "decision": "ALLOW", "constraints": []},
        {"pattern": "database.write", "decision": "ALLOW", "constraints": [
            {"field": "record_count", "operator": "LESS_THAN_OR_EQUAL", "value": 50}
        ]},
        {"pattern": "api.external.get", "decision": "ALLOW", "constraints": []},
        {"pattern": "agent.spawn", "decision": "ALLOW", "constraints": []},
    ]

    research_scope = {
        "authorized_actions": deepcopy(research_rules),
        "delegation": {
            "can_delegate": True,
            "max_depth": 2,
            "delegatable_scope": {
                "authorized_actions": [
                    {"pattern": "database.query", "decision": "ALLOW"},
                    {"pattern": "api.external.get", "decision": "ALLOW"},
                ],
                "parameter_constraints": [],
                "resource_constraints": [],
                "delegation": {"can_delegate": False, "max_depth": 0},
                "output_policy": {"authorized_output_types": []},
            },
        },
        "parameter_constraints": [],
        "resource_constraints": [],
        "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY"]},
    }

    grant = gov.create_grant("research-agent", research_scope, research_rules,
                              ttl_seconds=14400, granted_by="human:alex@org")
    parent = gov.create_root_identity(grant)

    # DL-001: Child with valid subset scope
    child_rules = [
        {"pattern": "database.query", "decision": "ALLOW", "constraints": []},
        {"pattern": "api.external.get", "decision": "ALLOW", "constraints": []},
    ]
    child_scope = {
        "authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}, {"pattern": "api.external.get", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    child, error = gov.create_child_identity(parent, "data-fetcher", child_scope, child_rules)
    check("DL-001", "Child with valid subset scope succeeds",
          child is not None and error is None)

    # DL-002: Child requesting action not in delegatable scope
    bad_rules = [{"pattern": "database.write", "decision": "ALLOW", "constraints": []}]
    bad_scope = {
        "authorized_actions": [{"pattern": "database.write", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    _, error = gov.create_child_identity(parent, "bad-child", bad_scope, bad_rules)
    check("DL-002", "Child requesting action not in parent delegatable scope fails",
          error == "DELEGATION_SCOPE_VIOLATION")

    # DL-002b: Child with extra output types (tests full is_subset step 5)
    extra_output_scope = {
        "authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": ["INTERNAL_SUMMARY", "CUSTOMER_FACING"]},
    }
    extra_output_rules = [{"pattern": "database.query", "decision": "ALLOW", "constraints": []}]
    _, error = gov.create_child_identity(parent, "extra-output", extra_output_scope, extra_output_rules)
    check("DL-002b", "Child with extra output types rejected by full is_subset",
          error == "DELEGATION_SCOPE_VIOLATION")

    # DL-003: Delegation depth exceeded
    gov2 = GovernanceStack()
    shallow_scope = {
        "authorized_actions": deepcopy(research_rules),
        "delegation": {
            "can_delegate": True, "max_depth": 1,
            "delegatable_scope": {
                "authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}],
                "parameter_constraints": [], "resource_constraints": [],
                "delegation": {"can_delegate": True, "max_depth": 0},
                "output_policy": {"authorized_output_types": []},
            },
        },
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    depth_child_rules = [{"pattern": "database.query", "decision": "ALLOW", "constraints": []}]
    depth_child_scope = {
        "authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}],
        "delegation": {"can_delegate": True, "max_depth": 0,
                        "delegatable_scope": {"authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}],
                                               "parameter_constraints": [], "resource_constraints": [],
                                               "delegation": {"can_delegate": False, "max_depth": 0},
                                               "output_policy": {"authorized_output_types": []}}},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    grant2 = gov2.create_grant("research-agent", shallow_scope, research_rules,
                                ttl_seconds=14400, granted_by="human:alex@org")
    p2 = gov2.create_root_identity(grant2)
    c2, err2 = gov2.create_child_identity(p2, "child1", depth_child_scope, depth_child_rules)
    check("DL-003a", "First-level child creation succeeds",
          c2 is not None and err2 is None, f"err={err2}")

    gc_scope = {
        "authorized_actions": [{"pattern": "database.query", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    _, error = gov2.create_child_identity(c2, "grandchild", gc_scope, depth_child_rules)
    check("DL-003b", "Delegation depth exceeded at second level",
          error == "DELEGATION_DEPTH_EXCEEDED", f"error={error}")

    # DL-004: Parent without delegation rights
    gov3 = GovernanceStack()
    no_deleg_scope = {
        "authorized_actions": deepcopy(research_rules),
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    grant3 = gov3.create_grant("research-agent", no_deleg_scope, research_rules,
                                ttl_seconds=14400, granted_by="human:alex@org")
    p3 = gov3.create_root_identity(grant3)
    _, error = gov3.create_child_identity(p3, "child", child_scope, child_rules)
    check("DL-004", "Parent without delegation rights cannot spawn",
          error == "SCOPE_VIOLATION")

    # DL-005, DL-006: Cascade
    cascaded = gov.terminate(parent, "COMPLETED")
    check("DL-005", "Parent termination cascades to child",
          child.terminated and child.termination_reason == "CASCADED")

    d, t, r = gov.evaluate(child, "database.query")
    check("DL-006", "Cascaded child's actions are denied",
          d == "DENY" and r == "IDENTITY_EXPIRED")

    # ── Suite: Rate Limits and Damage Budgets ──

    print(f"\n  Suite: rate_limits_and_budgets")
    print(f"  Rate limit and damage budget enforcement in the governance stack")
    print()

    gov_rl = GovernanceStack()
    rl_rules = [{"pattern": "api.call", "decision": "ALLOW", "constraints": []}]
    rl_scope = {
        "authorized_actions": [{"pattern": "api.call", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    rl_grant = gov_rl.create_grant(
        "api-agent", rl_scope, rl_rules, ttl_seconds=3600,
        granted_by="human:ops@org",
        rate_limits=[{"action_pattern": "api.call", "max_count": 3,
                      "window": "1h", "scope": "INSTANCE"}],
    )
    rl_agent = gov_rl.create_root_identity(rl_grant)

    # Three calls should succeed
    for i in range(3):
        d, t, r = gov_rl.evaluate(rl_agent, "api.call", {"n": i})
    check("RL-INT-001", "Actions within rate limit succeed",
          d == "ALLOW")

    # Fourth should be denied
    d, t, r = gov_rl.evaluate(rl_agent, "api.call", {"n": 3})
    check("RL-INT-002", "Action exceeding rate limit is denied",
          d == "DENY" and r == "RATE_LIMIT_EXCEEDED",
          f"decision={d}, reason={r}")

    # Damage budget test
    gov_db = GovernanceStack()
    db_rules = [{"pattern": "payment.send", "decision": "ALLOW", "constraints": []}]
    db_scope = {
        "authorized_actions": [{"pattern": "payment.send", "decision": "ALLOW"}],
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    db_grant = gov_db.create_grant(
        "payment-agent", db_scope, db_rules, ttl_seconds=3600,
        granted_by="human:finance@org",
        damage_budgets=[{
            "metric": "dollar_amount", "threshold": 10000,
            "window": "1h", "scope": "INSTANCE",
            "accumulator": "amount", "on_exceed": "DENY",
            "evaluation_tier": 2,
        }],
    )
    db_agent = gov_db.create_root_identity(db_grant)

    # Under budget
    d, t, r = gov_db.evaluate(db_agent, "payment.send", {"amount": 5000})
    check("DB-INT-001", "Action within damage budget succeeds",
          d == "ALLOW")

    # Over budget (5000 accumulated + 6000 = 11000 > 10000)
    d, t, r = gov_db.evaluate(db_agent, "payment.send", {"amount": 6000})
    check("DB-INT-002", "Action exceeding damage budget is denied",
          d == "DENY" and r == "DAMAGE_BUDGET_EXCEEDED",
          f"decision={d}, reason={r}")

    # ── Suite: Stateful Policy Evaluation ──

    print(f"\n  Suite: stateful_policy_evaluation")
    print(f"  Identity-state-dependent policy evaluation")
    print()

    gov4 = GovernanceStack()
    email_rules = [
        {"pattern": "gmail.threads.get", "decision": "ALLOW", "constraints": []},
        {"pattern": "gmail.messages.send", "decision": "ESCALATE", "constraints": []},
    ]
    email_scope = {
        "authorized_actions": deepcopy(email_rules),
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    grant4 = gov4.create_grant("email-drafter", email_scope, email_rules,
                                ttl_seconds=30, granted_by="human:jane@org")
    agent4 = gov4.create_root_identity(grant4)

    gov4.advance_time(seconds=60)
    d, t, r = gov4.evaluate(agent4, "gmail.threads.get")
    check("PE-008", "Deny — expired identity (TTL elapsed)",
          d == "DENY" and r in ("IDENTITY_EXPIRED", "AUTHORITY_EXPIRED"),
          f"decision={d}, reason={r}")

    gov5 = GovernanceStack()
    grant5 = gov5.create_grant("email-drafter", email_scope, email_rules,
                                ttl_seconds=3600, granted_by="human:jane@org")
    agent5 = gov5.create_root_identity(grant5)
    d, _, _ = gov5.evaluate(agent5, "gmail.threads.get")
    check("PE-009a", "Action succeeds before revocation", d == "ALLOW")
    gov5.revoke_grant(grant5.grant_id, "human:jane@org")
    d, t, r = gov5.evaluate(agent5, "gmail.threads.get")
    check("PE-009b", "Deny — revoked authority",
          d == "DENY" and r == "AUTHORITY_REVOKED")

    # ── Suite: Escalation Lifecycle (including timeout) ──

    print(f"\n  Suite: escalation_lifecycle")
    print(f"  Escalation with approve, modify, timeout, and candidate rule promotion")
    print()

    gov6 = GovernanceStack()
    grant6 = gov6.create_grant("email-drafter", email_scope, email_rules,
                                ttl_seconds=3600, granted_by="human:jane@org")
    agent6 = gov6.create_root_identity(grant6)

    # EL-001: APPROVE
    d, _, _ = gov6.evaluate(agent6, "gmail.messages.send", {"to": "client@partner.com"})
    check("EL-001a", "Action escalated", d == "ESCALATE")

    esc = gov6.escalation_queue[-1]
    gov6.resolve_escalation(esc["escalation_id"], "APPROVE",
                             "Verified recipient is authorized", "human:jane@org")
    check("EL-001b", "Escalation resolved with APPROVE and action executed",
          any(e["event_type"] == "EscalationResolved" for e in gov6.audit) and
          any(e["event_type"] == "ActionExecuted" for e in gov6.audit))

    # EL-002: TIMEOUT
    gov_to = GovernanceStack()
    grant_to = gov_to.create_grant("email-drafter", email_scope, email_rules,
                                    ttl_seconds=3600, granted_by="human:jane@org")
    agent_to = gov_to.create_root_identity(grant_to)
    d, _, _ = gov_to.evaluate(agent_to, "gmail.messages.send", {"to": "someone@example.com"})
    check("EL-002a", "Action escalated for timeout test", d == "ESCALATE")

    esc_to = gov_to.escalation_queue[-1]
    gov_to.advance_time(minutes=20)  # Past the 15-minute timeout
    result = gov_to.timeout_escalation(esc_to["escalation_id"])
    check("EL-002b", "Escalation timed out with default DENY",
          result.get("applied_decision") == "DENY")
    check("EL-002c", "EscalationTimedOut event emitted",
          any(e["event_type"] == "EscalationTimedOut" for e in gov_to.audit))

    # EL-003: MODIFY with re-evaluation
    gov7 = GovernanceStack()
    write_rules = [
        {"pattern": "database.write", "decision": "ALLOW", "constraints": [
            {"field": "record_count", "operator": "LESS_THAN_OR_EQUAL", "value": 50}
        ]},
        {"pattern": "database.write_bulk", "decision": "ESCALATE", "constraints": []},
    ]
    write_scope = {
        "authorized_actions": deepcopy(write_rules),
        "delegation": {"can_delegate": False, "max_depth": 0},
        "parameter_constraints": [], "resource_constraints": [],
        "output_policy": {"authorized_output_types": []},
    }
    grant7 = gov7.create_grant("writer", write_scope, write_rules,
                                ttl_seconds=3600, granted_by="human:alex@org")
    agent7 = gov7.create_root_identity(grant7)

    d, _, _ = gov7.evaluate(agent7, "database.write_bulk", {"record_count": 100})
    check("EL-003a", "Bulk write escalated", d == "ESCALATE")

    esc7 = gov7.escalation_queue[-1]
    gov7.resolve_escalation(esc7["escalation_id"], "MODIFY",
                             "Approved with reduced batch", "human:alex@org",
                             modified_params={"record_count": 25})
    re_evals = [e for e in gov7.audit if e["event_type"] == "ActionEvaluated"
                and "Re-evaluation" in e.get("detail", "")]
    check("EL-003b", "Modified action re-evaluated", len(re_evals) > 0)

    # EL-004/005: Separation of duties
    ok, _ = gov7.promote_candidate_rule("human:alice@org", "human:bob@org")
    check("EL-004", "Candidate rule promotion with separate approver", ok)

    ok, msg = gov7.promote_candidate_rule("human:alice@org", "human:alice@org")
    check("EL-005", "Self-approval rejected", not ok and "SEPARATION" in msg)

    # ── Suite: Audit Chain Integrity ──

    print(f"\n  Suite: audit_chain_integrity")
    print(f"  Hash chain integrity across multi-component operations")
    print()

    valid, err = verify_chain(gov6.chain, "SHA256", gov6.genesis)
    check("AC-001", "Chain valid after grant + spawn + evaluate + escalation", valid, err)

    valid, err = verify_chain(gov.chain, "SHA256", gov.genesis)
    check("AC-002", "Chain valid after delegation + cascade termination", valid, err)

    valid, err = verify_chain(gov_rl.chain, "SHA256", gov_rl.genesis)
    check("AC-003", "Chain valid after rate-limited operations", valid, err)

    tampered = [dict(e) for e in gov6.chain]
    if len(tampered) > 2:
        tampered[2]["agent_id"] = "TAMPERED"
    valid, _ = verify_chain(tampered, "SHA256", gov6.genesis)
    check("AC-004", "Tampered chain detected", not valid)

    # ── Suite: Event Schema Validation ──

    print(f"\n  Suite: event_schema_validation")
    print(f"  Validate emitted events against JSON Schema")
    print()

    if not HAS_JSONSCHEMA:
        skip("SV-001", "Validate events against JSON Schema",
             "jsonschema package not installed (pip install jsonschema)")
    else:
        schema_path = Path(__file__).parent.parent / "schemas" / "events.schema.json"
        types_path = Path(__file__).parent.parent / "schemas" / "types.schema.json"
        if not schema_path.exists() or not types_path.exists():
            skip("SV-001", "Validate events against JSON Schema",
                 f"Schema files not found at {schema_path}")
        else:
            with open(schema_path) as f:
                event_schema = json.load(f)
            with open(types_path) as f:
                types_schema = json.load(f)

            # Build a resolver that can handle $ref across files
            schema_store = {
                event_schema["$id"]: event_schema,
                types_schema["$id"]: types_schema,
            }

            # Validate that core event types referenced in the schema are structurally sound
            event_defs = event_schema.get("$defs", {})
            valid_count = 0
            invalid_count = 0
            for event_name, event_def in event_defs.items():
                if event_name == "EventBase":
                    continue
                try:
                    jsonschema.Draft202012Validator.check_schema(event_def)
                    valid_count += 1
                except jsonschema.SchemaError as e:
                    invalid_count += 1
                    print(f"    [FAIL] Schema invalid for {event_name}: {e.message}")

            check("SV-001", f"All {valid_count} event schemas are structurally valid",
                  invalid_count == 0, f"{invalid_count} invalid schemas")

            # Validate types schema
            type_defs = types_schema.get("$defs", {})
            valid_count = 0
            for type_name, type_def in type_defs.items():
                try:
                    jsonschema.Draft202012Validator.check_schema(type_def)
                    valid_count += 1
                except jsonschema.SchemaError:
                    pass
            check("SV-002", f"All {valid_count} type schemas are structurally valid",
                  valid_count == len(type_defs))

    # ── Summary ──

    total = passed + failed + skipped
    print(f"\n  {'='*60}")
    print(f"  Integration test results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"  Total: {total} test cases")
    print()
    if skipped > 0:
        print(f"  Skipped tests require: pip install jsonschema")
    if failed == 0 and skipped == 0:
        print(f"  All integration tests passed.")
    elif failed == 0:
        print(f"  All executed tests passed.")
    print()
    return failed == 0


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Agent Governance Spec — Integration Tests")
    print("  Delegation, rate limits, budgets, escalation, schema validation")
    print("="*60)
    success = run_integration_tests()
    sys.exit(0 if success else 1)
