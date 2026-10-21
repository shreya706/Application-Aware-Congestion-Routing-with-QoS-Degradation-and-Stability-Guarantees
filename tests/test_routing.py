import unittest
import networkx as nx
from routing import select_path


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.g=nx.Graph()
        self.g.add_edge(1,2,capacity_mbps=10,delay_ms=5,rate_mbps=0)
        self.g.add_edge(2,4,capacity_mbps=10,delay_ms=5,rate_mbps=0)
        self.g.add_edge(1,3,capacity_mbps=10,delay_ms=5,rate_mbps=0)
        self.g.add_edge(3,4,capacity_mbps=10,delay_ms=20,rate_mbps=0)
    def test_lower_delay_realtime_choice(self):
        policy={"max_delay_ms":40,"delay_weight":.9,"capacity_weight":.1}
        result=select_path(self.g,1,4,policy,2)
        self.assertEqual(result.nodes,[1,2,4])
    def test_infeasible_is_explicit(self):
        for a,b in self.g.edges: self.g[a][b]["rate_mbps"]=10
        result=select_path(self.g,1,4,{"max_delay_ms":100,"delay_weight":.5,"capacity_weight":.5},2)
        self.assertIsNotNone(result); self.assertFalse(result.feasible)
    def test_demand_profiles_choose_feasible_branches_differently(self):
        g=nx.Graph()
        g.add_edge(1,2,capacity_mbps=1.5,delay_ms=1,rate_mbps=0)
        g.add_edge(2,4,capacity_mbps=1.5,delay_ms=1,rate_mbps=0)
        g.add_edge(1,3,capacity_mbps=10,delay_ms=20,rate_mbps=0)
        g.add_edge(3,4,capacity_mbps=10,delay_ms=20,rate_mbps=0)
        shared={"max_delay_ms":50,"delay_weight":.7,"capacity_weight":.3}
        critical=select_path(g,1,4,shared,.5)
        realtime=select_path(g,1,4,shared,2)
        bulk=select_path(g,1,4,{**shared,"delay_weight":.15,"capacity_weight":.85},6)
        self.assertEqual(critical.nodes,[1,2,4])
        self.assertEqual(realtime.nodes,[1,3,4])
        self.assertEqual(bulk.nodes,[1,3,4])


if __name__=="__main__": unittest.main()
