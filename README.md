# Application-Aware Congestion Routing

An educational SDN prototype that classifies three configured flows by transport protocol and destination port, chooses between two OpenFlow paths, estimates link load from switch counters, and enforces a bulk rate ceiling with an Open vSwitch queue. The controller uses OS-Ken's Ryu-style OpenFlow 1.3 API. NetworkX is used for candidate paths.

The attached project proposal describes broader QoS goals. This implementation turns those goals into a small, fixed Mininet experiment. Port classification is predefined; it does not identify arbitrary applications. A configured delay is a link baseline, not a measured end-to-end latency. OpenFlow reports byte counters; rates and utilization are estimates derived from counter differences. Ping RTT and iperf UDP jitter/loss are separate end-host measurements.

## Topology

```text
h1 --\
h2 --- S1 ---- S2 ----\
h3 --/  \              S4 ---- S5 ---- h4
          \-- S3 ----/          shared bottleneck
       Path A: S1-S2-S4-S5
       Path B: S1-S3-S4-S5
```

Switch datapaths use DPIDs 1 through 5. Switch ports are deliberately deterministic and documented in `controller.py`; do not reorder links in `topology.py` without updating that map. ARP requests are forwarded only toward the target host along a shortest topology path, avoiding uncontrolled loop-prone flooding.

## Application profiles

| Class | Protocol/port | Requested | Minimum | Treatment |
|---|---|---:|---:|---|
| Critical | UDP/5001 | 0.5 Mbps | 0.5 Mbps | No configured degradation; low-delay weighted path and proposed-mode queue minimum |
| Real-time | UDP/5002 | 2 Mbps | 1 Mbps | Delay weighted and proposed-mode queue minimum where feasible |
| Bulk | TCP/5003 | 6 Mbps | 1 Mbps | Capacity weighted; OVS queue 1 applies the adjustable ceiling |

Edit `config.json` to change rates, link capacity/delay, path scoring, stability intervals and recovery steps. In `summary.csv`, a run's partial QoS result is satisfied when receiver throughput meets the class minimum and every jitter/loss metric present in the iperf receiver JSON meets that class's configured maximum. Missing metrics are omitted, so this is not a complete QoS-vector guarantee; ping RTT is reported separately and does not affect this flag. Controller logs do not claim QoS satisfaction based on link counters.

## Environment check and installation (Ubuntu)

Mininet needs Linux network namespaces, root privileges, and Open vSwitch. The authoring host for this project is Windows 11 with Python 3.12, so live Mininet execution was unavailable here. Use an Ubuntu 22.04/24.04 VM with at least 2 virtual CPUs and 4 GB RAM; no GPU, Docker, physical switch, or second server is needed. Run the project inside the VM. Check the actual guest first:

```bash
cat /etc/os-release
python3 --version
uname -a
```

From the project directory:

```bash
chmod +x scripts/*.sh cleanup.sh
./scripts/install_dependencies.sh
```

The apt packages (Mininet, OVS, iperf3, ping, Python and venv) require `sudo`; Python packages install into `.venv` without sudo. `requirements.txt` pins OS-Ken 3.1.1 because this project uses the `osken-manager` launcher, which OS-Ken 4 removed. NetworkX, pandas, and Matplotlib use compatible major-version constraints. If distro Mininet is not available, install it from the official Mininet project instructions for that Ubuntu release, then rerun the Python venv steps.

## Run the network

Use two terminals in the Ubuntu VM, both in this directory.

Terminal 1 starts the controller (the script uses sudo because it creates and updates OVS QoS objects):

```bash
source .venv/bin/activate
./scripts/start_controller.sh
```

Terminal 2 starts Mininet (requires root to create namespaces and OVS ports):

```bash
sudo env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 topology.py
```

At the Mininet prompt, check connectivity and inspect the switches:

```text
mininet> pingall
mininet> sh ovs-vsctl show
mininet> h1 ping -c 4 10.0.0.4
```

Traffic starts when an iperf client sends to UDP 5001, UDP 5002 or TCP 5003. For a quick manual run, open another terminal and use `iperf3 -s -p 5001` on h4 from the Mininet prompt (`h4 iperf3 -s -p 5001 &`), then `h1 iperf3 -c 10.0.0.4 -p 5001 -u -b 0.5M -t 10`. Repeat with ports 5002 and 5003, using TCP for 5003.

The controller writes `results/controller_events.csv` and `results/monitoring.csv`. The latter includes estimated transmit rates and active OVS parent capacities. On S4 port 3, proposed mode directs bulk to queue 1 with an adjustable maximum, real-time to queue 2 with a 1 Mbps minimum and 2 Mbps maximum, and critical traffic to queue 3 with a 0.5 Mbps minimum and maximum. Other modes use queue 1 at the parent ceiling and leave the two protected classes in the default queue. Verify the OVS QoS and queue objects with `sudo ovs-vsctl list Port s4-eth3` and `sudo ovs-vsctl list Queue`; inspect queue counters with `sudo ovs-ofctl -O OpenFlow13 queue-stats s4` where supported. A setup failure is logged and makes the experiment runner fail; a Python allocation value alone is not treated as enforcement.

## Experiments and cleanup

The experiment runner checks that it is on Linux with Mininet, OVS, iperf3 and ping. Run one mode at a time from a root-enabled terminal. It starts an OS-Ken controller for each scenario, launches the three clients concurrently, and captures ping output:

```bash
sudo env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 run_experiment.py --mode proposed --repetitions 3
sudo env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 run_experiment.py --mode shortest --repetitions 3
sudo env -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 run_experiment.py --mode load-aware --repetitions 3
```

Raw iperf JSON files are saved in `results/`; `python analyse.py` writes `summary.csv` and metric graphs. The branch case limits Path A links; shared overload lowers the OVS parent queue ceiling; recovery raises that OVS ceiling halfway through the traffic interval. The controller reads the active parent ceiling from OVSDB for capacity estimates. Compare the measured files and controller logs. OVS QoS owns the S4 egress qdisc, so the emulated shared link omits a competing Mininet netem qdisc. The configured bottleneck delay remains a controller path-cost input and must not be presented as a measured S4-S5 delay guarantee. [Mininet OVS switch notes](https://mininet.org/api/classmininet_1_1node_1_1OVSSwitch.html)

To stop the network, exit the Mininet CLI with `exit` and stop the controller with Ctrl-C. Reset Mininet and this demo's QoS attachment:

```bash
./cleanup.sh
```

This runs `sudo mn -c` and clears only `s4-eth3`'s QoS reference. It does not stop unrelated OVS bridges or controller processes. Use `sudo ovs-vsctl show` before any broader OVS reset.

## Tests and limitations

Run logic tests on Python 3.10+ with dependencies installed:

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```

These tests exercise classification configuration, candidate path selection, hysteresis/CRM, and bounded degradation/recovery without a live network. Live acceptance still requires the Ubuntu VM: establish host connectivity, verify controller-installed flows, inspect queue counters and rate limiting, run each congestion/recovery case, and inspect cleanup. This Windows session cannot claim those checks or experimental outcomes. The current fixed topology and single receiver are deliberate lab limits; route update consistency, QoS behavior, and measurement quality should be validated against the installed OVS/OS-Ken versions before a viva demonstration.

See [docs/project_positioning.md](docs/project_positioning.md), [docs/architecture.md](docs/architecture.md), [docs/algorithm.md](docs/algorithm.md), and [docs/viva_questions.md](docs/viva_questions.md).
