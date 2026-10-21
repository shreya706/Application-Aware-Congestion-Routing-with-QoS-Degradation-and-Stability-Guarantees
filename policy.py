"""KEEP/REROUTE/DEGRADE decisions, hysteresis, and Congestion Recovery Memory."""
from collections import deque
from dataclasses import dataclass, field
import time


def classify_transport(applications, protocol_number, port):
    """Map a transport protocol and port to a configured class, if any."""
    protocol_name = "udp" if protocol_number == 17 else "tcp" if protocol_number == 6 else ""
    for name, profile in applications.items():
        if profile["protocol"] == protocol_name and int(profile["destination_port"]) == int(port):
            return name
    return None


@dataclass
class FlowState:
    path: tuple
    last_change: float = 0.0
    candidate: tuple | None = None
    consecutive: int = 0
    previous_paths: deque = field(default_factory=deque)


def route_decision(state, proposed, current_score, proposed_score, now=None,
                   improvement=0.15, stable_intervals=3, cooldown=5.0,
                   memory_seconds=12.0, reversal_penalty=0.20):
    """Apply meaningful improvement, persistence, cooldown, and CRM reversal memory."""
    now = time.time() if now is None else now
    if proposed is None or tuple(proposed) == tuple(state.path):
        state.candidate, state.consecutive = None, 0
        return "KEEP", "current path remains preferred or no feasible path exists"
    target = tuple(proposed)
    while state.previous_paths and now - state.previous_paths[0][1] > memory_seconds:
        state.previous_paths.popleft()
    recently_abandoned = any(path == target for path, _ in state.previous_paths)
    required = improvement + (reversal_penalty if recently_abandoned else 0.0)
    if proposed_score < current_score * (1.0 + required):
        state.candidate, state.consecutive = None, 0
        return "KEEP", "alternative improvement is below hysteresis threshold"
    if now - state.last_change < cooldown:
        state.candidate, state.consecutive = None, 0
        return "KEEP", "route-change cooldown is active"
    if state.candidate == target:
        state.consecutive += 1
    else:
        state.candidate, state.consecutive = target, 1
    if state.consecutive < stable_intervals:
        return "KEEP", f"candidate improvement persisted {state.consecutive}/{stable_intervals} intervals"
    old = tuple(state.path)
    state.previous_paths.append((old, now))
    state.path, state.last_change = target, now
    state.candidate, state.consecutive = None, 0
    return "REROUTE", "sustained improvement passed hysteresis and cooldown"


def degrade_bulk(allocation_mbps, minimum_mbps, deficit_mbps,
                 max_degradation_fraction=1.0, requested_mbps=None):
    """Return a lower ceiling within minimum-rate and maximum-cut bounds."""
    requested = float(allocation_mbps if requested_mbps is None else requested_mbps)
    fraction = min(1.0, max(0.0, float(max_degradation_fraction)))
    floor = max(float(minimum_mbps), requested * (1.0 - fraction))
    target = max(floor, float(allocation_mbps) - max(0.0, float(deficit_mbps)))
    return target, float(allocation_mbps) - target


def recover_bulk(allocation_mbps, requested_mbps, step_mbps):
    return min(float(requested_mbps), float(allocation_mbps) + max(0.0, float(step_mbps)))


@dataclass
class RecoveryMemory:
    allocation_mbps: float
    clear_intervals: int = 0

    def update(self, congested, requested_mbps, minimum_mbps, clear_required, step_mbps):
        if congested:
            self.clear_intervals = 0
            return self.allocation_mbps, None
        self.clear_intervals += 1
        if self.clear_intervals < clear_required or self.allocation_mbps >= requested_mbps:
            return self.allocation_mbps, None
        old = self.allocation_mbps
        self.allocation_mbps = min(requested_mbps, max(minimum_mbps, old + step_mbps))
        return self.allocation_mbps, {"old_mbps": old, "new_mbps": self.allocation_mbps}
