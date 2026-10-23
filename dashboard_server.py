#!/usr/bin/env python3
"""Local web control panel for the Mininet demo. Run only on Ubuntu as root."""
from __future__ import annotations

import csv
import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
MODES = {"proposed", "shortest", "load-aware"}
SCENARIOS = {"normal", "branch_congestion", "shared_overload", "recovery"}
state_lock = threading.RLock()
state = {
    "controller": None,
    "controller_log": None,
    "topology": None,
    "experiment": None,
    "experiment_log": None,
    "analysis_running": False,
    "mode": "proposed",
    "scenario": "normal",
    "output": deque(maxlen=120),
}


def clean_env(**extra):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({key: str(value) for key, value in extra.items()})
    env["PYTHONUNBUFFERED"] = "1"
    return env


def append_output(line):
    with state_lock:
        state["output"].append(line.rstrip())


def capture_output(process, label):
    try:
        for line in process.stdout:
            append_output(f"[{label}] {line}")
    except (OSError, ValueError):
        pass


def spawn_reader(process, label):
    threading.Thread(target=capture_output, args=(process, label), daemon=True).start()


def run_cleanup():
    subprocess.run(["mn", "-c"], cwd=ROOT, env=clean_env(), check=True, timeout=45,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    subprocess.run(["ovs-vsctl", "--if-exists", "clear", "Port", "s4-eth3", "qos"],
                   cwd=ROOT, env=clean_env(), check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def alive(proc):
    return proc is not None and proc.poll() is None


def tail_csv(name, count=20):
    path = ROOT / "results" / name
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            return list(csv.DictReader(f))[-count:]
    except OSError:
        return []


def generate_summary():
    try:
        result = subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(ROOT / "analyse.py")],
            cwd=ROOT, env=clean_env(), check=True, timeout=180,
            capture_output=True, text=True,
        )
        append_output("Experiment summary and graphs updated from the result files.")
        if result.stdout.strip():
            append_output(result.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError) as exc:
        append_output(f"Experiment completed, but summary generation failed: {exc}")
    finally:
        with state_lock:
            state["analysis_running"] = False


def start_lab(mode, scenario):
    if mode not in MODES or scenario not in SCENARIOS:
        raise ValueError("Choose a supported mode and scenario.")
    with state_lock:
        if alive(state["experiment"]):
            raise RuntimeError("Stop the running experiment before starting the interactive lab.")
        if alive(state["topology"]):
            return "The lab is already running."
        state["mode"], state["scenario"] = mode, scenario
        state["output"].clear()
        append_output("Cleaning up old Mininet interfaces…")
        run_cleanup()
        log_path = ROOT / "results" / "dashboard_controller.log"
        log = log_path.open("a", encoding="utf-8", buffering=1)
        env = clean_env(AA_MODE=mode, AA_SCENARIO=scenario)
        controller = subprocess.Popen(
            [str(ROOT / ".venv/bin/osken-manager"), str(ROOT / "controller.py")],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        state["controller"], state["controller_log"] = controller, log
        time.sleep(1.5)
        if not alive(controller):
            log.flush()
            raise RuntimeError("Controller exited during startup. Check results/dashboard_controller.log.")
        topology = subprocess.Popen(
            ["/usr/bin/python3", "-u", str(ROOT / "topology.py")],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
        )
        state["topology"] = topology
        spawn_reader(topology, "network")
        time.sleep(1.5)
        if not alive(topology):
            stop_lab()
            raise RuntimeError("Mininet failed to start. Read the Network output below and check the Ubuntu packages.")
        append_output("Network started. Use Check connectivity to run pingall.")
        return "Network started."


def stop_process(proc, grace=8):
    if not alive(proc):
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=grace)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=3)


def stop_lab():
    with state_lock:
        topology = state.get("topology")
        if alive(topology):
            try:
                topology.stdin.write("exit\n")
                topology.stdin.flush()
                topology.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired, AttributeError):
                stop_process(topology)
        state["topology"] = None
        stop_process(state.get("controller"))
        state["controller"] = None
        log = state.get("controller_log")
        if log:
            log.close()
            state["controller_log"] = None
        if not alive(state.get("experiment")):
            try:
                run_cleanup()
                append_output("Lab stopped and Mininet state cleaned up.")
            except (OSError, subprocess.SubprocessError) as exc:
                append_output(f"Cleanup reported: {exc}")
        return "Lab stopped."


