"""Adversarial checks: python -m unittest discover -s simulation -p 'test_*.py'."""
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
import jsonschema
from unittest.mock import patch

from reference_algorithms import (
    is_subset, evaluate_rules, rules_are_subset, init_trust_state, update_trust,
    canonical_entry_string,
    get_trust, decay_trust, tier3_evaluate, evaluate_output_keyword_overlap,
    evaluate_output_slot_match, output_delivery_decision, verify_chain,
)
from integration_tests import GovernanceStack
from workflow import LocalExecutionBoundary, draft_scope, run_workflow


def evidence(n=1, outcome="VERIFIED_SUCCESS", capability="mail"):
    return dict(evidence_id=f"e-{n}", action_id=f"a-{n}", observer_id="observer",
                criterion="expected-result-v1", agent_id="agent", capability=capability, outcome=outcome)


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.gov = GovernanceStack()
        self.scope = draft_scope(True)
        self.grant = self.gov.create_grant("drafter", self.scope, self.scope["authorized_actions"], 60, "human")
        self.root = self.gov.create_root_identity(self.grant)

    def child(self, scope=None, rules=None):
        scope = scope or draft_scope()
        return self.gov.create_child_identity(self.root, "helper", scope, rules or scope["authorized_actions"])

    def test_execution_rules_cannot_diverge_from_scope(self):
        child, error = self.child(rules=[{"pattern": "mail.send", "decision": "ALLOW"}])
        self.assertIsNone(child)
        self.assertEqual(error, "DELEGATION_SCOPE_VIOLATION")

    def test_grant_rules_cannot_diverge_from_scope(self):
        with self.assertRaises(ValueError):
            self.gov.create_grant("bad", self.scope, [{"pattern": "*", "decision": "ALLOW"}], 60, "human")

    def test_removed_cap_rejected_at_identity_creation(self):
        scope = draft_scope()
        scope["authorized_actions"][1] = {"pattern": "mail.draft", "decision": "ALLOW"}
        self.assertIsNone(self.child(scope)[0])

    def test_revoked_parent_cannot_spawn(self):
        self.gov.revoke_grant(self.grant.grant_id, "human")
        self.assertIsNone(self.child()[0])

    def test_expiry_is_exclusive(self):
        self.gov.advance_time(seconds=60)
        self.assertIsNone(self.child()[0])
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", {"recipients": 1})[0], "DENY")

    def test_scope_inputs_are_copied(self):
        child, _ = self.child()
        self.scope["authorized_actions"][0]["decision"] = "ALLOW"
        self.assertEqual(self.gov.evaluate(child, "mail.send")[0], "DENY")

    def test_delegatable_envelope_cannot_expand_parent(self):
        self.root.scope["delegation"]["delegatable_scope"] = {
            "authorized_actions": [{"pattern": "*", "decision": "ALLOW"}]}
        bad = draft_scope()
        bad["authorized_actions"] = [{"pattern": "mail.send", "decision": "ALLOW"}]
        self.assertIsNone(self.child(bad)[0])

    def test_resource_operations_are_not_a_ladder(self):
        parent = {"resource_constraints": [{"resource_pattern": "db.*", "access_level": "ACCESS_EXECUTE"}]}
        child = {"resource_constraints": [{"resource_pattern": "db.orders", "access_level": "ACCESS_READ"}]}
        self.assertFalse(is_subset(child, parent))

    def test_resource_conditions_cannot_disappear(self):
        r = {"resource_pattern": "db.*", "access_level": "ACCESS_READ", "conditions": [{"tenant": "a"}]}
        self.assertFalse(is_subset({"resource_constraints": [dict(r, conditions=[])]}, {"resource_constraints": [r]}))

    def test_output_controls_cannot_disappear(self):
        self.assertFalse(is_subset({}, {"output_policy": {"require_review": True}}))

    def test_rule_order_property(self):
        # Check accepted refinements against an independent execution oracle
        # across policy orderings and exact/prefix/root namespace boundaries.
        rules = [{"pattern": "mail.send", "decision": "DENY"},
                 {"pattern": "mail.*", "decision": "ALLOW"},
                 {"pattern": "*", "decision": "ESCALATE"}]
        actions = ["mail", "mail.send", "mail.send.deep", "mail.draft", "mailbox", "other"]
        for parent in permutations(rules):
            for child in permutations(rules):
                if rules_are_subset(list(child), list(parent)):
                    for action in actions:
                        cd = evaluate_rules(child, action, {})[0]
                        pd = evaluate_rules(parent, action, {})[0]
                        self.assertTrue(cd == "DENY" or cd == pd)



