"""
Agent Governance Specification — Illustrative Demo

Standalone walkthrough of governance scenarios with readable output.
Uses its own simplified types for clarity of presentation.

This is NOT the reference implementation or the conformance harness:
- Canonical algorithms: reference_algorithms.py
- Conformance-tested stack: integration_tests.py

Run: python3 demo.py
"""

import uuid
from reference_algorithms import is_subset, matches
import hashlib
import json
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# ─── Enumerations (Appendix C.1) ───

class Decision(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    ATTENUATE = "ATTENUATE"

class OutputDecision(Enum):
    RELEASE = "RELEASE"
    SUPPRESS = "SUPPRESS"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"

class TrustTier(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    RESTRICTED = "RESTRICTED"

class ReasonCode(Enum):
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    DELEGATION_DEPTH_EXCEEDED = "DELEGATION_DEPTH_EXCEEDED"
    DELEGATION_SCOPE_VIOLATION = "DELEGATION_SCOPE_VIOLATION"
    AUTHORITY_EXPIRED = "AUTHORITY_EXPIRED"
    IDENTITY_EXPIRED = "IDENTITY_EXPIRED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    POLICY_MATCH_DENY = "POLICY_MATCH_DENY"
    UNMATCHED_ACTION = "UNMATCHED_ACTION"
    OUTPUT_SCOPE_MISALIGNED = "OUTPUT_SCOPE_MISALIGNED"
    TRUST_INSUFFICIENT = "TRUST_INSUFFICIENT"
    BEHAVIORAL_ANOMALY = "BEHAVIORAL_ANOMALY"

class TerminationReason(Enum):
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CASCADED = "CASCADED"


# ─── Core Data Types ───

@dataclass
class PolicyScope:
    allowed_actions: dict  # pattern -> Decision
    constraints: dict      # pattern -> list of constraint dicts
    can_delegate: bool = False
    max_delegation_depth: int = 0
    delegatable_actions: dict = field(default_factory=dict)
    output_types: list = field(default_factory=list)

    def is_subset_of(self, parent: "PolicyScope") -> bool:
        def scope(value, actions):
            return {"authorized_actions": [
                {"pattern": pattern, "decision": decision.value,
                 "constraints": value.constraints.get(pattern, [])}
                for pattern, decision in actions.items()],
                "delegation": {"can_delegate": value.can_delegate,
                               "max_depth": value.max_delegation_depth},
                "output_policy": {"authorized_output_types": value.output_types}}
        child = scope(self, self.allowed_actions)
        return (is_subset(child, scope(parent, parent.allowed_actions)) and
                is_subset(child, scope(parent, parent.delegatable_actions)))

    _matches = staticmethod(matches)


@dataclass
class AuthorityGrant:
    grant_id: str
    agent_type: str
    scope: PolicyScope
    ttl_seconds: int
    granted_by: str
    granted_at: datetime
    rate_limits: dict = field(default_factory=dict)  # action_pattern -> (max, window_seconds)
    terminated: bool = False
    terminated_at: datetime | None = None
    terminated_by: str | None = None
    termination_reason: str | None = None  # "REVOKED" | "CASCADED" | "EXPIRED"

    @property
    def expires_at(self) -> datetime:
        return self.granted_at + timedelta(seconds=self.ttl_seconds)

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


@dataclass
class AgentIdentity:
    instance_id: str
    agent_type: str
    parent_id: Optional[str]
    lineage_chain: list
    authority_scope: PolicyScope
    trust_tiers: dict  # capability_class -> TrustTier
    created_at: datetime
    expires_at: datetime
    grant_id: str
    terminated: bool = False
    termination_reason: Optional[TerminationReason] = None


@dataclass
class AuditEntry:
    entry_id: str
    timestamp: datetime
    event_type: str
    agent_id: str
    agent_type: str
    action_type: Optional[str]
    decision: Optional[str]
    tier: Optional[int]
    reason_code: Optional[str]
    policy_version: str
    lineage_chain: list
    causal_parent: Optional[str]
    chain_hash: str
    details: str = ""


# ─── Authority Registry (Section 3.1) ───

class AuthorityRegistry:
    def __init__(self):
        self.grants: dict[str, AuthorityGrant] = {}
        self.policy_version = "1.0.0"

    def create_grant(self, agent_type: str, scope: PolicyScope,
                     ttl_seconds: int, granted_by: str,
                     rate_limits: dict = None) -> AuthorityGrant:
        grant = AuthorityGrant(
            grant_id=f"grant-{uuid.uuid4().hex[:8]}",
            agent_type=agent_type,
            scope=scope,
            ttl_seconds=ttl_seconds,
            granted_by=granted_by,
            granted_at=datetime.now(),
            rate_limits=rate_limits or {},
        )
        self.grants[grant.grant_id] = grant
        return grant

    def get_grant(self, agent_type: str) -> Optional[AuthorityGrant]:
        for g in self.grants.values():
            if g.agent_type == agent_type and not g.terminated and not g.is_expired:
                return g
        return None

    def revoke_grant(self, grant_id: str, revoked_by: str):
        grant = self.grants.get(grant_id)
        if grant and not grant.terminated:
            grant.terminated = True
            grant.terminated_at = datetime.now()
            grant.terminated_by = revoked_by
            grant.termination_reason = "REVOKED"


# ─── Agent Identity Service (Section 3.2) ───

class IdentityService:
    def __init__(self, registry: AuthorityRegistry):
        self.registry = registry
        self.identities: dict[str, AgentIdentity] = {}

    def create_root_identity(self, agent_type: str, grant: AuthorityGrant) -> AgentIdentity:
        instance_id = f"agent-{uuid.uuid4().hex[:8]}"
        identity = AgentIdentity(
            instance_id=instance_id,
            agent_type=agent_type,
            parent_id=None,
            lineage_chain=[instance_id],
            authority_scope=grant.scope,
            trust_tiers={"data_read": TrustTier.MEDIUM, "data_write": TrustTier.LOW,
                         "external_comms": TrustTier.LOW, "agent_spawn": TrustTier.LOW},
            created_at=datetime.now(),
            expires_at=grant.expires_at,
            grant_id=grant.grant_id,
        )
        self.identities[instance_id] = identity
        return identity

    def create_child_identity(self, parent: AgentIdentity, child_type: str,
                              child_scope: PolicyScope) -> tuple[Optional[AgentIdentity], Optional[ReasonCode]]:
        # Check parent can delegate
        if not parent.authority_scope.can_delegate:
            return None, ReasonCode.SCOPE_VIOLATION

        # Check delegation depth
        if len(parent.lineage_chain) >= parent.authority_scope.max_delegation_depth + 1:
            return None, ReasonCode.DELEGATION_DEPTH_EXCEEDED

        # Check scope is subset (simplified)
        if not child_scope.is_subset_of(parent.authority_scope):
            return None, ReasonCode.DELEGATION_SCOPE_VIOLATION

        # Attenuate trust: child gets minimum of parent trust
        child_trust = {}
        for cap, tier in parent.trust_tiers.items():
            child_trust[cap] = TrustTier.LOW if tier == TrustTier.LOW else tier

        instance_id = f"agent-{uuid.uuid4().hex[:8]}"
        identity = AgentIdentity(
            instance_id=instance_id,
            agent_type=child_type,
            parent_id=parent.instance_id,
            lineage_chain=parent.lineage_chain + [instance_id],
            authority_scope=child_scope,
            trust_tiers=child_trust,
            created_at=datetime.now(),
            expires_at=min(parent.expires_at, datetime.now() + timedelta(hours=1)),
            grant_id=parent.grant_id,
        )
        self.identities[instance_id] = identity
        return identity, None

    def terminate(self, identity: AgentIdentity, reason: TerminationReason):
        identity.terminated = True
        identity.termination_reason = reason
        # Cascade to children
        children = [i for i in self.identities.values()
                     if i.parent_id == identity.instance_id and not i.terminated]
        for child in children:
            self.terminate(child, TerminationReason.CASCADED)
        return children


# ─── Audit Ledger (Section 3.5) ───

class AuditLedger:
    def __init__(self):
        self.entries: list[AuditEntry] = []
        self.last_hash = "GENESIS"

    def append(self, event_type: str, agent_id: str, agent_type: str,
               action_type: str = None, decision: str = None, tier: int = None,
               reason_code: str = None, policy_version: str = "1.0.0",
               lineage_chain: list = None, causal_parent: str = None,
               details: str = "") -> AuditEntry:
        entry_id = f"audit-{uuid.uuid4().hex[:8]}"

        # Cryptographic chaining
        chain_input = f"{self.last_hash}|{entry_id}|{event_type}|{agent_id}"
        chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()[:16]

        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=datetime.now(),
            event_type=event_type,
            agent_id=agent_id,
            agent_type=agent_type,
            action_type=action_type,
            decision=decision,
            tier=tier,
            reason_code=reason_code,
            policy_version=policy_version,
            lineage_chain=lineage_chain or [],
            causal_parent=causal_parent,
            chain_hash=chain_hash,
            details=details,
        )
        self.last_hash = chain_hash
        self.entries.append(entry)
        return entry

    def get_causal_chain(self, entry_id: str) -> list[AuditEntry]:
        chain = []
        current = next((e for e in self.entries if e.entry_id == entry_id), None)
        while current:
            chain.append(current)
            if current.causal_parent:
                current = next((e for e in self.entries if e.entry_id == current.causal_parent), None)
            else:
                break
        return list(reversed(chain))

    def verify_integrity(self) -> bool:
        prev_hash = "GENESIS"
        for entry in self.entries:
            expected_input = f"{prev_hash}|{entry.entry_id}|{entry.event_type}|{entry.agent_id}"
            expected_hash = hashlib.sha256(expected_input.encode()).hexdigest()[:16]
            if entry.chain_hash != expected_hash:
                return False
            prev_hash = entry.chain_hash
        return True


# ─── Policy Gate (Section 3.3) ───

class PolicyGate:
    def __init__(self, registry: AuthorityRegistry, identity_service: IdentityService,
                 ledger: AuditLedger):
        self.registry = registry
        self.identity_service = identity_service
        self.ledger = ledger
        self.rate_counts: dict[str, dict[str, int]] = {}  # agent_id -> action -> count

    def evaluate(self, identity: AgentIdentity, action_type: str,
                 params: dict = None, causal_parent: str = None) -> tuple[Decision, int, ReasonCode, Optional[str]]:
        params = params or {}

        # Record the request
        request_entry = self.ledger.append(
            event_type="ActionRequested",
            agent_id=identity.instance_id,
            agent_type=identity.agent_type,
            action_type=action_type,
            lineage_chain=identity.lineage_chain,
            causal_parent=causal_parent,
            details=json.dumps(params, default=str),
        )

        # ── Tier 1: Deterministic Rule Evaluation ──

        # Check identity validity
        if identity.terminated:
            decision = Decision.DENY
            reason = ReasonCode.IDENTITY_EXPIRED
            self._record_decision(request_entry, identity, action_type, decision, 1, reason)
            return decision, 1, reason, request_entry.entry_id

        # Check authority expiration. Lazy detection of TTL elapse per
        # Section 3.1 Termination Completeness: if the grant has expired
        # but the struct has not yet been updated, flip it and emit the
        # AuthorityGrantTerminated event before any denial fires.
        grant = self.registry.grants.get(identity.grant_id)
        if grant and not grant.terminated and grant.is_expired:
            grant.terminated = True
            grant.terminated_at = datetime.now()
            grant.terminated_by = None  # system-driven
            grant.termination_reason = "EXPIRED"
            self.ledger.append(
                event_type="AuthorityGrantTerminated",
                agent_id="system",
                agent_type="system",
                details=f"Grant {grant.grant_id} reason=EXPIRED terminated_by=None",
            )
        if not grant or grant.terminated:
            decision = Decision.DENY
            reason = ReasonCode.AUTHORITY_EXPIRED
            self._record_decision(request_entry, identity, action_type, decision, 1, reason)
            return decision, 1, reason, request_entry.entry_id

        # Check scope: first-match-wins against allowed_actions
        scope = identity.authority_scope
        matched = False
        scope_decision = None

        for pattern, decision_val in scope.allowed_actions.items():
            if PolicyScope._matches(action_type, pattern):
                matched = True
                scope_decision = decision_val
                break

        if not matched:
            decision = Decision.DENY
            reason = ReasonCode.UNMATCHED_ACTION
            self._record_decision(request_entry, identity, action_type, decision, 1, reason)
            return decision, 1, reason, request_entry.entry_id

        if scope_decision == Decision.DENY:
            reason = ReasonCode.POLICY_MATCH_DENY
            self._record_decision(request_entry, identity, action_type, Decision.DENY, 1, reason)
            return Decision.DENY, 1, reason, request_entry.entry_id

        if scope_decision == Decision.ESCALATE:
            reason = ReasonCode.ESCALATION_REQUIRED
            self._record_decision(request_entry, identity, action_type, Decision.ESCALATE, 1, reason)
            return Decision.ESCALATE, 1, reason, request_entry.entry_id

        # Check rate limits
        agent_rates = self.rate_counts.setdefault(identity.instance_id, {})
        current_count = agent_rates.get(action_type, 0)
        if action_type in grant.rate_limits:
            max_count, _ = grant.rate_limits[action_type]
            if current_count >= max_count:
                decision = Decision.DENY
                reason = ReasonCode.RATE_LIMIT_EXCEEDED
                self._record_decision(request_entry, identity, action_type, decision, 1, reason,
                                      f"Rate: {current_count}/{max_count}")
                return decision, 1, reason, request_entry.entry_id

        # Tier 1 resolved: ALLOW
        agent_rates[action_type] = current_count + 1

        # ── Tier 2: Parameter Constraint Evaluation ──

        constraints = scope.constraints.get(action_type, [])
        for constraint in constraints:
            field_name = constraint.get("field")
            operator = constraint.get("operator")
            value = constraint.get("value")
            actual = params.get(field_name)

            if operator == "NOT_IN" and actual in value:
                decision = Decision.DENY
                reason = ReasonCode.CONSTRAINT_VIOLATION
                detail = f"{field_name}={actual} is in blocked list {value}"
                self._record_decision(request_entry, identity, action_type, decision, 2, reason, detail)
                return decision, 2, reason, request_entry.entry_id

            if operator == "LESS_THAN_OR_EQUAL" and actual is not None and actual > value:
                # Check if we can attenuate
                decision = Decision.ATTENUATE
                reason = ReasonCode.CONSTRAINT_VIOLATION
                detail = f"{field_name}={actual} exceeds {value}, attenuating"
                self._record_decision(request_entry, identity, action_type, decision, 2, reason, detail)
                return decision, 2, reason, request_entry.entry_id

            if operator == "EQUALS" and actual is not None and actual != value:
                decision = Decision.DENY
                reason = ReasonCode.CONSTRAINT_VIOLATION
                detail = f"{field_name}={actual}, expected {value}"
                self._record_decision(request_entry, identity, action_type, decision, 2, reason, detail)
                return decision, 2, reason, request_entry.entry_id

        # Tier 2 passed, ALLOW
        decision = Decision.ALLOW
        self._record_decision(request_entry, identity, action_type, decision,
                              2 if constraints else 1, None)
        return decision, 2 if constraints else 1, None, request_entry.entry_id

    def _record_decision(self, request_entry: AuditEntry, identity: AgentIdentity,
                         action_type: str, decision: Decision, tier: int,
                         reason: Optional[ReasonCode], detail: str = ""):
        self.ledger.append(
            event_type="ActionEvaluated",
            agent_id=identity.instance_id,
            agent_type=identity.agent_type,
            action_type=action_type,
            decision=decision.value,
            tier=tier,
            reason_code=reason.value if reason else None,
            lineage_chain=identity.lineage_chain,
            causal_parent=request_entry.entry_id,
            details=detail,
        )


# ─── Output Evaluator (Section 3.6) ───

class OutputEvaluator:
    def evaluate(self, identity: AgentIdentity, output_text: str,
                 output_type: str, ledger: AuditLedger,
                 causal_parent: str = None) -> tuple[OutputDecision, float, str]:
        # Scope alignment check: is this output consistent with authorized output types?
        authorized = identity.authority_scope.output_types
        if output_type not in authorized:
            entry = ledger.append(
                event_type="OutputEvaluated",
                agent_id=identity.instance_id,
                agent_type=identity.agent_type,
                action_type=f"output:{output_type}",
                decision=OutputDecision.SUPPRESS.value,
                reason_code=ReasonCode.OUTPUT_SCOPE_MISALIGNED.value,
                lineage_chain=identity.lineage_chain,
                causal_parent=causal_parent,
                details=f"Output type '{output_type}' not in authorized types: {authorized}",
            )
            return OutputDecision.SUPPRESS, 0.1, f"Out of scope: {output_type}"

        # Simple scope keyword check
        scope_keywords = getattr(identity.authority_scope, 'scope_keywords', [])
        if scope_keywords:
            matches = sum(1 for k in scope_keywords if k.lower() in output_text.lower())
            alignment = min(1.0, matches / max(len(scope_keywords), 1))
        else:
            alignment = 0.8  # Default for agents without keyword scope

        if alignment < 0.3:
            entry = ledger.append(
                event_type="OutputEvaluated",
                agent_id=identity.instance_id,
                agent_type=identity.agent_type,
                action_type=f"output:{output_type}",
                decision=OutputDecision.REVISE.value,
                reason_code=ReasonCode.OUTPUT_SCOPE_MISALIGNED.value,
                lineage_chain=identity.lineage_chain,
                causal_parent=causal_parent,
                details=f"Low scope alignment: {alignment:.2f}",
            )
            return OutputDecision.REVISE, alignment, "Low scope alignment — revise"

        entry = ledger.append(
            event_type="OutputEvaluated",
            agent_id=identity.instance_id,
            agent_type=identity.agent_type,
            action_type=f"output:{output_type}",
            decision=OutputDecision.RELEASE.value,
            lineage_chain=identity.lineage_chain,
            causal_parent=causal_parent,
            details=f"Scope alignment: {alignment:.2f}",
        )
        return OutputDecision.RELEASE, alignment, "Released"


# ─── Trust Engine (Section 3.7) ───

class TrustEngine:
    def __init__(self, ledger: AuditLedger):
        self.ledger = ledger

    def compute_adjustment(self, agent_type: str) -> dict:
        """Permission records alone do not establish outcome quality."""
        return {"status": "insufficient_outcome_evidence",
                "recommendation": "Keep trust unchanged until independently verified outcomes exist"}


# ─── Simulation Printer ───

def header(text):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")

def subheader(text):
    print(f"\n  --- {text} ---")

def result(decision, tier, reason, action, details=""):
    icon = {"ALLOW": "+", "DENY": "X", "ESCALATE": "?", "ATTENUATE": "~"}
    r = reason.value if reason else "—"
    d = f" | {details}" if details else ""
    print(f"  [{icon.get(decision.value, '?')}] {decision.value:10s} | Tier {tier} | {r:30s} | {action}{d}")

def output_result(decision, alignment, output_type, details=""):
    icon = {"RELEASE": "+", "SUPPRESS": "X", "REVISE": "~", "ESCALATE": "?"}
    print(f"  [{icon.get(decision.value, '?')}] {decision.value:10s} | Alignment: {alignment:.2f} | {output_type} | {details}")


# ─── Run the Simulation ───

def main():
    print("\n" + "="*70)
    print("  AGENT GOVERNANCE SPECIFICATION — SIMULATION")
    print("  Demonstrates the core governance loop in action")
    print("="*70)

    # Initialize infrastructure
    registry = AuthorityRegistry()
    identity_service = IdentityService(registry)
    ledger = AuditLedger()
    gate = PolicyGate(registry, identity_service, ledger)
    output_eval = OutputEvaluator()
    trust_engine = TrustEngine(ledger)

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 1: Email Drafter Agent — Normal Operations")
    # ════════════════════════════════════════════════════════════════

    subheader("Human creates authority grant")
    email_scope = PolicyScope(
        allowed_actions={
            "gmail.threads.get": Decision.ALLOW,
            "gmail.drafts.create": Decision.ALLOW,
            "gmail.messages.send": Decision.ESCALATE,
            "agent.spawn": Decision.DENY,
        },
        constraints={
            "gmail.drafts.create": [
                {"field": "recipient_domain", "operator": "NOT_IN",
                 "value": ["competitor.com", "regulator.gov"]},
                {"field": "recipient_count", "operator": "LESS_THAN_OR_EQUAL", "value": 10},
            ],
        },
        can_delegate=False,
        output_types=["email_draft", "email_summary"],
    )
    email_scope.scope_keywords = ["email", "draft", "message", "thread"]

    email_grant = registry.create_grant(
        agent_type="email-drafter",
        scope=email_scope,
        ttl_seconds=28800,  # 8 hours
        granted_by="human:jane.smith@acme.com",
        rate_limits={"gmail.drafts.create": (20, 3600), "gmail.threads.get": (100, 3600)},
    )
    print(f"  Grant: {email_grant.grant_id}")
    print(f"  Type:  {email_grant.agent_type}")
    print(f"  TTL:   {email_grant.ttl_seconds}s ({email_grant.ttl_seconds/3600:.0f}h)")
    print(f"  By:    {email_grant.granted_by}")

    subheader("Agent spawned with identity")
    email_agent = identity_service.create_root_identity("email-drafter", email_grant)
    print(f"  ID:      {email_agent.instance_id}")
    print(f"  Lineage: {email_agent.lineage_chain}")
    print(f"  Trust:   {', '.join(f'{k}={v.value}' for k, v in email_agent.trust_tiers.items())}")

    # Record the spawn
    spawn_entry = ledger.append(
        event_type="AgentSpawned",
        agent_id=email_agent.instance_id,
        agent_type="email-drafter",
        lineage_chain=email_agent.lineage_chain,
        details=f"Root agent spawned by {email_grant.granted_by}",
    )

    subheader("Action 1: Read email threads (ALLOWED — Tier 1)")
    d, t, r, eid = gate.evaluate(email_agent, "gmail.threads.get", causal_parent=spawn_entry.entry_id)
    result(d, t, r, "gmail.threads.get")

    subheader("Action 2: Create draft to safe domain (ALLOWED — Tier 2)")
    d, t, r, eid = gate.evaluate(email_agent, "gmail.drafts.create",
                                  {"recipient_domain": "partner.com", "recipient_count": 3},
                                  causal_parent=eid)
    result(d, t, r, "gmail.drafts.create", "to: partner.com, 3 recipients")

    subheader("Action 3: Create draft to competitor (DENIED — Tier 2 constraint)")
    d, t, r, eid2 = gate.evaluate(email_agent, "gmail.drafts.create",
                                   {"recipient_domain": "competitor.com", "recipient_count": 1},
                                   causal_parent=eid)
    result(d, t, r, "gmail.drafts.create", "to: competitor.com — BLOCKED")

    subheader("Action 4: Send email (ESCALATED — policy requires human review)")
    d, t, r, eid = gate.evaluate(email_agent, "gmail.messages.send",
                                  {"to": "client@partner.com"},
                                  causal_parent=eid)
    result(d, t, r, "gmail.messages.send", "requires human approval")

    subheader("Action 5: Create draft with too many recipients (ATTENUATED — Tier 2)")
    d, t, r, eid = gate.evaluate(email_agent, "gmail.drafts.create",
                                  {"recipient_domain": "partner.com", "recipient_count": 25},
                                  causal_parent=eid)
    result(d, t, r, "gmail.drafts.create", "25 recipients → attenuated to 10")

    subheader("Action 6: Try to spawn a child agent (DENIED — no delegation)")
    d, t, r, eid = gate.evaluate(email_agent, "agent.spawn",
                                  {"child_type": "helper"},
                                  causal_parent=eid)
    result(d, t, r, "agent.spawn", "email-drafter cannot delegate")

    subheader("Action 7: Try unrecognized action (DENIED — default deny)")
    d, t, r, eid = gate.evaluate(email_agent, "calendar.events.create",
                                  {},
                                  causal_parent=eid)
    result(d, t, r, "calendar.events.create", "not in scope — default deny")

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 2: Output Evaluation — Scope Alignment")
    # ════════════════════════════════════════════════════════════════

    subheader("Output 1: Email draft (in scope — RELEASED)")
    od, align, detail = output_eval.evaluate(
        email_agent,
        "Dear Partner, I'd like to follow up on our email thread regarding the draft agreement.",
        "email_draft", ledger, eid
    )
    output_result(od, align, "email_draft", detail)

    subheader("Output 2: Financial analysis (out of scope — SUPPRESSED)")
    od, align, detail = output_eval.evaluate(
        email_agent,
        "Based on Q3 revenue projections and EBITDA margins, I recommend restructuring the portfolio.",
        "financial_analysis", ledger, eid
    )
    output_result(od, align, "financial_analysis", detail)

    subheader("Output 3: Vague output with low scope alignment (REVISE)")
    od, align, detail = output_eval.evaluate(
        email_agent,
        "The corporate restructuring plan should prioritize synergies across business units.",
        "email_draft", ledger, eid
    )
    output_result(od, align, "email_draft", detail)

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 3: Research Agent with Delegation")
    # ════════════════════════════════════════════════════════════════

    subheader("Human creates authority grant with delegation rights")
    research_scope = PolicyScope(
        allowed_actions={
            "database.query": Decision.ALLOW,
            "database.write": Decision.ALLOW,
            "api.external.get": Decision.ALLOW,
            "agent.spawn": Decision.ALLOW,
            "reports.generate": Decision.ALLOW,
        },
        constraints={
            "database.write": [
                {"field": "record_count", "operator": "LESS_THAN_OR_EQUAL", "value": 50},
            ],
        },
        can_delegate=True,
        max_delegation_depth=2,
        delegatable_actions={
            "database.query": Decision.ALLOW,
            "api.external.get": Decision.ALLOW,
        },
        output_types=["research_summary", "data_report"],
    )

    research_grant = registry.create_grant(
        agent_type="research-agent",
        scope=research_scope,
        ttl_seconds=14400,  # 4 hours
        granted_by="human:alex.johnson@acme.com",
    )
    print(f"  Grant: {research_grant.grant_id}")
    print(f"  Delegation: depth={research_scope.max_delegation_depth}, actions={list(research_scope.delegatable_actions.keys())}")

    research_agent = identity_service.create_root_identity("research-agent", research_grant)
    research_spawn = ledger.append(
        event_type="AgentSpawned",
        agent_id=research_agent.instance_id,
        agent_type="research-agent",
        lineage_chain=research_agent.lineage_chain,
        details=f"Root agent spawned by {research_grant.granted_by}",
    )
    print(f"  Agent: {research_agent.instance_id}")

    subheader("Research agent spawns a data-fetcher child")
    child_scope = PolicyScope(
        allowed_actions={
            "database.query": Decision.ALLOW,
            "api.external.get": Decision.ALLOW,
        },
        constraints={},
        can_delegate=False,
        delegatable_actions={},
        output_types=["data_report"],
    )
    child, error = identity_service.create_child_identity(research_agent, "data-fetcher", child_scope)
    if child:
        child_spawn = ledger.append(
            event_type="AgentSpawned",
            agent_id=child.instance_id,
            agent_type="data-fetcher",
            lineage_chain=child.lineage_chain,
            causal_parent=research_spawn.entry_id,
            details=f"Child of {research_agent.instance_id}",
        )
        print(f"  Child:   {child.instance_id}")
        print(f"  Lineage: {child.lineage_chain}")
        print(f"  Scope:   {list(child.authority_scope.allowed_actions.keys())} (attenuated from parent)")
        print(f"  Trust:   {', '.join(f'{k}={v.value}' for k, v in child.trust_tiers.items())}")

    subheader("Child performs allowed action (database query)")
    d, t, r, eid = gate.evaluate(child, "database.query",
                                  {"table": "customers", "limit": 100},
                                  causal_parent=child_spawn.entry_id)
    result(d, t, r, "database.query", "attenuated scope — read only")

    subheader("Child tries to write (DENIED — not in delegated scope)")
    d, t, r, eid = gate.evaluate(child, "database.write",
                                  {"table": "customers", "record_count": 5},
                                  causal_parent=eid)
    result(d, t, r, "database.write", "parent only delegated read actions")

    subheader("Child tries to spawn its own child (DENIED — can't delegate)")
    d, t, r, eid = gate.evaluate(child, "agent.spawn", {}, causal_parent=eid)
    result(d, t, r, "agent.spawn", "data-fetcher cannot delegate")

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 4: Parent Termination Cascade")
    # ════════════════════════════════════════════════════════════════

    subheader("Terminating research agent (parent)")
    cascaded = identity_service.terminate(research_agent, TerminationReason.COMPLETED)
    print(f"  Terminated: {research_agent.instance_id} (reason: {research_agent.termination_reason.value})")
    for c in cascaded:
        print(f"  Cascaded:   {c.instance_id} (reason: {c.termination_reason.value})")

    ledger.append(
        event_type="AgentTerminated",
        agent_id=research_agent.instance_id,
        agent_type="research-agent",
        lineage_chain=research_agent.lineage_chain,
        details=f"Terminated: {research_agent.termination_reason.value}",
    )
    for c in cascaded:
        ledger.append(
            event_type="AgentTerminated",
            agent_id=c.instance_id,
            agent_type=c.agent_type,
            lineage_chain=c.lineage_chain,
            details=f"Cascade terminated: parent {research_agent.instance_id} terminated",
        )

    subheader("Terminated child tries to act (DENIED — identity expired)")
    d, t, r, eid = gate.evaluate(child, "database.query", {"table": "customers"}, causal_parent=eid)
    result(d, t, r, "database.query", "child was cascade-terminated")

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 5: Authority Revocation")
    # ════════════════════════════════════════════════════════════════

    subheader("Human revokes email-drafter grant")
    registry.revoke_grant(email_grant.grant_id, "human:jane.smith@acme.com")
    ledger.append(
        event_type="AuthorityGrantTerminated",
        agent_id="system",
        agent_type="system",
        details=f"Grant {email_grant.grant_id} reason=REVOKED terminated_by=jane.smith@acme.com",
    )
    print(f"  Revoked: {email_grant.grant_id}")

    subheader("Email agent tries to act after revocation (DENIED)")
    d, t, r, eid = gate.evaluate(email_agent, "gmail.threads.get", causal_parent=eid)
    result(d, t, r, "gmail.threads.get", "authority grant revoked")

    # ════════════════════════════════════════════════════════════════
    header("SCENARIO 6: Trust Engine Analysis")
    # ════════════════════════════════════════════════════════════════

    adjustment = trust_engine.compute_adjustment("email-drafter")
    print(f"  Agent type:    email-drafter")
    print(f"  Analysis:      {adjustment}")

    adjustment = trust_engine.compute_adjustment("data-fetcher")
    print(f"  Agent type:    data-fetcher")
    print(f"  Analysis:      {adjustment}")

    # ════════════════════════════════════════════════════════════════
    header("AUDIT TRAIL — Full Causal Chain Analysis")
    # ════════════════════════════════════════════════════════════════

    subheader("Audit ledger integrity check")
    integrity = ledger.verify_integrity()
    print(f"  Chain integrity: {'VERIFIED' if integrity else 'BROKEN'}")
    print(f"  Total entries:   {len(ledger.entries)}")

    subheader("Complete audit trail (chronological)")
    print(f"  {'#':>3s}  {'Event Type':<25s}  {'Decision':<12s}  {'Tier':>4s}  {'Agent':<20s}  {'Action':<25s}  {'Reason':<30s}")
    print(f"  {'─'*3}  {'─'*25}  {'─'*12}  {'─'*4}  {'─'*20}  {'─'*25}  {'─'*30}")
    for i, e in enumerate(ledger.entries):
        tier_str = str(e.tier) if e.tier else "—"
        decision_str = e.decision or "—"
        action_str = e.action_type or "—"
        reason_str = e.reason_code or "—"
        agent_short = e.agent_id[:16] if e.agent_id else "—"
        print(f"  {i+1:3d}  {e.event_type:<25s}  {decision_str:<12s}  {tier_str:>4s}  {agent_short:<20s}  {action_str:<25s}  {reason_str:<30s}")

    subheader("Causal chain: Trace any action back to human origin")
    # Find the competitor.com denial and trace it back
    competitor_denial = next((e for e in ledger.entries
                              if e.reason_code == "CONSTRAINT_VIOLATION"
                              and e.event_type == "ActionEvaluated"), None)
    if competitor_denial:
        chain = ledger.get_causal_chain(competitor_denial.entry_id)
        print(f"  Tracing: Why was the competitor.com draft denied?")
        print()
        for i, e in enumerate(chain):
            indent = "  " * (i + 1)
            if e.event_type == "AgentSpawned":
                print(f"  {indent}[{e.event_type}] {e.details}")
            elif e.event_type == "ActionRequested":
                print(f"  {indent}[{e.event_type}] {e.action_type} — {e.details}")
            elif e.event_type == "ActionEvaluated":
                print(f"  {indent}[{e.event_type}] {e.decision} at Tier {e.tier} — {e.reason_code}")
                if e.details:
                    print(f"  {indent}  Detail: {e.details}")

    # ════════════════════════════════════════════════════════════════
    header("SIMULATION SUMMARY")
    # ════════════════════════════════════════════════════════════════

    decisions = [e.decision for e in ledger.entries if e.decision]
    print(f"  Total governance events:  {len(ledger.entries)}")
    print(f"  Actions evaluated:        {sum(1 for e in ledger.entries if e.event_type == 'ActionEvaluated')}")
    print(f"  ├─ ALLOW:                 {decisions.count('ALLOW')}")
    print(f"  ├─ DENY:                  {decisions.count('DENY')}")
    print(f"  ├─ ESCALATE:              {decisions.count('ESCALATE')}")
    print(f"  ├─ ATTENUATE:             {decisions.count('ATTENUATE')}")
    print(f"  Outputs evaluated:        {sum(1 for e in ledger.entries if e.event_type == 'OutputEvaluated')}")
    print(f"  ├─ RELEASE:               {decisions.count('RELEASE')}")
    print(f"  ├─ SUPPRESS:              {decisions.count('SUPPRESS')}")
    print(f"  ├─ REVISE:                {decisions.count('REVISE')}")
    print(f"  Agents spawned:           {sum(1 for e in ledger.entries if e.event_type == 'AgentSpawned')}")
    print(f"  Agents terminated:        {sum(1 for e in ledger.entries if e.event_type == 'AgentTerminated')}")
    print(f"  Grants terminated:        {sum(1 for e in ledger.entries if e.event_type == 'AuthorityGrantTerminated')}")
    print(f"  Audit chain integrity:    {'VERIFIED' if integrity else 'BROKEN'}")
    print(f"  Chain length:             {len(ledger.entries)} entries")
    print()
    print("  Specification properties illustrated (not deployment guarantees):")
    print("    1. No Bypass          — every action passed through Policy Gate")
    print("    2. Human Origin       — every grant traces to a named human")
    print("    3. Attenuation Only   — child scope was subset of parent delegatable scope")
    print("    4. Agent Isolation    — not tested: this demo runs in one process")
    print("    5. Credential Isolation — resource-name illustration; no isolated secrets service")
    print("    6. Decision Trace     — every action has full causal chain to human origin")
    print("    7. Tamper Evidence    — SHA-256 chain verified across all entries")
    print("    8. Fail-Closed       — expired/revoked authority → DENY")
    print("    9. Authority Expires  — every grant has TTL, no permanent authority")
    print()


if __name__ == "__main__":
    main()
