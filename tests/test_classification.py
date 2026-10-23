import json, unittest
from pathlib import Path
from policy import classify_iperf_control, classify_transport


class ClassificationConfigTests(unittest.TestCase):
    def test_protocol_and_ports_are_unique(self):
        cfg=json.loads((Path(__file__).parents[1]/"config.json").read_text())
        pairs={(v["protocol"],v["destination_port"]) for v in cfg["applications"].values()}
        self.assertEqual(len(pairs),3)
        self.assertEqual({x[1] for x in pairs},{5001,5002,5003})
        apps=cfg["applications"]
        self.assertEqual(classify_transport(apps,17,5001),"critical")
        self.assertEqual(classify_transport(apps,17,5002),"realtime")
        self.assertEqual(classify_transport(apps,6,5003),"bulk")
        self.assertIsNone(classify_transport(apps,6,5001))
        self.assertIsNone(classify_transport(apps,1,5001))

    def test_udp_iperf_ports_allow_only_tcp_control_detection(self):
        cfg=json.loads((Path(__file__).parents[1]/"config.json").read_text())
        apps=cfg["applications"]
        self.assertEqual(classify_iperf_control(apps,6,5001),"critical")
        self.assertEqual(classify_iperf_control(apps,6,5002),"realtime")
        self.assertIsNone(classify_iperf_control(apps,17,5001))
        self.assertIsNone(classify_iperf_control(apps,6,5003))


if __name__=="__main__": unittest.main()