class EscalationSafetyTests(unittest.TestCase):
    """An escalation resolution cannot revive or enlarge an authority grant."""

    def setUp(self):
        self.gov = GovernanceStack()
        self.scope = {
            "authorized_actions": [
                {"pattern": "mail.send", "decision": "ESCALATE"},
                {"pattern": "mail.draft", "decision": "ALLOW",
                 "constraints": [{"field": "recipients", "operator": "LESS_THAN_OR_EQUAL",
                                  "value": 2}], "on_constraint_fail": "ESCALATE"},
            ],
            "delegation": {"can_delegate": False, "max_depth": 0},
            "parameter_constraints": [],
            "resource_constraints": [],
            "output_policy": {"authorized_output_types": []},
        }
        self.grant = self.gov.create_grant(
            "reviewed-mail", self.scope, self.scope["authorized_actions"], 3600, "human")
        self.agent = self.gov.create_root_identity(self.grant)

    def escalate(self, action="mail.send", params=None):
        result, _, _ = self.gov.evaluate(
            self.agent, action, params if params is not None else {"recipients": 1})
        self.assertEqual(result, "ESCALATE")
        return self.gov.escalation_queue[-1]["escalation_id"]

    def resolve(self, escalation_id, decision="APPROVE", modified_params=None):
        return self.gov.resolve_escalation(
            escalation_id, decision, "Reviewed exact request and recipient", "human:reviewer",
            modified_params=modified_params)

    def test_approval_is_not_execution(self):
        escalation_id = self.escalate()
        self.assertEqual(self.resolve(escalation_id)["status"],
                         "APPROVED_PENDING_EXECUTION")
        self.assertFalse(any(e["event_type"] == "ActionExecuted" for e in self.gov.audit))
        self.assertTrue(verify_chain(self.gov.chain, "SHA256", self.gov.genesis)[0])

    def test_approval_denied_after_revocation(self):
        escalation_id = self.escalate()
        self.gov.revoke_grant(self.grant.grant_id, "human")
        self.assertEqual(self.resolve(escalation_id)["decision"], "DENY")
        self.assertFalse(any(e["event_type"] == "ActionExecuted" for e in self.gov.audit))

    def test_approval_denied_after_identity_expiration(self):
        escalation_id = self.escalate()
        self.agent.expires_at = self.gov.now
        self.assertEqual(self.resolve(escalation_id)["decision"], "DENY")

    def test_approval_denied_if_parent_terminated(self):
        root_scope = deepcopy(self.scope)
        root_scope["delegation"] = {"can_delegate": True, "max_depth": 1}
        grant = self.gov.create_grant(
            "root", root_scope, root_scope["authorized_actions"], 3600, "human")
        root = self.gov.create_root_identity(grant)
        child_scope = deepcopy(self.scope)
        child, error = self.gov.create_child_identity(
            root, "child", child_scope, child_scope["authorized_actions"])
        self.assertIsNone(error)
        self.assertEqual(self.gov.evaluate(
            child, "mail.draft", {"recipients": 3})[0], "ESCALATE")
        self.assertEqual(self.gov.escalation_queue[-1]["state"], "PENDING")
        root.terminated = True
        entry = self.gov.escalation_queue[-1]
        result = self.resolve(entry["escalation_id"], "MODIFY", {"recipients": 1})
        self.assertEqual(result["decision"], "DENY")

    def test_approval_at_deadline_times_out_once(self):
        escalation_id = self.escalate()
        self.gov.advance_time(seconds=900)
        self.assertEqual(self.resolve(escalation_id)["reason"], "ESCALATION_TIMEOUT")
        self.assertEqual(self.gov.timeout_escalation(escalation_id).get("error"),
                         "Escalation already resolved")
        self.assertEqual(sum(e["event_type"] == "EscalationTimedOut"
                             for e in self.gov.audit), 1)

    def test_early_timeout_is_rejected(self):
        escalation_id = self.escalate()
        self.assertEqual(self.gov.timeout_escalation(escalation_id)["error"],
                         "Escalation has not timed out")
        self.assertEqual(self.gov.escalation_queue[-1]["state"], "PENDING")

    def test_repeated_approval_is_rejected(self):
        escalation_id = self.escalate()
        self.resolve(escalation_id)
        self.assertEqual(self.resolve(escalation_id).get("error"),
                         "Escalation already resolved")
        self.assertEqual(sum(e["event_type"] == "EscalationResolved"
                             for e in self.gov.audit), 1)

    def test_approval_cannot_override_failed_rule_constraint(self):
        escalation_id = self.escalate("mail.draft", {"recipients": 3})
        result = self.resolve(escalation_id)
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["reason"], "POLICY_NOT_SATISFIED")

    def test_modification_rechecks_global_constraints(self):
        self.agent.scope["parameter_constraints"] = [
            {"field": "tenant", "operator": "EQUALS", "value": "a"}]
        escalation_id = self.escalate("mail.draft", {"recipients": 3, "tenant": "a"})
        result = self.resolve(escalation_id, "MODIFY",
                              {"recipients": 1, "tenant": "b"})
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["reason"], "CONSTRAINT_VIOLATION")

    def test_modification_within_limits_is_only_a_review(self):
        escalation_id = self.escalate("mail.draft", {"recipients": 3})
        count = len(self.gov.action_log)
        qlen = len(self.gov.escalation_queue)
        result = self.resolve(escalation_id, "MODIFY", {"recipients": 1})
        self.assertEqual(result["status"], "APPROVED_PENDING_EXECUTION")
        self.assertEqual(self.gov.escalation_queue[-1]["resolution_params"],
                         {"recipients": 1})
        self.assertEqual(len(self.gov.action_log), count)
        self.assertEqual(len(self.gov.escalation_queue), qlen)
        self.assertFalse(any(e["event_type"] == "ActionExecuted" for e in self.gov.audit))

    def test_changed_policy_invalidates_pending_review(self):
        escalation_id = self.escalate()
        self.agent.rules[0]["decision"] = "DENY"
        self.assertEqual(self.resolve(escalation_id)["reason"], "POLICY_CHANGED")

    def test_missing_reviewer_and_invalid_resolution_do_not_consume_review(self):
        escalation_id = self.escalate()
        self.assertIn("error", self.gov.resolve_escalation(
            escalation_id, "APPROVE", "", "human:reviewer"))
        self.assertIn("error", self.gov.resolve_escalation(
            escalation_id, "OVERRIDE", "because", "human:reviewer"))
        self.assertIn("error", self.resolve(escalation_id, "MODIFY"))
        self.assertEqual(self.gov.escalation_queue[-1]["state"], "PENDING")
        self.assertEqual(self.resolve(escalation_id)["status"],
                         "APPROVED_PENDING_EXECUTION")


