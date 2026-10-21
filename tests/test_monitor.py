import unittest
from monitor import CounterSample, rate_mbps, utilization, residual_capacity


class MonitorTests(unittest.TestCase):
    def test_first_interval_and_counter_reset_are_missing(self):
        self.assertIsNone(rate_mbps(None,CounterSample(100,1)))
        self.assertIsNone(rate_mbps(CounterSample(200,1),CounterSample(100,2)))
    def test_rate_utilization_and_residual(self):
        rate=rate_mbps(CounterSample(0,1),CounterSample(125000,2))
        self.assertEqual(rate,1.0)
        self.assertEqual(utilization(rate,10),.1)
        self.assertEqual(residual_capacity(rate,10),9)


if __name__=="__main__": unittest.main()
