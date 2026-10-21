# Viva questions and short answers

1. **What problem does the project address?** It assigns paths and congestion treatment according to configured application needs.
2. **Why use SDN?** A controller can make a network-wide decision and install forwarding rules in switches.
3. **What does OpenFlow do here?** It carries switch events/statistics to the controller and transports flow rules back to OVS.
4. **Why OS-Ken?** It is a Python controller framework with a Ryu-style OpenFlow API.
5. **How is traffic classified?** By IP transport protocol and the configured destination port: UDP 5001/5002 or TCP 5003.
6. **Is this general application identification?** No. It is predefined port-based classification.
7. **Why use NetworkX?** It represents the graph and enumerates candidate simple paths.
8. **How does real-time differ from bulk?** Real-time gives more score weight to configured delay; bulk gives more weight to residual capacity.
9. **What is residual bandwidth?** Configured capacity minus estimated current rate and the expected rate of new flows, clamped at zero.
10. **What is the difference between configured delay and measured RTT?** Configured delay is a link baseline; RTT is measured end-to-end with ping.
11. **How is link utilization estimated?** OpenFlow transmit-byte counter delta converted to Mbps and divided by configured capacity.
12. **Why ignore the first statistics sample?** There is no previous counter from which to calculate a rate.
13. **What does KEEP mean?** The controller keeps the path if the alternative is not sufficiently better or stable.
14. **What prevents route flapping?** A meaningful improvement, repeated qualifying intervals, and a cooldown are required.
15. **What is Congestion Recovery Memory?** This prototype remembers recently abandoned paths and restores bulk allocation in steps after congestion clears.
16. **How is bulk shaping enforced?** OVS HTB QoS queue 1 caps bulk traffic on the shared egress link, selected by an OpenFlow queue action.
17. **What if every path is full?** The controller records infeasibility and may reduce tolerant bulk traffic; it cannot promise impossible guarantees.
18. **How are UDP jitter and loss measured?** From iperf3 receiver reports, not OpenFlow counters.
19. **What does Mininet provide?** Linux network namespaces and virtual Ethernet links/switches for repeatable experiments.
20. **What are important limitations?** Fixed topology, predefined ports, estimated counter load, and live OVS QoS behavior requiring validation on Ubuntu.
