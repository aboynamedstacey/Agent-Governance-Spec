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
        self.assertIn("policy_snapshot", request)
        self.assertEqual(request["params"], self.params)

    def test_bool_does_not_pass_numeric_tool_contract(self):
        self.assertEqual(self.boundary.execute(self.root.instance_id, "mail.draft", dict(self.params, recipients=True))["reason"], "invalid_parameters")

    def test_boundary_failure_stops_execution(self):
        self.boundary.available = False
        self.assertEqual(self.boundary.execute(self.root.instance_id, "mail.draft", self.params)["decision"], "DENY")
        self.assertEqual(self.boundary.counts()["drafts"], 0)


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
