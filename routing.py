"""Application-aware path scoring, independent of a live Mininet instance."""
from dataclasses import dataclass
import networkx as nx


@dataclass
class PathEstimate:
    nodes: list
    delay_ms: float
    residual_mbps: float
    utilization: float
    score: float
    feasible: bool
    bottleneck_edge: tuple | None = None


def candidate_paths(graph, source, destination, count=4):
    """Return simple candidate paths ordered by configured delay."""
    try:
        paths = nx.shortest_simple_paths(graph, source, destination, weight="delay_ms")
        return [list(p) for _, p in zip(range(count), paths)]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def estimate_path(graph, path, policy, requested_mbps, expected_load=None):
    expected_load = expected_load or {}
    delay = 0.0
    residuals, utilizations, edge_residuals = [], [], []
    for a, b in zip(path, path[1:]):
        edge = graph[a][b]
        cap = float(edge["capacity_mbps"])
        rate = float(edge.get("rate_mbps", 0.0)) + float(expected_load.get(tuple(sorted((a, b))), 0.0))
        delay += float(edge["delay_ms"])
        residuals.append(max(0.0, cap - rate))
        edge_residuals.append((max(0.0, cap - rate), tuple(sorted((a, b)))))
        utilizations.append(min(1.0, rate / cap) if cap else 1.0)
    residual = min(residuals, default=0.0)
    utilization = max(utilizations, default=1.0)
    cap_score = min(1.0, residual / max(requested_mbps, 0.001))
    delay_score = 1.0 / (1.0 + delay / max(float(policy["max_delay_ms"]), 1.0))
    feasible = residual + 1e-9 >= requested_mbps and delay <= float(policy["max_delay_ms"])
    score = float(policy["delay_weight"]) * delay_score + float(policy["capacity_weight"]) * cap_score
    bottleneck_edge = min(edge_residuals, key=lambda item: item[0])[1] if edge_residuals else None
    return PathEstimate(list(path), delay, residual, utilization, score, feasible, bottleneck_edge)


def select_path(graph, source, destination, policy, requested_mbps, expected_load=None, count=4):
    estimates = [estimate_path(graph, p, policy, requested_mbps, expected_load)
                 for p in candidate_paths(graph, source, destination, count)]
    feasible = [p for p in estimates if p.feasible]
    # Keep an explicit best-effort estimate so callers can report infeasibility.
    return max(feasible or estimates, key=lambda p: p.score) if estimates else None
