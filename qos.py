"""OVS HTB queue management for actual bulk rate enforcement on S4 -> S5."""
import subprocess


def _run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True)


def configure_bulk_queue(interface, capacity_mbps, rate_mbps):
    """Create/update one QoS tree; queue 1 is the bulk queue used by SET_QUEUE."""
    capacity = int(float(capacity_mbps) * 1_000_000)
    rate = int(min(float(rate_mbps), float(capacity_mbps)) * 1_000_000)
    # Reuse existing QoS object when possible. OVSDB failures are surfaced to caller.
    qid = _run(["ovs-vsctl", "--", "--if-exists", "get", "Port", interface, "qos"]).stdout.strip()
    if qid and qid != "[]":
        _run(["ovs-vsctl", "set", "QoS", qid, f"other-config:max-rate={capacity}"])
        queue_id = _run(["ovs-vsctl", "--bare", "get", "QoS", qid, "queues:1"]).stdout.strip()
        if queue_id and queue_id not in ("[]", "{}"):
            _run(["ovs-vsctl", "set", "Queue", queue_id, f"other-config:max-rate={rate}"])
        else:
            _run(["ovs-vsctl", "--", "--id=@q", "create", "Queue", f"other-config:max-rate={rate}", "--", "set", "QoS", qid, "queues:1=@q"])
    else:
        _run(["ovs-vsctl", "--", "--id=@q", "create", "Queue", f"other-config:max-rate={rate}", "--", "--id=@qos", "create", "QoS", "type=linux-htb", f"other-config:max-rate={capacity}", "queues:1=@q", "--", "set", "Port", interface, "qos=@qos"])
    verify_bulk_queue(interface)


def verify_bulk_queue(interface):
    return verify_queue(interface, 1)


def verify_queue(interface, queue_number):
    result = _run(["ovs-vsctl", "--bare", "get", "Port", interface, "qos"]).stdout.strip()
    if result in ("", "[]", "{}"):
        raise RuntimeError(f"No OVS QoS configured on {interface}")
    queue_id = _run(["ovs-vsctl", "--bare", "get", "QoS", result, f"queues:{int(queue_number)}"]).stdout.strip()
    if queue_id in ("", "[]", "{}"):
        raise RuntimeError(f"OVS QoS on {interface} has no queue {queue_number} mapping")
    return result


def configure_reserved_queue(interface, queue_number, minimum_mbps, maximum_mbps):
    """Create/update an OVS queue with a protected minimum and bounded maximum."""
    qos_id = _run(["ovs-vsctl", "--bare", "get", "Port", interface, "qos"]).stdout.strip()
    if qos_id in ("", "[]", "{}"):
        raise RuntimeError(f"No OVS QoS configured on {interface}")
    minimum = int(float(minimum_mbps) * 1_000_000)
    maximum = int(float(maximum_mbps) * 1_000_000)
    queue_id = _run(["ovs-vsctl", "--bare", "get", "QoS", qos_id, f"queues:{int(queue_number)}"]).stdout.strip()
    attrs = [f"other-config:min-rate={minimum}", f"other-config:max-rate={maximum}"]
    if queue_id and queue_id not in ("[]", "{}"):
        _run(["ovs-vsctl", "set", "Queue", queue_id, *attrs])
    else:
        _run(["ovs-vsctl", "--", "--id=@q", "create", "Queue", *attrs, "--", "set", "QoS", qos_id, f"queues:{int(queue_number)}=@q"])
    verify_queue(interface, queue_number)


def set_qos_capacity(interface, capacity_mbps):
    """Change the parent link ceiling without overwriting the current bulk queue rate."""
    qos_id = _run(["ovs-vsctl", "--bare", "get", "Port", interface, "qos"]).stdout.strip()
    if qos_id in ("", "[]", "{}"):
        raise RuntimeError(f"No OVS QoS configured on {interface}")
    capacity = int(float(capacity_mbps) * 1_000_000)
    _run(["ovs-vsctl", "set", "QoS", qos_id, f"other-config:max-rate={capacity}"])
    verify_bulk_queue(interface)


def get_qos_capacity(interface):
    """Read the active OVS parent ceiling in Mbps from OVSDB."""
    qos_id = _run(["ovs-vsctl", "--bare", "get", "Port", interface, "qos"]).stdout.strip()
    if qos_id in ("", "[]", "{}"):
        raise RuntimeError(f"No OVS QoS configured on {interface}")
    value = _run(["ovs-vsctl", "--bare", "get", "QoS", qos_id, "other-config:max-rate"]).stdout.strip()
    try:
        return float(value) / 1_000_000.0
    except ValueError as exc:
        raise RuntimeError(f"OVS QoS on {interface} has no numeric max-rate: {value}") from exc


def cleanup_qos(interface):
    _run(["ovs-vsctl", "--", "clear", "Port", interface, "qos"])
