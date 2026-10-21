#!/usr/bin/env python3
"""OS-Ken OpenFlow 1.3 controller for the fixed student topology."""
import csv, json, time, os
from pathlib import Path
import networkx as nx
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ipv4, arp, udp, tcp, ether_types
from routing import select_path
from monitor import CounterSample, rate_mbps
from policy import FlowState, route_decision, degrade_bulk, RecoveryMemory, classify_transport
from qos import configure_bulk_queue, configure_reserved_queue, get_qos_capacity

ROOT = Path(__file__).resolve().parent
PORTS = {
    1: {"hosts": {"10.0.0.1": 1, "10.0.0.2": 2, "10.0.0.3": 3}, 2: 4, 3: 5},
    2: {1: 1, 4: 2}, 3: {1: 1, 4: 2}, 4: {2: 1, 3: 2, 5: 3},
    5: {"hosts": {"10.0.0.4": 1}, 4: 2}
}
HOST_SWITCH = {"10.0.0.1": 1, "10.0.0.2": 1, "10.0.0.3": 1, "10.0.0.4": 5}


class ApplicationAwareController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = json.loads((ROOT / "config.json").read_text())
        self.mode = os.environ.get("AA_MODE", "proposed")
        self.scenario = os.environ.get("AA_SCENARIO", "normal")
        self.graph = nx.Graph()
        t = self.config["topology"]
        for a,b in [(1,2),(1,3),(2,4),(3,4)]: self.graph.add_edge(a,b, capacity_mbps=t["capacity_mbps"], delay_ms=t["delay_ms"], rate_mbps=0.0)
        if self.scenario == "branch_congestion":
            for edge in [(1,2),(2,4)]: self.graph[edge[0]][edge[1]]["capacity_mbps"] = min(2.0, t["capacity_mbps"])
        bottleneck = min(5.0, t["bottleneck_mbps"]) if self.scenario in ("shared_overload", "recovery") else t["bottleneck_mbps"]
        self.graph.add_edge(4,5, capacity_mbps=bottleneck, delay_ms=t["bottleneck_delay_ms"], rate_mbps=0.0)
        self.datapaths, self.samples, self.flows, self.expected = {}, {}, {}, {}
        self.edge_rates = {}
        self.stats_reply_switches = set()
        self.bulk_rate = float(self.config["applications"]["bulk"]["requested_mbps"])
        self.qos_ready = False
        self.recovery = RecoveryMemory(self.bulk_rate)
        self.last_stats = {}
        self._open_logs()

    def _open_logs(self):
        (ROOT / "results").mkdir(exist_ok=True)
        self.events = open(ROOT / "results/controller_events.csv", "a", newline="", buffering=1)
        self.event_writer = csv.writer(self.events)
        if self.events.tell() == 0: self.event_writer.writerow(["timestamp","mode","scenario","decision","class","src","dst","path","reason","bulk_mbps"])
        self.monitor = open(ROOT / "results/monitoring.csv", "a", newline="", buffering=1)
        self.monitor_writer = csv.writer(self.monitor)
        if self.monitor.tell() == 0: self.monitor_writer.writerow(["timestamp","mode","scenario","switch","port","rate_mbps_estimate","capacity_mbps_used_for_utilization","utilization_estimate"])

    def _log(self, decision, cls, src, dst, path, reason):
        self.event_writer.writerow([time.time(), self.mode, self.scenario, decision, cls, src, dst, "-".join(map(str,path or [])), reason, self.bulk_rate])

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath; self.datapaths[dp.id] = dp
        ofp = dp.ofproto; parser = dp.ofproto_parser
        # Misses go to controller; every learned route is then explicitly installed.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=match, instructions=[parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]))
        if len(self.datapaths) == 5 and not self.qos_ready:
            try:
                initial_queue_rate = self.bulk_rate if self.mode == "proposed" else self.graph[4][5]["capacity_mbps"]
                configure_bulk_queue("s4-eth3", self.graph[4][5]["capacity_mbps"], initial_queue_rate)
                if self.mode == "proposed":
                    apps=self.config["applications"]
                    protected_min=apps["critical"]["minimum_mbps"]+apps["realtime"]["minimum_mbps"]
                    if protected_min > self.graph[4][5]["capacity_mbps"]:
                        raise RuntimeError("QOS_INFEASIBLE: protected minimum allocations exceed shared link capacity")
                    configure_reserved_queue("s4-eth3",2,apps["realtime"]["minimum_mbps"],apps["realtime"]["requested_mbps"])
                    configure_reserved_queue("s4-eth3",3,apps["critical"]["minimum_mbps"],apps["critical"]["requested_mbps"])
                self.qos_ready = True
                self._log("KEEP", "bulk", "-", "-", [], f"OVS queue 1 configured at {initial_queue_rate:.2f} Mbps")
            except Exception as exc:
                self.logger.error("QOS_SETUP_FAILED: %s", exc)
                self._log("QOS_INFEASIBLE", "bulk", "-", "-", [], f"initial OVS queue setup failed: {exc}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg=ev.msg; dp=msg.datapath; parser=dp.ofproto_parser; ofp=dp.ofproto
        pkt=packet.Packet(msg.data); eth=pkt.get_protocol(ethernet.ethernet)
        if not eth or eth.ethertype == ether_types.ETH_TYPE_LLDP: return
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            self._forward_arp(dp, msg, pkt.get_protocol(arp.arp)); return
        ip=pkt.get_protocol(ipv4.ipv4)
        if not ip: return
        udp_h=pkt.get_protocol(udp.udp); tcp_h=pkt.get_protocol(tcp.tcp)
        proto=17 if udp_h else 6 if tcp_h else ip.proto
        sport=udp_h.src_port if udp_h else tcp_h.src_port if tcp_h else 0
        dport=udp_h.dst_port if udp_h else tcp_h.dst_port if tcp_h else 0
        cls=self._classify(proto,dport) or self._classify(proto,sport)
        if cls is None and proto == 1 and ip.src in HOST_SWITCH and ip.dst in HOST_SWITCH:
            try: path=nx.shortest_path(self._active_graph(),HOST_SWITCH[ip.src],HOST_SWITCH[ip.dst])
            except (nx.NetworkXNoPath,nx.NodeNotFound): return
            self._install_bidirectional(path,ip.src,ip.dst,proto,None,None,None)
            self._packet_out(dp,msg,self._next_port(path,dp.id,ip.src,ip.dst))
            return
        if cls is None: return
        reverse = self._classify(proto, dport) is None
        src_host, dst_host = (ip.dst,ip.src) if reverse else (ip.src,ip.dst)
        if dst_host not in HOST_SWITCH: return
        flow_sport, flow_dport = (dport,sport) if reverse else (sport,dport)
        canonical = (src_host,dst_host,proto,flow_sport,flow_dport)
        state=self.flows.get(canonical)
        if state is None:
            policy=self.config["applications"][cls]
            path=self._choose_path(HOST_SWITCH[src_host],HOST_SWITCH[dst_host],policy)
            if path is None: self._log("QOS_INFEASIBLE",cls,src_host,dst_host,[],"no connected candidate path"); return
            if not path.feasible: self._log("QOS_INFEASIBLE",cls,src_host,dst_host,path.nodes,"requested bandwidth exceeds all path estimates")
            state=FlowState(tuple(path.nodes)); self.flows[canonical]=(state,cls,src_host,dst_host,proto,flow_sport,flow_dport)
            for a,b in zip(path.nodes,path.nodes[1:]):
                key=tuple(sorted((a,b))); self.expected[key]=self.expected.get(key,0)+policy["requested_mbps"]
            self._install_bidirectional(state.path, src_host,dst_host,proto,flow_sport,flow_dport,cls)
            self._log("KEEP",cls,src_host,dst_host,state.path,"initial application-aware path installed")
        else:
            state=state[0]
        active_path = list(reversed(state.path)) if reverse else state.path
        self._packet_out(dp,msg,self._next_port(active_path,dp.id,ip.src,ip.dst))

    def _classify(self, proto, port):
        return classify_transport(self.config["applications"], proto, port)

    def _forward_arp(self, dp, msg, request):
        if not request or request.dst_ip not in HOST_SWITCH: return
        source_switch=dp.id; target=HOST_SWITCH[request.dst_ip]
        try: path=nx.shortest_path(self._active_graph(),source_switch,target)
        except (nx.NetworkXNoPath,nx.NodeNotFound): return
        self._packet_out(dp,msg,self._port_between(source_switch,path[1]) if len(path)>1 else PORTS[target]["hosts"][request.dst_ip])

    def _port_between(self, a,b): return PORTS[a][b]

    def _active_graph(self):
        graph=self.graph.copy()
        graph.remove_nodes_from(set(graph.nodes)-set(self.datapaths))
        return graph
    def _next_port(self,path,dpid,src,dst):
        if dpid not in path: return PORTS[dpid]["hosts"].get(dst, PORTS[dpid]["hosts"].get(src))
        i=path.index(dpid)
        if i < len(path)-1: return self._port_between(dpid,path[i+1])
        return PORTS[dpid]["hosts"].get(dst)

    def _packet_out(self,dp,msg,port):
        if port is None: return
        parser=dp.ofproto_parser; ofp=dp.ofproto
        dp.send_msg(parser.OFPPacketOut(datapath=dp,buffer_id=msg.buffer_id,in_port=msg.match.get("in_port"),actions=[parser.OFPActionOutput(port)],data=None if msg.buffer_id!=ofp.OFP_NO_BUFFER else msg.data))

    def _install_bidirectional(self,path,src,dst,proto,sport,dport,cls):
        for route, saddr,daddr,sp,dpn in [(path,src,dst,sport,dport),(list(reversed(path)),dst,src,dport,sport)]:
            # Program destination-side switches first so the ingress is switched last.
            for i in reversed(range(len(route))):
                sw=route[i]
                dp=self.datapaths.get(sw)
                if dp is None: continue
                out=PORTS[sw]["hosts"].get(daddr) if i==len(route)-1 else PORTS[sw][route[i+1]]
                if out is None: continue
                p=dp.ofproto_parser; ofp=dp.ofproto
                fields={"eth_type":ether_types.ETH_TYPE_IP,"ipv4_src":saddr,"ipv4_dst":daddr,"ip_proto":proto}
                if proto in (6,17):
                    fields["udp_src" if proto==17 else "tcp_src"]=sp
                    fields["udp_dst" if proto==17 else "tcp_dst"]=dpn
                actions=[]
                if sw==4 and out==3:
                    queue_id = (1 if cls=="bulk" else 2 if cls=="realtime" else 3 if cls=="critical" else None) if self.qos_ready else None
                    if self.mode != "proposed" and cls != "bulk": queue_id=None
                    if queue_id is not None: actions.append(p.OFPActionSetQueue(queue_id))
                actions.append(p.OFPActionOutput(out))
                match=p.OFPMatch(**fields)
                # The lab has a small fixed flow set; keep entries until rerouted or the switch stops.
                dp.send_msg(p.OFPFlowMod(datapath=dp,priority=100,match=match,instructions=[p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS,actions)],idle_timeout=0,hard_timeout=0))

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def stats_reply(self, ev):
        dp=ev.msg.datapath; now=time.time()
        self.stats_reply_switches.add(dp.id)
        if self.qos_ready and now-self.last_stats.get("capacity_read",0) >= self.config["controller"]["monitor_interval"]:
            self.last_stats["capacity_read"] = now
            try:
                self.graph[4][5]["capacity_mbps"] = get_qos_capacity("s4-eth3")
            except Exception as exc:
                self.logger.warning("Could not read active S4-S5 OVS capacity: %s", exc)
        for stat in ev.msg.body:
            key=(dp.id,stat.port_no); old=self.samples.get(key)
            current=CounterSample(stat.tx_bytes,now); rate=rate_mbps(old,current); self.samples[key]=current
            if rate is None: continue
            cap=self._port_capacity(dp.id,stat.port_no)
            util=rate/cap if cap else None
            self.monitor_writer.writerow([now,self.mode,self.scenario,dp.id,stat.port_no,rate,cap,util])
            # Track only inter-switch links, once, using this switch's transmitting port.
            neighbor=self._neighbor(dp.id,stat.port_no)
            if neighbor:
                self.edge_rates[(dp.id,neighbor)]=rate
                edge=self.graph[dp.id][neighbor]
                edge["rate_mbps"]=self.edge_rates.get((dp.id,neighbor),0.0)+self.edge_rates.get((neighbor,dp.id),0.0)
        online_switches=set(self.datapaths)
        if online_switches and online_switches.issubset(self.stats_reply_switches):
            # Pending reservations cover only flows added since the last complete stats sweep.
            self.expected.clear()
            self.stats_reply_switches.clear()
        self._periodic_policy(now)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def openflow_error(self, ev):
        msg=ev.msg
        self.logger.error("OPENFLOW_ERROR: dpid=%s type=%s code=%s data=%s",msg.datapath.id,msg.type,msg.code,msg.data.hex() if msg.data else "")

    def _port_capacity(self,sw,port):
        neighbor=self._neighbor(sw,port)
        if neighbor is not None: return self.graph[sw][neighbor]["capacity_mbps"]
        return self.config["topology"]["capacity_mbps"]
    def _neighbor(self,sw,port):
        for other,mapping in PORTS.items():
            if isinstance(mapping.get(sw),int) and mapping.get(sw)==port and sw in self.graph and other in self.graph[sw]: return other
        for other in self.graph.neighbors(sw):
            if PORTS[sw].get(other)==port: return other
        return None

    def _periodic_policy(self,now):
        # Polling is driven by stats replies. Stability decisions are logged from these snapshots.
        if now-self.last_stats.get("policy",0)<self.config["controller"]["monitor_interval"]: return
        self.last_stats["policy"]=now
        for key,item in list(self.flows.items()):
            state,cls,src,dst,proto,sport,dport=item
            policy=self.config["applications"][cls]
            active_policy=dict(policy)
            if cls == "bulk": active_policy["requested_mbps"] = self.bulk_rate
            candidate=self._choose_path(HOST_SWITCH[src],HOST_SWITCH[dst],active_policy)
            if candidate is None: self._log("QOS_INFEASIBLE",cls,src,dst,state.path,"no path"); continue
            if any(sw not in self.datapaths for sw in state.path):
                if candidate.feasible:
                    state.path=tuple(candidate.nodes)
                    self._install_bidirectional(state.path,src,dst,proto,sport,dport,cls)
                    self._log("REROUTE",cls,src,dst,state.path,"current path contains a disconnected switch; failure bypassed congestion hold-down")
                else:
                    self._log("QOS_INFEASIBLE",cls,src,dst,state.path,"current path is disconnected and no feasible connected path exists")
                continue
            current_score=0.0
            # Current path estimate uses same scoring function through select_path's helper.
            from routing import estimate_path
            current=estimate_path(self.graph,list(state.path),active_policy,active_policy["requested_mbps"],self.expected)
            current_score=current.score
            if self.mode == "proposed" and not candidate.feasible and cls == "bulk":
                self.recovery.clear_intervals=0
                if candidate.bottleneck_edge != (4,5):
                    self._log("QOS_INFEASIBLE",cls,src,dst,state.path,f"bottleneck {candidate.bottleneck_edge} has no configured bulk queue; no rate change made")
                    continue
                target,reduced=degrade_bulk(
                    self.bulk_rate,
                    policy["minimum_mbps"],
                    max(0.0,self.bulk_rate-candidate.residual_mbps),
                    policy["max_degradation_fraction"],
                    policy["requested_mbps"],
                )
                if reduced > 0:
                    if not self.qos_ready:
                        self._log("QOS_INFEASIBLE",cls,src,dst,state.path,"bulk allocation unchanged because OVS queue is not verified")
                    else:
                        try:
                            configure_bulk_queue("s4-eth3",self.graph[4][5]["capacity_mbps"],target)
                            self.bulk_rate=target
                            self.recovery.allocation_mbps=target
                            self.recovery.clear_intervals=0
                            self._log("DEGRADE",cls,src,dst,state.path,f"OVS queue capped bulk at {target:.2f} Mbps; reduced by {reduced:.2f} Mbps")
                        except Exception as exc:
                            self.logger.error("QOS_DEGRADE_FAILED: %s", exc)
                            self._log("QOS_INFEASIBLE",cls,src,dst,state.path,f"OVS queue update failed; allocation unchanged: {exc}")
                else:
                    self._log("QOS_INFEASIBLE",cls,src,dst,state.path,"bulk is already at its configured minimum and the path remains infeasible")
                continue
            if not candidate.feasible and cls != "bulk":
                self._log("QOS_INFEASIBLE",cls,src,dst,state.path,"protected flow requirement cannot fit current path capacity")
                continue
            if self.mode == "proposed" and cls == "bulk" and candidate.feasible:
                old_allocation=self.recovery.allocation_mbps
                new_rate,event=self.recovery.update(False,policy["requested_mbps"],policy["minimum_mbps"],self.config["recovery"]["clear_intervals"],self.config["recovery"]["step_mbps"])
                if event:
                    try:
                        if not self.qos_ready: raise RuntimeError("OVS queue is not verified")
                        configure_bulk_queue("s4-eth3",self.graph[4][5]["capacity_mbps"],new_rate)
                        self.bulk_rate=new_rate
                        self._log("RECOVER",cls,src,dst,state.path,f"OVS queue raised gradually {event['old_mbps']:.2f}->{event['new_mbps']:.2f} Mbps")
                    except Exception as exc:
                        self.recovery.allocation_mbps=old_allocation
                        self.recovery.clear_intervals=max(0,self.config["recovery"]["clear_intervals"]-1)
                        self.logger.error("QOS_RECOVERY_FAILED: %s", exc)
                        self._log("QOS_INFEASIBLE",cls,src,dst,state.path,f"OVS queue recovery failed; allocation unchanged: {exc}")
                continue
            if self.mode == "shortest":
                self._log("KEEP",cls,src,dst,state.path,"fixed shortest-path baseline"); continue
            if self.mode == "load-aware":
                if candidate.nodes != list(state.path):
                    state.path=tuple(candidate.nodes); self._install_bidirectional(state.path,src,dst,proto,sport,dport,cls)
                    self._log("REROUTE",cls,src,dst,state.path,"load-aware baseline selected the currently best residual path")
                else: self._log("KEEP",cls,src,dst,state.path,"load-aware baseline kept current path")
                continue
            decision,reason=route_decision(state,candidate.nodes,current_score,candidate.score,now,
                self.config["routing"]["improvement_fraction"],self.config["routing"]["stable_intervals"],
                self.config["routing"]["cooldown_seconds"],self.config["routing"]["crm_memory_seconds"],self.config["routing"]["crm_reversal_penalty"])
            if decision=="REROUTE": self._install_bidirectional(state.path,src,dst,proto,sport,dport,cls)
            self._log(decision,cls,src,dst,state.path,reason)

    def _choose_path(self, source, destination, policy):
        graph=self._active_graph()
        if self.mode == "shortest":
            try:
                from routing import estimate_path
                path=nx.shortest_path(graph,source,destination)
                return estimate_path(graph,path,policy,policy["requested_mbps"],{})
            except (nx.NetworkXNoPath,nx.NodeNotFound): return None
        if self.mode == "load-aware":
            paths=[]
            try: candidate_paths=nx.shortest_simple_paths(graph,source,destination,weight="delay_ms")
            except (nx.NetworkXNoPath,nx.NodeNotFound): return None
            for p in candidate_paths:
                est=estimate_path(graph,p,policy,policy["requested_mbps"],self.expected); paths.append(est)
                if len(paths)>=self.config["routing"]["candidate_paths"]: break
            return min(paths,key=lambda x:x.utilization) if paths else None
        return select_path(graph,source,destination,policy,policy["requested_mbps"],self.expected,count=self.config["routing"]["candidate_paths"])

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def state_change(self, ev):
        dp=ev.datapath
        if ev.state==MAIN_DISPATCHER:
            self.datapaths[dp.id]=dp
            if not self.last_stats.get("poll_started"):
                self.last_stats["poll_started"]=True
                from os_ken.lib import hub
                self._poller=hub.spawn(self._poll_stats)
        elif ev.state==CONFIG_DISPATCHER:
            self.datapaths.pop(dp.id,None)
            self.qos_ready=False
            for key in [key for key in self.samples if key[0]==dp.id]: self.samples.pop(key,None)
            for edge_key in [key for key in self.edge_rates if dp.id in key]: self.edge_rates.pop(edge_key,None)
            for neighbor in self.graph.neighbors(dp.id):
                self.graph[dp.id][neighbor]["rate_mbps"]=self.edge_rates.get((neighbor,dp.id),0.0)

    def _poll_stats(self):
        from os_ken.lib import hub
        while True:
            for dp in list(self.datapaths.values()):
                dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp,0,dp.ofproto.OFPP_ANY))
            hub.sleep(self.config["controller"]["monitor_interval"])
