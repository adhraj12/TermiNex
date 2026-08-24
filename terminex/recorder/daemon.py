"""Background telemetry collector daemon for TermiNex Flight Recorder."""

import os
import platform
import subprocess
import threading
import time
from typing import Dict, Optional
import psutil
from terminex.config import FLIGHT_RECORDER_INTERVAL_SECONDS
from terminex.recorder.store import FlightRecorderStore


class FlightRecorderDaemon:
    def __init__(self, store: Optional[FlightRecorderStore] = None):
        self.store = store or FlightRecorderStore()
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._last_net = psutil.net_io_counters()
        self._last_time = time.time()
        self._tracked_services = ["nginx", "apache2", "postgresql", "mysql", "ssh", "docker"]
        self._prev_service_states: Dict[str, str] = {}

    def start(self, background: bool = True):
        self.running = True
        if background:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        else:
            self._run_loop()

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def collect_once(self):
        now = time.time()
        dt = max(now - self._last_time, 0.1)

        # 1. Resource Metrics
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        try:
            disk = psutil.disk_usage("/").percent
        except Exception:
            disk = psutil.disk_usage("C:\\").percent if platform.system() == "Windows" else 0.0

        net = psutil.net_io_counters()
        net_sent_kb = (net.bytes_sent - self._last_net.bytes_sent) / (1024 * dt)
        net_recv_kb = (net.bytes_recv - self._last_net.bytes_recv) / (1024 * dt)
        self._last_net = net
        self._last_time = now

        load_1m = 0.0
        if hasattr(os, "getloadavg"):
            try:
                load_1m = os.getloadavg()[0]
            except Exception:
                pass

        self.store.record_metric(
            cpu_percent=cpu,
            mem_percent=mem,
            disk_percent=disk,
            net_sent_kb=round(net_sent_kb, 2),
            net_recv_kb=round(net_recv_kb, 2),
            load_1m=round(load_1m, 2),
        )

        # 2. Check Anomalies
        if disk > 90.0:
            self.store.record_event(
                event_type="DISK_PRESSURE",
                source="storage",
                severity="CRITICAL",
                title=f"Root disk usage exceeded critical threshold: {disk}%",
                details={"disk_percent": disk},
            )
        elif cpu > 95.0:
            self.store.record_event(
                event_type="CPU_SPIKE",
                source="scheduler",
                severity="WARN",
                title=f"CPU saturation warning: {cpu}%",
                details={"cpu_percent": cpu},
            )

        # 3. Check Systemd Units (on Linux)
        if platform.system() == "Linux":
            self._check_linux_services()

    def _check_linux_services(self):
        for svc in self._tracked_services:
            try:
                res = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                state = res.stdout.strip()
                prev = self._prev_service_states.get(svc)
                if prev and prev == "active" and state != "active":
                    # Unit failed or stopped
                    self.store.record_event(
                        event_type="SERVICE_FAIL",
                        source=svc,
                        severity="CRITICAL",
                        title=f"Service '{svc}' transitioned from ACTIVE to {state.upper()}",
                        details={"service": svc, "new_state": state, "prev_state": prev},
                    )
                self._prev_service_states[svc] = state
            except Exception:
                pass

    def _run_loop(self):
        while self.running:
            try:
                self.collect_once()
            except Exception as e:
                pass
            time.sleep(FLIGHT_RECORDER_INTERVAL_SECONDS)
