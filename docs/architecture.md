# Architecture

## Problem and objective

Shortest-path forwarding treats application flows alike. The prototype compares configured application requirements with candidate paths and tries to protect delay-sensitive traffic while allowing bulk traffic to use the remaining capacity. When capacity is insufficient it must report infeasibility rather than claim that every flow is guaranteed.

## Components

- **Mininet** creates four hosts and five OVS switches with two branches and a shared bottleneck.
- **Open vSwitch/OpenFlow 1.3** forwards packets using controller-installed flow entries. The controller receives misses and port statistics.
- **OS-Ken** handles OpenFlow events and communicates with OVS using its Ryu-compatible API.
- **NetworkX** stores the fixed topology and returns candidate simple paths.
- **iperf3 and ping** generate traffic and measure receiver throughput, UDP jitter/loss, and end-to-end RTT.
- **OVS HTB QoS** enforces the bulk queue rate on the shared bottleneck egress. Flow actions place bulk TCP packets in queue 1.
- **JSON/CSV and pandas/Matplotlib** store configuration and support analysis of results.

## Packet path

Packets arriving at a switch miss table entries and go to the controller. The controller checks the IP protocol and configured port, chooses a path, then installs matching IPv4 transport rules in each direction. ARP requests are sent toward only the switch connected to the target IP. No generic broadcast flood is installed. A counter poll runs each second; first samples, missing deltas, and counter resets are omitted instead of becoming fake rates.

## Measurement boundaries

Configured per-link delay is used as a path-selection baseline. OpenFlow byte-counter deltas produce estimated transmit rate and utilization. They do not measure one-way delay, RTT, jitter, or packet loss. End-host `ping` and iperf receiver reports provide those measurements. QoS thresholds are configuration values and not proof that the thresholds were achieved.
