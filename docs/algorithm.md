# Algorithm notes

## Path selection

NetworkX returns up to `candidate_paths` simple paths ordered by configured delay. For each edge, the controller estimates residual capacity as `max(0, capacity - measured_rate - expected_new_load)`. Path delay is the sum of configured edge delay. The normalized score is:

```text
score = delay_weight * 1/(1 + path_delay/max_delay) + capacity_weight * min(1, path_residual/requested_rate)
```

A path is feasible when its bottleneck residual meets the requested rate and its configured delay meets the class limit. Critical/realtime profiles weight delay more; bulk weights capacity more. If no candidate is feasible, the best-effort path is retained for explicit `QOS_INFEASIBLE` reporting.

## Monitoring and stable route changes

For successive samples, `rate_mbps = 8 * delta_tx_bytes / elapsed_seconds / 1,000,000`; utilization divides the estimated rate by configured capacity. A candidate must exceed the current score by the configured hysteresis fraction for three successive policy intervals, and the five-second cooldown must have expired. Otherwise the decision is KEEP with a logged reason. Congestion Recovery Memory remembers recently abandoned paths and asks for a larger improvement before reversal.

## Degradation and recovery

Bulk has a requested ceiling of 6 Mbps and minimum of 1 Mbps, with the configured maximum-degradation fraction also bounding the lowest target. Queue 1 enforces its current ceiling. In proposed mode, queue 2 reserves the real-time minimum and caps it at its requested rate; queue 3 reserves and caps the critical rate. The controller adds `SET_QUEUE` to each matching flow's S4 egress action. The recovery helper changes the queue's OVSDB maximum only after the configured clear intervals. If protected minimum demand by itself exceeds available capacity, queue setup reports `QOS_INFEASIBLE`; no configuration can guarantee more capacity than the link provides.

The project-specific CRM extension combines route-reversal memory with gradual bandwidth restoration. It is a simple stability policy choice, not a claim of inventing the general idea of hysteresis or recovery memory.