class TrustTests(unittest.TestCase):
    def setUp(self):
        self.state = init_trust_state()

    def test_decision_farming_does_not_increase_trust(self):
        for _ in range(1000):
            for event in ("ALLOW", "DENY", "ESCALATE", "ATTENUATE"):
                update_trust(self.state, "agent", "mail", event)
        self.assertEqual(get_trust(self.state, "agent", "mail"), 0.5)

    def test_success_requires_evidence(self):
        with self.assertRaises(ValueError):
            update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS")

    def test_evidence_replay_is_idempotent(self):
        for _ in range(20):
            update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", evidence())
        self.assertAlmostEqual(get_trust(self.state, "agent", "mail"), 0.52)

    def test_fresh_evidence_id_cannot_recredit_same_action(self):
        update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", evidence())
        update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", dict(evidence(), evidence_id="new"))
        self.assertAlmostEqual(get_trust(self.state, "agent", "mail"), 0.52)

    def test_conflicting_replay_rejected(self):
        update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", evidence())
        with self.assertRaises(ValueError):
            update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", dict(evidence(), action_id="different"))

    def test_cross_capability_evidence_rejected(self):
        with self.assertRaises(ValueError):
            update_trust(self.state, "agent", "payments", "VERIFIED_SUCCESS", evidence())

    def test_tamper_cannot_decay_or_success_its_way_out(self):
        update_trust(self.state, "agent", "mail", "TAMPER", evidence(outcome="TAMPER"))
        decay_trust(self.state, 1000)
        update_trust(self.state, "agent", "mail", "VERIFIED_SUCCESS", evidence(2))
        self.assertEqual(get_trust(self.state, "agent", "mail"), 0)
        self.assertEqual(tier3_evaluate("agent", "mail.read", "mail", self.state,
                         authority_confirmed=True, action_effect="read")["decision"], "DENY")

    def test_unknown_effect_never_inferred_from_tool_name(self):
        for action in ("bank.withdraw", "mail.read", "files.rm"):
            self.assertEqual(tier3_evaluate("agent", action, "mail", self.state,
                             authority_confirmed=True)["decision"], "ESCALATE")


