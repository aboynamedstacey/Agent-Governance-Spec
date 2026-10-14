"""Bounded-window usage indexes for the in-memory governance test stack.

Each decision reads only the relevant keyed windows. Entries expire lazily in
amortized constant work; an optional sweep removes inactive keys off-path.
This is not a durable, concurrent budget reservation service.
"""
from collections import deque
from datetime import timedelta
import math

from reference_algorithms import matches, parse_duration


def _resolve(path, obj):
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class RollingUsageIndex:
    def __init__(self):
        self.rate_windows = {}
        self.budget_windows = {}
        self.budget_totals = {}

    @staticmethod
    def _rate_key(grant, index, limit, identity):
        scope = limit.get("scope", "INSTANCE")
        if scope == "INSTANCE":
            owner = identity.instance_id
        elif scope == "TYPE":
            owner = limit.get("agent_type")
        elif scope == "DELEGATION_TREE":
            owner = identity.instance_id
        else:
            raise ValueError("Unsupported rate-limit scope")
        return grant.grant_id, index, scope, owner

    def _rate_window(self, key, now, duration):
        queue = self.rate_windows.get(key)
        if queue is not None:
            start = now - duration
            while queue and queue[0] < start:
                queue.popleft()
            if not queue:
                del self.rate_windows[key]
                return None
        return queue

    def rate_permits(self, grant, index, limit, identity, now):
        key = self._rate_key(grant, index, limit, identity)
        queue = self._rate_window(key, now, parse_duration(limit["window"]))
        return queue is None or len(queue) < limit["max_count"]

    def _budget_window(self, key, now, duration):
        queue = self.budget_windows.get(key)
        if queue is not None:
            cutoff = now - duration
            total = self.budget_totals[key]
            while queue and queue[0][0] < cutoff:
                _, amount = queue.popleft()
                total -= amount
            if queue:
                self.budget_totals[key] = total
            else:
                del self.budget_windows[key]
                del self.budget_totals[key]
                return None
        return queue

    def budget_permits(self, grant, index, budget, identity, params, now):
        value = _resolve(budget["accumulator"], params)
        if value is None:
            return True, 0, None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return False, 0, value
        key = (grant.grant_id, index, identity.instance_id)
        window = self._budget_window(key, now, parse_duration(budget["window"]))
        accumulated = self.budget_totals[key] if window else 0
        return accumulated + value <= budget["threshold"], accumulated, value

    def record(self, grant, identity, action_type, params, now):
        for index, limit in enumerate(grant.rate_limits):
            if not matches(action_type, limit["action_pattern"]):
                continue
            scope = limit.get("scope", "INSTANCE")
            if scope == "TYPE" and identity.agent_type != limit.get("agent_type"):
                continue
            owners = (identity.lineage_chain if scope == "DELEGATION_TREE"
                      else [identity.instance_id])
            for owner in owners:
                key = (grant.grant_id, index, scope,
                       owner if scope != "TYPE" else limit.get("agent_type"))
                queue = self._rate_window(key, now, parse_duration(limit["window"]))
                if queue is None:
                    queue = deque()
                    self.rate_windows[key] = queue
                queue.append(now)

        for index, budget in enumerate(grant.damage_budgets):
            if budget.get("evaluation_tier", 2) != 2:
                continue
            value = _resolve(budget["accumulator"], params)
            if value is None:
                continue
            # The evaluator must reject malformed budget amounts before record.
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid budget amount")
            key = (grant.grant_id, index, identity.instance_id)
            queue = self._budget_window(key, now, parse_duration(budget["window"]))
            if queue is None:
                queue = deque()
                self.budget_windows[key] = queue
                self.budget_totals[key] = 0
            queue.append((now, value))
            self.budget_totals[key] += value

    def sweep(self, now, grants):
        """Off-path cleanup; not used when authorizing a tool action."""
        for key in list(self.rate_windows):
            grant = grants.get(key[0])
            if grant is None or key[1] >= len(grant.rate_limits):
                self.rate_windows.pop(key, None)
            else:
                self._rate_window(key, now, parse_duration(grant.rate_limits[key[1]]["window"]))
        for key in list(self.budget_windows):
            grant = grants.get(key[0])
            if grant is None or key[1] >= len(grant.damage_budgets):
                self.budget_windows.pop(key, None)
                self.budget_totals.pop(key, None)
            else:
                self._budget_window(key, now, parse_duration(grant.damage_budgets[key[1]]["window"]))
