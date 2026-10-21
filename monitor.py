"""Counter-delta monitoring helpers. Rates are estimates from OpenFlow counters."""
from dataclasses import dataclass


@dataclass
class CounterSample:
    tx_bytes: int
    timestamp: float


def rate_mbps(previous, current):
    if previous is None or current is None:
        return None
    elapsed = current.timestamp - previous.timestamp
    delta = current.tx_bytes - previous.tx_bytes
    if elapsed <= 0 or delta < 0:  # first sample, reset, or counter wrap
        return None
    return 8.0 * delta / elapsed / 1_000_000.0


def utilization(rate, capacity):
    if rate is None or capacity is None or capacity <= 0:
        return None
    return max(0.0, rate / capacity)


def residual_capacity(rate, capacity):
    if rate is None or capacity is None or capacity <= 0:
        return None
    return max(0.0, capacity - rate)
