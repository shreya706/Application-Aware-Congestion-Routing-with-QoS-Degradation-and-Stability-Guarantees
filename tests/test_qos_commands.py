import unittest
from unittest.mock import patch
from types import SimpleNamespace
import qos


class OVSQueueCommandTests(unittest.TestCase):
    def test_reads_parent_capacity_from_ovsdb(self):
        with patch("qos._run", side_effect=[SimpleNamespace(stdout="qos-id\n"), SimpleNamespace(stdout="10000000\n")]) as run:
            self.assertEqual(qos.get_qos_capacity("s4-eth3"),10.0)
            self.assertEqual(run.call_count,2)

    def test_queue_create_uses_max_rate_ceiling(self):
        with patch("qos._run", return_value=SimpleNamespace(stdout="[]\n")) as run, patch("qos.verify_bulk_queue"):
            qos.configure_bulk_queue("s4-eth3",10,2.5)
            create=run.call_args.args[0]
            self.assertIn("other-config:max-rate=2500000",create)
            self.assertFalse(any("min-rate" in arg for arg in create))

    def test_existing_queue_is_updated_in_place(self):
        with patch("qos._run", side_effect=[SimpleNamespace(stdout="qos-id\n"), SimpleNamespace(stdout=""), SimpleNamespace(stdout="queue-id\n"), SimpleNamespace(stdout="")]) as run, patch("qos.verify_bulk_queue"):
            qos.configure_bulk_queue("s4-eth3",10,1.5)
            self.assertIn("set",run.call_args_list[3].args[0])
            self.assertIn("other-config:max-rate=1500000",run.call_args_list[3].args[0])

    def test_reserved_queue_sets_minimum_and_maximum(self):
        responses=["qos-id\n","[]\n","","qos-id\n","queue-id\n"]
        with patch("qos._run", side_effect=[SimpleNamespace(stdout=value) for value in responses]) as run:
            qos.configure_reserved_queue("s4-eth3",2,1,2)
            create=run.call_args_list[2].args[0]
            self.assertIn("other-config:min-rate=1000000",create)
            self.assertIn("other-config:max-rate=2000000",create)


if __name__=="__main__": unittest.main()
