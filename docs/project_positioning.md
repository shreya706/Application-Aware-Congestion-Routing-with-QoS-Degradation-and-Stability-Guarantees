# Project problem objective and contribution

## Problem

Applications do not have identical network needs. Critical and real-time flows are
sensitive to service loss and delay, while bulk transfers can usually accept a temporary
rate reduction. Application-aware routing can move a flow when another suitable path
exists. During shared-bottleneck overload, however, every candidate path eventually
uses the same saturated link, so rerouting alone cannot create capacity. Rapid reactions
to short-lived measurements can also cause repeated path reversals.

The project asks: when rerouting cannot remove congestion, how can an SDN controller
protect sensitive traffic, reduce tolerant traffic within declared limits, and avoid
unnecessary route changes?

## Objective

Design and experimentally evaluate an explainable SDN controller that:

1. classifies configured test flows by transport protocol and destination port;
2. selects paths using class-specific delay and residual-capacity preferences;
3. reroutes only after meaningful, persistent improvement and a cooldown;
4. bounds bulk degradation by its configured minimum and maximum cut;
5. gradually restores the bulk allocation after sustained recovery; and
6. records KEEP, REROUTE, DEGRADE, RECOVER, and QOS_INFEASIBLE decisions.

The evaluation compares fixed shortest path, immediate load-aware routing, and the full
proposed policy under normal, branch-congestion, shared-overload, and recovery scenarios.

## Project contribution and novelty position

Application-aware routing, QoS queues, rate allocation, and hysteresis already exist.
The project does not claim to invent those individual techniques. Its proposed
contribution is their small, reproducible coordination for the overload case described
in the submitted brief:

- feasibility-aware class-specific route selection;
- tolerance-bounded bulk degradation when the shared bottleneck makes rerouting
  insufficient;
- persistence, cooldown, and recent-route memory that require extra evidence before
  reversing onto a recently abandoned path; and
- gradual restoration after sustained spare capacity.

This combined policy is called Congestion Recovery Memory in the prototype. Its value
must be supported by comparison results: protected-class QoS, bulk throughput, route
changes, and recovery behavior. Until those experiments pass, it is a proposed
contribution rather than a proven improvement or a claim of being the first such system.

## Scope limits

Classification is configured port matching, not arbitrary application discovery.
Configured link delay is a routing estimate; ping RTT and iperf3 jitter/loss are
end-host measurements. OpenFlow counter deltas estimate link rate. QoS is enforced only
where verified OVS queues exist. When protected demand itself exceeds capacity, the
controller reports infeasibility instead of claiming an impossible guarantee.
