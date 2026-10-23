#!/usr/bin/env python3
"""Mininet topology: three senders, two branches, shared S4-S5 bottleneck."""
import json
from pathlib import Path
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

ROOT = Path(__file__).resolve().parent


def build(config, scenario="normal"):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, build=False, autoSetMacs=False)
    try:
        net.addController("c0", controller=RemoteController, ip=config["controller"]["host"], port=config["controller"]["port"])
        hosts = [net.addHost(f"h{i}", ip=f"10.0.0.{i}/24", mac=f"00:00:00:00:00:{i:02x}") for i in range(1, 5)]
        switches = [net.addSwitch(f"s{i}", dpid=f"{i:016x}", protocols="OpenFlow13", failMode="secure") for i in range(1, 6)]
        cap, delay = config["topology"]["capacity_mbps"], config["topology"]["delay_ms"]
        linkopts = dict(bw=cap, delay=f"{delay}ms", use_htb=True)
        # Link order fixes switch port numbers, matching PORTS in controller.py.
        for host in hosts[:3]: net.addLink(host, switches[0], **linkopts)
        net.addLink(hosts[3], switches[4], **linkopts)
        branchopts = dict(bw=min(2,cap), delay=f"{delay}ms", use_htb=True) if scenario == "branch_congestion" else linkopts
        net.addLink(switches[0], switches[1], **branchopts)
        net.addLink(switches[0], switches[2], **linkopts)
        net.addLink(switches[1], switches[3], **branchopts)
        net.addLink(switches[2], switches[3], **linkopts)
        # OVS QoS owns S4's egress qdisc. A TCLink netem qdisc on this interface
        # would replace or compete with that HTB tree, so this shared link has no
        # Mininet traffic-control options.
        net.addLink(switches[3], switches[4])
        net.build()
        net.start()
        return net
    except Exception:
        net.stop()
        raise


def main():
    setLogLevel("info")
    config = json.loads((ROOT / "config.json").read_text())
    net = build(config)
    info("*** Topology ready. Try: pingall\n")
    try: CLI(net)
    finally:
        net.stop()


if __name__ == "__main__": main()
