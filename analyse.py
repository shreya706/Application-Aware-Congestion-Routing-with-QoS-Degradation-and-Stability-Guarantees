#!/usr/bin/env python3
"""Summarise raw experiment outputs and plot measured iperf throughput."""
import argparse, json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import re

ROOT=Path(__file__).resolve().parent


def analyse(results_dir=ROOT/"results"):
    rows=[]
    for path in results_dir.glob("iperf_*.json"):
        try:
            raw=json.loads(path.read_text()); end=raw.get("end",{}); summ=end.get("sum_received",end.get("sum",{}))
            match=re.match(r"iperf_(.+)_(normal|branch_congestion|shared_overload|recovery)_(\d+)_(5001|5002|5003)\.json$",path.name)
            if not match: continue
            mode,scenario,repeat,port=match.groups(); profile=json.loads((ROOT/"config.json").read_text())["applications"]
            cls={"5001":"critical","5002":"realtime","5003":"bulk"}[port]; policy=profile[cls]
            throughput=summ.get("bits_per_second",0)/1e6; jitter=summ.get("jitter_ms"); loss=summ.get("lost_percent")
            satisfied=throughput >= policy["minimum_mbps"]
            if jitter is not None: satisfied = satisfied and jitter <= policy["max_jitter_ms"]
            if loss is not None: satisfied = satisfied and loss <= policy["max_loss_percent"]
            rows.append({"mode":mode,"scenario":scenario,"repeat":int(repeat),"class":cls,"file":path.name,"throughput_mbps":throughput,
                         "jitter_ms":jitter,"lost_percent":loss,"qos_satisfied":bool(satisfied),
                         "note":"receiver throughput plus available configured jitter/loss limits; missing metrics are not inferred"})
        except (OSError,ValueError,TypeError): continue
    frame=pd.DataFrame(rows)
    csv_path=results_dir/"summary.csv"; frame.to_csv(csv_path,index=False)
    if not frame.empty:
        grouped=frame.groupby(["mode","scenario","class"],as_index=False).agg(throughput_mbps=("throughput_mbps","mean"),qos_satisfaction_rate=("qos_satisfied","mean"),jitter_ms=("jitter_ms","mean"),lost_percent=("lost_percent","mean"))
        grouped.to_csv(results_dir/"mode_summary.csv",index=False)
        for metric in ("throughput_mbps","jitter_ms","lost_percent","qos_satisfaction_rate"):
            plot=grouped.pivot_table(index=["scenario","class"],columns="mode",values=metric)
            ax=plot.plot.bar(figsize=(10,5),title=f"Mean {metric.replace('_',' ')} by mode and scenario")
            ax.set_ylabel(metric.replace("_"," ")); plt.tight_layout(); plt.savefig(results_dir/f"{metric}.png",dpi=160); plt.close()
    events_path=results_dir/"controller_events.csv"
    if events_path.exists():
        events=pd.read_csv(events_path)
        if {"mode","scenario","decision"}.issubset(events.columns):
            events.groupby(["mode","scenario","decision"]).size().rename("count").reset_index().to_csv(results_dir/"decision_summary.csv",index=False)
    ping_rows=[]
    for path in results_dir.glob("ping_*.txt"):
        match=re.match(r"ping_(.+)_(normal|branch_congestion|shared_overload|recovery)_(\d+)\.txt$",path.name)
        if not match: continue
        mode,scenario,repeat=match.groups(); body=path.read_text(errors="replace")
        found=re.search(r"(?:round-trip|rtt) min/avg/max/(?:mdev|stddev) = [\d.]+/([\d.]+)/",body)
        ping_rows.append({"mode":mode,"scenario":scenario,"repeat":int(repeat),"rtt_avg_ms":float(found.group(1)) if found else None})
    if ping_rows:
        pings=pd.DataFrame(ping_rows); pings.to_csv(results_dir/"ping_summary.csv",index=False)
        pings.groupby(["mode","scenario"],as_index=False)["rtt_avg_ms"].mean().to_csv(results_dir/"rtt_mode_summary.csv",index=False)
    monitoring_path=results_dir/"monitoring.csv"
    if monitoring_path.exists():
        monitored=pd.read_csv(monitoring_path)
        if {"mode","scenario","utilization_estimate"}.issubset(monitored.columns):
            links=monitored.groupby(["mode","scenario"],as_index=False)["utilization_estimate"].mean()
            links.to_csv(results_dir/"link_utilization_summary.csv",index=False)
    return frame


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--results",type=Path,default=ROOT/"results"); args=parser.parse_args()
    print(analyse(args.results).to_string(index=False))
