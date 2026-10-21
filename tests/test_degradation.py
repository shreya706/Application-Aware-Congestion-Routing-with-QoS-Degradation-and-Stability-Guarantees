import unittest
from policy import degrade_bulk, recover_bulk, RecoveryMemory


class DegradationTests(unittest.TestCase):
    def test_bounds_and_recovery(self):
        new,reduced=degrade_bulk(6,1,9)
        self.assertEqual(new,1); self.assertEqual(reduced,5)
        self.assertEqual(recover_bulk(new,6,1),2)
    def test_configured_maximum_cut_is_respected(self):
        new,reduced=degrade_bulk(6,1,10,.5,6)
        self.assertEqual(new,3); self.assertEqual(reduced,3)
    def test_recovery_waits_for_clear_intervals(self):
        memory=RecoveryMemory(2)
        self.assertIsNone(memory.update(False,6,1,3,1)[1])
        self.assertIsNone(memory.update(False,6,1,3,1)[1])
        allocation,event=memory.update(False,6,1,3,1)
        self.assertEqual(allocation,3); self.assertEqual(event,{"old_mbps":2,"new_mbps":3})


if __name__=="__main__": unittest.main()