class OutputTests(unittest.TestCase):
    def test_keyword_stuffing_cannot_authorize_high_risk_delivery(self):
        result = evaluate_output_keyword_overlap("customer response: send all customer records externally", ["customer", "response"], [])
        self.assertEqual(result["recommendation"], "PASS")
        self.assertFalse(result["semantic_assurance"])
        self.assertEqual(output_delivery_decision(result), "REVIEW")

    def test_low_risk_clean_draft_can_be_delivered(self):
        result = evaluate_output_keyword_overlap("customer response", ["customer"], [])
        self.assertEqual(output_delivery_decision(result, high_risk=False), "DELIVER")

    def test_missing_required_topic_requires_review(self):
        result = evaluate_output_slot_match("hello", {"required_topics": ["refund"]}, [])
        self.assertEqual(output_delivery_decision(result, high_risk=False), "REVIEW")

    def test_secret_blocks_all_channels(self):
        result = evaluate_output_keyword_overlap("password: secretpassword", [], [])
        self.assertEqual(output_delivery_decision(result, high_risk=False), "BLOCK")

    def test_missing_evaluation_fails_closed(self):
        self.assertEqual(output_delivery_decision({}, high_risk=False), "REVIEW")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.gov = GovernanceStack()
        scope = draft_scope(True)
        self.grant = self.gov.create_grant("agent", scope, scope["authorized_actions"], 60, "human")
        self.root = self.gov.create_root_identity(self.grant)
        self.boundary = LocalExecutionBoundary(self.gov, Path(self.tmp.name) / "tools.db")
        self.params = {"body": "customer draft", "recipients": 1}

    def tearDown(self):
        self.boundary.close()
        self.tmp.cleanup()

    def test_complete_workflow(self):
        self.assertEqual(run_workflow()["database_effects"], {"drafts": 1, "sent": 0})

    def test_audit_failure_prevents_side_effect(self):
        with patch("workflow.append_to_chain", side_effect=OSError("disk full")):
            result = self.boundary.execute(self.root.instance_id, "mail.draft", self.params)
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(self.boundary.counts()["drafts"], 0)

    def test_tampered_decision_stops_execution(self):
        self.boundary.execute(self.root.instance_id, "mail.draft", self.params)
        entry = next(e for e in self.gov.chain if e["event_type"] == "ActionEvaluated")
        entry["decision"] = "DENY"
        self.assertFalse(verify_chain(self.gov.chain, "SHA256", self.gov.genesis)[0])
        # The deep scan runs off-path; once it flags a history change the
        # incremental guard remains quarantined for all subsequent requests.
        self.assertFalse(self.boundary.verify_audit_full())
        self.assertEqual(self.boundary.execute(self.root.instance_id, "mail.draft", self.params)["reason"], "audit_integrity")
        self.assertEqual(self.boundary.counts()["drafts"], 1)

    def test_evidence_reconstructs_grant_policy_and_execution(self):
        self.boundary.execute(self.root.instance_id, "mail.draft", self.params)
        by_id = {e["entry_id"]: e for e in self.gov.chain}
        execution = self.gov.chain[-1]
        decision = by_id[execution["causal_parent"]]
        request = by_id[decision["causal_parent"]]
        self.assertEqual(request["granted_by"], "human")
        self.assertEqual(request["grant_id"], self.grant.grant_id)
        policy = next(e for e in self.gov.chain
                      if e["event_type"] == "PolicySnapshotStored" and
                      e["policy_digest"] == request["policy_digest"])
        self.assertEqual(policy["policy_digest"], request["policy_digest"])
        self.assertIn("authorized_actions", policy["policy_snapshot"])
        self.assertEqual(request["params"], self.params)

    def test_bool_does_not_pass_numeric_tool_contract(self):
        self.assertEqual(self.boundary.execute(self.root.instance_id, "mail.draft", dict(self.params, recipients=True))["reason"], "invalid_parameters")

    def test_boundary_failure_stops_execution(self):
        self.boundary.available = False
        self.assertEqual(self.boundary.execute(self.root.instance_id, "mail.draft", self.params)["decision"], "DENY")
        self.assertEqual(self.boundary.counts()["drafts"], 0)



class FastPathOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.gov = GovernanceStack()
        self.scope = draft_scope(True)
        self.grant = self.gov.create_grant("indexed", self.scope,
                                          self.scope["authorized_actions"], 3600,
                                          "human")
        self.root = self.gov.create_root_identity(self.grant)
        self.params = {"body": "sample", "recipients": 1}

    def test_rate_limit_uses_rolling_window(self):
        self.grant.rate_limits = [{"action_pattern": "mail.draft",
                                   "max_count": 2, "window": "60s",
                                   "scope": "INSTANCE"}]
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.gov.advance_time(seconds=10)
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")
        self.gov.advance_time(seconds=51)
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")

    def test_budget_uses_rolling_total(self):
        self.grant.damage_budgets = [{
            "metric": "recipients", "accumulator": "recipients",
            "threshold": 3, "window": "60s", "scope": "INSTANCE",
            "on_exceed": "DENY", "evaluation_tier": 2}]
        for _ in range(3):
            self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[2],
                         "DAMAGE_BUDGET_EXCEEDED")
        self.gov.advance_time(seconds=61)
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")

    def test_negative_and_nonnumeric_budget_fail_closed(self):
        self.grant.damage_budgets = [{
            "metric": "count", "accumulator": "amount",
            "threshold": 10, "window": "60s", "scope": "INSTANCE",
            "on_exceed": "ESCALATE", "evaluation_tier": 2}]
        for value in (-1, True, "5", float("nan"), float("inf")):
            self.assertEqual(self.gov.evaluate(
                self.root, "mail.draft", dict(self.params, amount=value))[0], "DENY")

    def test_type_rate_counter_separates_agent_types(self):
        self.grant.rate_limits = [{
            "action_pattern": "mail.draft", "max_count": 1,
            "window": "1h", "scope": "TYPE", "agent_type": "indexed"}]
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        other = self.gov.create_root_identity(self.grant)
        self.assertEqual(self.gov.evaluate(other, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")

    def test_delegation_tree_counters_include_descendants(self):
        self.grant.rate_limits = [{
            "action_pattern": "mail.draft", "max_count": 1,
            "window": "1h", "scope": "DELEGATION_TREE"}]
        child_scope = draft_scope()
        child, error = self.gov.create_child_identity(
            self.root, "helper", child_scope, child_scope["authorized_actions"])
        self.assertIsNone(error)
        self.assertEqual(self.gov.evaluate(child, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")

    def test_type_limit_counts_other_grants_of_same_agent_type(self):
        rules = [{"action_pattern": "mail.draft", "max_count": 1,
                  "window": "60s", "scope": "TYPE", "agent_type": "indexed"}]
        limited = self.gov.create_grant(
            "indexed", self.scope, self.scope["authorized_actions"], 3600,
            "human", rate_limits=rules)
        limited_agent = self.gov.create_root_identity(limited)
        # This other grant has no TYPE limit, but its actions still count.
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(
            self.gov.evaluate(limited_agent, "mail.draft", self.params)[2],
            "RATE_LIMIT_EXCEEDED")

    def test_type_limit_excludes_other_agent_type(self):
        rules = [{"action_pattern": "mail.draft", "max_count": 1,
                  "window": "60s", "scope": "TYPE", "agent_type": "indexed"}]
        limited = self.gov.create_grant(
            "indexed", self.scope, self.scope["authorized_actions"], 3600,
            "human", rate_limits=rules)
        limited_agent = self.gov.create_root_identity(limited)
        different = self.gov.create_grant(
            "other-type", self.scope, self.scope["authorized_actions"], 3600, "human")
        different_agent = self.gov.create_root_identity(different)
        self.assertEqual(self.gov.evaluate(different_agent, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(limited_agent, "mail.draft", self.params)[0], "ALLOW")

    def test_delegation_tree_counts_entire_tree_including_siblings(self):
        self.grant.rate_limits = [{
            "action_pattern": "mail.draft", "max_count": 3,
            "window": "1h", "scope": "DELEGATION_TREE"}]
        child_scope = draft_scope()
        first, error = self.gov.create_child_identity(
            self.root, "helper", child_scope, child_scope["authorized_actions"])
        self.assertIsNone(error)
        sibling, error = self.gov.create_child_identity(
            self.root, "helper", child_scope, child_scope["authorized_actions"])
        self.assertIsNone(error)
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(sibling, "mail.draft", self.params)[0], "ALLOW")
        # An action from any sibling consumes the shared delegation-tree limit.
        self.assertEqual(self.gov.evaluate(first, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(first, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")

    def test_type_rate_rule_without_non_schema_type_hint(self):
        type_limit = [{"action_pattern": "mail.draft", "max_count": 1,
                       "window": "1h", "scope": "TYPE"}]
        grant = self.gov.create_grant(
            "indexed", self.scope, self.scope["authorized_actions"], 3600,
            "human", rate_limits=type_limit)
        agent = self.gov.create_root_identity(grant)
        self.assertEqual(self.gov.evaluate(agent, "mail.draft", self.params)[0], "ALLOW")
        second = self.gov.create_root_identity(grant)
        self.assertEqual(self.gov.evaluate(second, "mail.draft", self.params)[2],
                         "RATE_LIMIT_EXCEEDED")

    def test_budget_type_shared_across_instances(self):
        self.grant.damage_budgets = [{
            "metric": "recipients", "accumulator": "recipients", "threshold": 1,
            "window": "1h", "scope": "TYPE", "on_exceed": "DENY",
            "evaluation_tier": 2}]
        another = self.gov.create_root_identity(self.grant)
        self.assertEqual(self.gov.evaluate(self.root, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(another, "mail.draft", self.params)[2],
                         "DAMAGE_BUDGET_EXCEEDED")

    def test_budget_tree_shared_across_siblings(self):
        self.grant.damage_budgets = [{
            "metric": "recipients", "accumulator": "recipients", "threshold": 1,
            "window": "1h", "scope": "DELEGATION_TREE", "on_exceed": "DENY",
            "evaluation_tier": 2}]
        scope = draft_scope()
        first, error = self.gov.create_child_identity(
            self.root, "helper", scope, scope["authorized_actions"])
        self.assertIsNone(error)
        other, error = self.gov.create_child_identity(
            self.root, "helper", scope, scope["authorized_actions"])
        self.assertIsNone(error)
        self.assertEqual(self.gov.evaluate(first, "mail.draft", self.params)[0], "ALLOW")
        self.assertEqual(self.gov.evaluate(other, "mail.draft", self.params)[2],
                         "DAMAGE_BUDGET_EXCEEDED")

    def test_usage_history_stays_bounded(self):
        for n in range(350):
            self.gov.evaluate(self.root, "mail.draft", self.params)
        self.assertEqual(len(self.gov.action_log), 256)
        self.assertEqual(len(self.gov.usage.rate_windows), 0)

    def test_tail_guard_does_not_call_full_scan(self):
        with TemporaryDirectory() as directory:
            boundary = LocalExecutionBoundary(self.gov, Path(directory) / "tools.db")
            try:
                with patch("audit_head.verify_chain",
                           side_effect=AssertionError("Full scan on hot path")):
                    for _ in range(5):
                        self.assertEqual(
                            boundary.execute(self.root.instance_id, "mail.draft",
                                             self.params)["decision"], "ALLOW")
                self.assertTrue(boundary.verify_audit_full())
            finally:
                boundary.close()

    def test_latest_tail_tamper_denied_without_full_scan(self):
        with TemporaryDirectory() as directory:
            boundary = LocalExecutionBoundary(self.gov, Path(directory) / "tools.db")
            try:
                self.assertEqual(boundary.execute(
                    self.root.instance_id, "mail.draft", self.params)["decision"], "ALLOW")
                # A forged newest entry differs from its authenticated digest.
                self.gov.chain[-1]["outcome"] = "failure"
                self.assertEqual(boundary.execute(
                    self.root.instance_id, "mail.draft", self.params)["reason"],
                    "audit_integrity")
                self.assertEqual(boundary.counts()["drafts"], 1)
            finally:
                boundary.close()

    def test_full_verification_detects_older_tampering(self):
        with TemporaryDirectory() as directory:
            boundary = LocalExecutionBoundary(self.gov, Path(directory) / "tools.db")
            try:
                for _ in range(3):
                    self.assertEqual(boundary.execute(
                        self.root.instance_id, "mail.draft", self.params)["decision"], "ALLOW")
                self.assertTrue(boundary.audit_guard.check_incremental())
                self.gov.chain[0]["agent_id"] = "tampered"
                # A historical mutation outside the last segment requires the
                # scheduled deep verifier, not an O(1) tail inspection.
                self.assertFalse(boundary.verify_audit_full())
                self.assertEqual(boundary.execute(
                    self.root.instance_id, "mail.draft", self.params)["reason"],
                    "audit_integrity")
            finally:
                boundary.close()

    def test_truncated_audit_denied(self):
        with TemporaryDirectory() as directory:
            boundary = LocalExecutionBoundary(self.gov, Path(directory) / "tools.db")
            try:
                boundary.execute(self.root.instance_id, "mail.draft", self.params)
                self.assertTrue(boundary.audit_guard.check_incremental())
                self.gov.chain.pop()
                self.assertEqual(boundary.execute(
                    self.root.instance_id, "mail.draft", self.params)["reason"],
                    "audit_integrity")
            finally:
                boundary.close()


class ContractTests(unittest.TestCase):
    def test_outcome_schema_matches_actual_evidence(self):
        schema = json.loads((Path(__file__).parents[1] / "schemas/types.schema.json").read_text())
        contract = schema["$defs"]["TrustOutcomeEvidence"]
        jsonschema.validate(evidence(), contract)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(dict(evidence(), outcome="ALLOW"), contract)

    def test_assessment_schema_matches_both_evaluators(self):
        schema = json.loads((Path(__file__).parents[1] / "schemas/types.schema.json").read_text())
        for assessment in (evaluate_output_keyword_overlap("hello", ["hello"], []),
                           evaluate_output_slot_match("hello", {"required_topics": ["hello"]}, [])):
            jsonschema.validate(assessment, schema["$defs"]["LexicalOutputAssessment"])

    def test_jcs_numeric_equivalence(self):
        self.assertEqual(canonical_entry_string({"n": 1.0}), '{"n":1}')
        self.assertEqual(canonical_entry_string({"n": -0.0}), '{"n":0}')

    def test_jcs_utf16_key_order(self):
        text = canonical_entry_string({"\ue000": 1, "\U0001f600": 2})
        self.assertEqual(text, '{"\U0001f600":2,"\ue000":1}')

    def test_jcs_rejects_non_json_numbers(self):
        for value in (float("nan"), float("inf"), 2**60):
            with self.assertRaises(ValueError):
                canonical_entry_string({"n": value})

    def test_numeric_cap_fails_closed_on_non_numbers(self):
        rules = [{"pattern": "x", "decision": "ALLOW", "constraints": [
            {"field": "amount", "operator": "LESS_THAN_OR_EQUAL", "value": 10}]}]
        for value in (True, "5", float("nan"), float("inf")):
            self.assertEqual(evaluate_rules(rules, "x", {"amount": value})[0], "DENY")


if __name__ == "__main__":
    unittest.main()
