#!/usr/bin/env python3
"""Run a live experiment through Mininet's Python API; never substitutes simulation."""
import argparse, csv, json, os, shutil, subprocess, sys, time, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent


def progress(message):
    print(f"[experiment] {message}", flush=True)


def require_linux_tools():
    if sys.platform != "linux":
        raise SystemExit("Live experiments require Ubuntu/Linux with Mininet and OVS. This host is Windows; use the documented Ubuntu VM steps.")
    missing=[tool for tool in ("mn","ovs-vsctl","iperf3","ping") if shutil.which(tool) is None]
    if missing: raise SystemExit("Missing live-network tools: "+", ".join(missing))


def run(args):
    require_linux_tools()
    progress("cleaning stale Mininet interfaces from earlier interrupted runs")
    subprocess.run(["mn", "-c"], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.STDOUT)
    sys.path.insert(0,str(ROOT))
    from mininet.net import Mininet
    from topology import build
    from qos import set_qos_capacity
    config=json.loads((ROOT/"config.json").read_text())
    results=ROOT/"results"; results.mkdir(exist_ok=True)
    outfile=results/"experiment_runs.csv"
    exists=outfile.exists()
    duration=config["experiments"]["duration_seconds"]
    progress(f"mode={args.mode}; {args.repetitions} repetition(s); four scenarios; about {args.repetitions * 4 * (duration + 10)} seconds")
    with outfile.open("a",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["timestamp","mode","scenario","repeat","status","note"])
        if not exists: writer.writeheader()
        for repeat in range(1,args.repetitions+1):
            for scenario in ("normal","branch_congestion","shared_overload","recovery"):
                progress(f"starting {scenario} ({repeat}/{args.repetitions})")
                env=os.environ.copy(); env["AA_MODE"]=args.mode
                env["AA_SCENARIO"]=scenario
                controller_log=(results/f"controller_{args.mode}_{scenario}_{repeat}.log").open("w")
                controller=subprocess.Popen([str(ROOT/".venv/bin/osken-manager"),str(ROOT/"controller.py")],cwd=ROOT,env=env,stdout=controller_log,stderr=subprocess.STDOUT)
                time.sleep(2)
                net=None
                try:
                    if controller.poll() is not None:
                        raise RuntimeError(f"OS-Ken exited before Mininet start; inspect {controller_log.name}")
                    net=build(config,scenario)
                    progress(f"{scenario}: topology started; checking reachability")
                    loss=net.pingAll()
                    if loss > 0:
                        raise RuntimeError(f"pingall reported {loss:.1f}% loss before traffic run")
                    progress(f"{scenario}: reachability passed; running traffic for {duration} seconds")
                    receiver=net.get("h4")
                    servers=[]
                    for port in (5001,5002,5003):
                        servers.append(receiver.popen(["iperf3","-s","-p",str(port)],stdout=open(f"/tmp/aa-iperf-{port}.log","w"),stderr=subprocess.STDOUT))
                    time.sleep(1)
                    if any(server.poll() is not None for server in servers):
                        raise RuntimeError("An iperf3 server exited before client traffic started")
                    clients=[]
                    client_outputs=[]
                    for host,port,proto,rate in [(net.get("h1"),5001,"udp","0.5M"),(net.get("h2"),5002,"udp","2M"),(net.get("h3"),5003,"tcp",None)]:
                        cmd=["iperf3","-c","10.0.0.4","-p",str(port),"-t",str(config["experiments"]["duration_seconds"]),"-J"]
                        if proto=="udp": cmd += ["-u","-b",rate]
                        output_path=results/f"iperf_{args.mode}_{scenario}_{repeat}_{port}.json"
                        client_outputs.append(output_path)
                        clients.append(host.popen(cmd,stdout=open(output_path,"w"),stderr=subprocess.STDOUT))
                    recovery_errors=[]
                    if scenario == "recovery":
                        progress(f"{scenario}: bottleneck will be restored after {duration / 2:g} seconds")
                        def restore_link():
                            try:
                                time.sleep(config["experiments"]["duration_seconds"]/2)
                                set_qos_capacity("s4-eth3",config["topology"]["bottleneck_mbps"])
                            except Exception as exc: recovery_errors.append(exc)
                        recovery_thread=threading.Thread(target=restore_link,daemon=True)
                        recovery_thread.start()
                    pinger=net.get("h1").popen(["ping","-i","0.5","-w",str(config["experiments"]["duration_seconds"]),"10.0.0.4"],stdout=open(results/f"ping_{args.mode}_{scenario}_{repeat}.txt","w"),stderr=subprocess.STDOUT)
                    client_codes=[proc.wait() for proc in clients]
                    ping_code=pinger.wait()
                    if any(code != 0 for code in client_codes):
                        raise RuntimeError(f"iperf3 client exited with status codes {client_codes}")
                    for output_path in client_outputs:
                        try: report=json.loads(output_path.read_text())
                        except (OSError,json.JSONDecodeError) as exc: raise RuntimeError(f"invalid iperf3 JSON at {output_path.name}: {exc}") from exc
                        if "end" not in report: raise RuntimeError(f"iperf3 report has no end summary: {output_path.name}")
                    if ping_code not in (0,1):
                        raise RuntimeError(f"ping command failed with status {ping_code}; inspect its captured output")
                    if scenario == "recovery":
                        recovery_thread.join()
                        if recovery_errors: raise RuntimeError(f"recovery link update failed: {recovery_errors[0]}")
                    controller.terminate()
                    controller.wait(timeout=5)
                    controller_log.flush()
                    controller_messages=(results/f"controller_{args.mode}_{scenario}_{repeat}.log").read_text(errors="replace")
                    control_failures=[marker for marker in ("QOS_SETUP_FAILED","QOS_DEGRADE_FAILED","QOS_RECOVERY_FAILED","OPENFLOW_ERROR") if marker in controller_messages]
                    if control_failures:
                        raise RuntimeError("Controller/OVS operation failed: "+", ".join(control_failures))
                    writer.writerow({"timestamp":time.time(),"mode":args.mode,"scenario":scenario,"repeat":repeat,"status":"completed","note":"Live Mininet run; see per-run iperf and ping files plus controller log"})
                    f.flush()
                    progress(f"completed {scenario} ({repeat}/{args.repetitions})")
                except Exception as exc:
                    writer.writerow({"timestamp":time.time(),"mode":args.mode,"scenario":scenario,"repeat":repeat,"status":"failed","note":str(exc)})
                    f.flush()
                    progress(f"FAILED {scenario}: {exc}")
                    raise
                except KeyboardInterrupt:
                    writer.writerow({"timestamp":time.time(),"mode":args.mode,"scenario":scenario,"repeat":repeat,"status":"interrupted","note":"Stopped by user before the timed scenario completed"})
                    f.flush()
                    progress(f"interrupted {scenario}; partial output files are not valid results")
                    raise
                finally:
                    if net is not None: net.stop()
                    controller.terminate()
                    try: controller.wait(timeout=5)
                    except subprocess.TimeoutExpired: controller.kill(); controller.wait()
                    controller_log.close()
    progress(f"all scenarios completed; run index: {outfile}")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--mode",choices=["shortest","load-aware","proposed"],required=True); p.add_argument("--repetitions",type=int,default=3); run(p.parse_args())
