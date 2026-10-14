"""Keyed rolling-window accounting for the in-memory governance fixture.

Queries visit only the relevant counters. TYPE rate limits span grants; a
DELEGATION_TREE rate limits aggregate the entire tree, including siblings. Expiry is amortized over recorded events. Production needs
durable, atomic reservations and shared state across workers.
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
        self.rate_windows = {}          # (grant, rule, scope, node) -> timestamps
        self.type_limits = {}           # agent type -> {(type, pattern, duration): max_count}
        self.type_windows = {}          # shared counters across all grants
        self.incomplete_type_limits = set()
        self.budget_windows = {}
        self.budget_totals = {}

    @staticmethod
    def _window(registry, key, now, duration):
        queue = registry.get(key)
        if queue is not None:
            cutoff = now - duration
            while queue and queue[0] < cutoff:
                queue.popleft()
            if not queue:
                registry.pop(key, None)
                return None
        return queue

    def register_grant(self, grant):
        for limit in grant.rate_limits:
            if limit.get("scope", "INSTANCE") != "TYPE":
                continue
            self._register_type_rule(limit, grant.agent_type)

    def _register_type_rule(self, limit, default_agent_type=None):
        agent_type = limit.get("agent_type") or default_agent_type
        if not agent_type:
            raise ValueError("TYPE rate limits require an agent type")
        duration = parse_duration(limit["window"])
        key = (agent_type, limit["action_pattern"], duration.total_seconds())
        limits = self.type_limits.setdefault(agent_type, {})
        previous = limits.get(key)
        if previous is None:
            limits[key] = limit["max_count"]
        elif limit["max_count"] > previous:
            # A wider limit cannot recover older timestamps evicted under
            # the earlier bound. Fail closed until a complete window elapses.
            limits[key] = limit["max_count"]
            if key in self.type_windows and len(self.type_windows[key]) == previous:
                self.incomplete_type_limits.add(key)
            existing = self.type_windows.get(key)
            if existing is not None:
                self.type_windows[key] = deque(existing, maxlen=limit["max_count"])
        return key

    def rate_permits(self, grant, index, limit, identity, now):
        scope = limit.get("scope", "INSTANCE")
        duration = parse_duration(limit["window"])
        if scope == "TYPE":
            key = self._register_type_rule(limit, grant.agent_type)
            window = self._window(self.type_windows, key, now, duration)
            if key in self.incomplete_type_limits:
                if window is not None:
                    return False
                self.incomplete_type_limits.discard(key)
            return window is None or len(window) < limit["max_count"]
        if scope not in ("INSTANCE", "DELEGATION_TREE"):
            raise ValueError("Unsupported rate-limit scope")

        owner = (identity.lineage_chain[0] if scope == "DELEGATION_TREE"
                 else identity.instance_id)
        key = (grant.grant_id, index, scope, owner)
        window = self._window(self.rate_windows, key, now, duration)
        return window is None or len(window) < limit["max_count"]

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
                self.budget_windows.pop(key, None)
                self.budget_totals.pop(key, None)
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
        # TYPE counters include activity from other grants, including grants
        # without a TYPE limit of their own.
        for key, max_count in self.type_limits.get(identity.agent_type, {}).items():
            if not matches(action_type, key[1]):
                continue
            window = self._window(self.type_windows, key, now,
                                  timedelta(seconds=key[2]))
            if window is None:
                window = deque(maxlen=max_count)
                self.type_windows[key] = window
            window.append(now)

        for index, limit in enumerate(grant.rate_limits):
            if not matches(action_type, limit["action_pattern"]):
                continue
            scope = limit.get("scope", "INSTANCE")
            if scope == "TYPE":
                continue  # Accounted for by the shared type registry.
            if scope not in ("INSTANCE", "DELEGATION_TREE"):
                raise ValueError("Unsupported rate-limit scope")
            owner = (identity.lineage_chain[0] if scope == "DELEGATION_TREE"
                     else identity.instance_id)
            key = (grant.grant_id, index, scope, owner)
            queue = self._window(self.rate_windows, key, now,
                                 parse_duration(limit["window"]))
            if queue is None:
                queue = deque()
                self.rate_windows[key] = queue
            queue.append(now)

        for index, budget in enumerate(grant.damage_budgets):
            if budget.get("evaluation_tier", 2) != 2:
                continue
            value = _resolve(budget["accumulator"], params)
            if value is None or value == 0:
                continue
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
        """Reclaim idle counters off-path, not during authorization."""
        for key in list(self.rate_windows):
            grant = grants.get(key[0])
            if grant is None or key[1] >= len(grant.rate_limits):
                self.rate_windows.pop(key, None)
            else:
                self._window(self.rate_windows, key, now,
                             parse_duration(grant.rate_limits[key[1]]["window"]))
        for key in list(self.type_windows):
            self._window(self.type_windows, key, now, timedelta(seconds=key[2]))
            if key not in self.type_windows:
                self.incomplete_type_limits.discard(key)
        for key in list(self.budget_windows):
            grant = grants.get(key[0])
            if grant is None or key[1] >= len(grant.damage_budgets):
                self.budget_windows.pop(key, None)
                self.budget_totals.pop(key, None)
            else:
                self._budget_window(key, now, parse_duration(grant.damage_budgets[key[1]]["window"]))
