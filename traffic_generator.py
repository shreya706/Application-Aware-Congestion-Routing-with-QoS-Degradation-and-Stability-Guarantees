"""Repeatable iperf3 client commands for the three predefined application ports."""
import argparse, time


def start_servers(receiver):
    cmds=[]
    for port in (5001,5002,5003):
        cmds.append(receiver.popen(["iperf3","-s","-p",str(port)],stdout=open(f"/tmp/iperf3-server-{port}.log","w"),stderr=-2))
    return cmds


def start_clients(hosts, receiver_ip, duration, rates):
    procs=[]
    for i,host in enumerate(hosts):
        for port in (5001,5002):
            procs.append(host.popen(["iperf3","-c",receiver_ip,"-p",str(port),"-u","-b",f"{rates[port]}M","-t",str(duration),"-J"]))
        procs.append(host.popen(["iperf3","-c",receiver_ip,"-p","5003","-t",str(duration),"-J"]))
    return procs


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--duration",type=int,default=20); parser.add_argument("--receiver",default="10.0.0.4"); parser.parse_args()
    print("Import start_servers/start_clients from a Mininet CLI script; see README demo commands.")