def run_experiment(mode, repetitions):
    if mode not in MODES:
        raise ValueError("Choose a supported routing mode.")
    repetitions = int(repetitions)
    if not 1 <= repetitions <= 10:
        raise ValueError("Repetitions must be between 1 and 10.")
    with state_lock:
        if alive(state["topology"]):
            raise RuntimeError("Stop the interactive lab before running an experiment.")
        if alive(state["experiment"]):
            raise RuntimeError("An experiment is already running.")
        run_cleanup()
        append_output(f"Starting {mode} experiment ({repetitions} repetition(s)); this may take several minutes…")
        log = subprocess.Popen(
            ["/usr/bin/python3", str(ROOT / "run_experiment.py"),
             "--mode", mode, "--repetitions", str(repetitions)],
            cwd=ROOT, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )
        state["experiment"], state["experiment_log"] = log, None
        spawn_reader(log, "experiment")
        return "Experiment started. Progress appears below."


def stop_experiment():
    with state_lock:
        proc = state.get("experiment")
        if not alive(proc):
            return "No experiment is running."
        stop_process(proc, grace=3)
        state["experiment"] = None
        append_output("Experiment stopped by user; its partial results should not be treated as complete.")
        try:
            run_cleanup()
        except (OSError, subprocess.SubprocessError) as exc:
            append_output(f"Cleanup reported: {exc}")
        return "Experiment stopped."


def snapshot():
    with state_lock:
        for name in ("topology", "controller", "experiment"):
            proc = state.get(name)
            if proc is not None and proc.poll() is not None:
                if name == "topology":
                    state[name] = None
                elif name == "experiment":
                    state[name] = None
                    if proc.returncode == 0:
                        append_output("Experiment finished. Updating its result summary…")
                        state["analysis_running"] = True
                        threading.Thread(target=generate_summary, daemon=True).start()
                    else:
                        append_output(f"Experiment stopped with exit code {proc.returncode}.")
                elif name == "controller":
                    append_output(f"Controller stopped (exit code {proc.returncode}).")
                    state[name] = None
        return {
            "controller_running": alive(state["controller"]),
            "network_running": alive(state["topology"]),
            "experiment_running": alive(state["experiment"]),
            "analysis_running": state["analysis_running"],
            "mode": state["mode"], "scenario": state["scenario"],
            "output": list(state["output"]),
            "events": tail_csv("controller_events.csv"),
            "monitoring": tail_csv("monitoring.csv"),
            "experiment_runs": tail_csv("experiment_runs.csv"),
            "summary": tail_csv("mode_summary.csv", 60),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "AARDashboard/1.0"

    def send_json(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self.send_json(snapshot())
            return
        if path in ("/", "/dashboard/index.html"):
            try:
                payload = (ROOT / "dashboard/index.html").read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self):
        # Bind to loopback and reject cross-origin browser posts. The API exposes
        # only fixed actions; it never accepts a shell command from the page.
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            self.send_error(403)
            return
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765"):
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 4096:
                raise ValueError("Request is too large.")
            payload = json.loads(self.rfile.read(size) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/start":
                message = start_lab(payload.get("mode", "proposed"), payload.get("scenario", "normal"))
            elif path == "/api/stop":
                message = stop_lab()
            elif path == "/api/ping":
                with state_lock:
                    proc = state.get("topology")
                    if not alive(proc):
                        raise RuntimeError("Start the network before checking connectivity.")
                    proc.stdin.write("pingall\n")
                    proc.stdin.flush()
                message = "Connectivity check sent."
            elif path == "/api/experiment":
                message = run_experiment(payload.get("mode", "proposed"), payload.get("repetitions", 1))
            elif path == "/api/experiment/stop":
                message = stop_experiment()
            else:
                self.send_error(404)
                return
            self.send_json({"ok": True, "message": message})
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "message": str(exc)}, 400)

    def log_message(self, fmt, *args):
        return


def main():
    if os.name != "posix" or not Path("/usr/bin/python3").exists():
        raise SystemExit("The dashboard controller service must run on Ubuntu/Linux.")
    if os.geteuid() != 0:
        raise SystemExit("Run the dashboard service through the provided systemd installer (it runs as root).")
    if not (ROOT / ".venv/bin/osken-manager").is_file():
        raise SystemExit("Dependencies are missing. Run scripts/install_dependencies.sh first.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    finally:
        stop_lab()
        stop_experiment()
        server.server_close()


if __name__ == "__main__":
    main()
