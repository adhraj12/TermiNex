"""SQLite WAL-backed Flight Recorder storage for system telemetry and events."""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from terminex.config import RECORDER_DB_PATH, FLIGHT_RECORDER_RETENTION_HOURS


class FlightRecorderStore:
    def __init__(self, db_path: Path = RECORDER_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metrics_ring (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    cpu_percent REAL,
                    mem_percent REAL,
                    disk_percent REAL,
                    net_sent_kb REAL,
                    net_recv_kb REAL,
                    load_1m REAL,
                    oom_events INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics_ring(timestamp);

                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_time ON system_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_severity ON system_events(severity);

                CREATE TABLE IF NOT EXISTS file_mutations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    action TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    details TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_file_time ON file_mutations(timestamp);
            """)

    def record_metric(
        self,
        cpu_percent: float,
        mem_percent: float,
        disk_percent: float,
        net_sent_kb: float = 0.0,
        net_recv_kb: float = 0.0,
        load_1m: float = 0.0,
        oom_events: int = 0,
        timestamp: Optional[float] = None,
    ):
        ts = timestamp or time.time()
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO metrics_ring 
                (timestamp, iso_time, cpu_percent, mem_percent, disk_percent, net_sent_kb, net_recv_kb, load_1m, oom_events)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, iso, cpu_percent, mem_percent, disk_percent, net_sent_kb, net_recv_kb, load_1m, oom_events),
            )
            if int(ts) % 100 == 0:
                cutoff = ts - (FLIGHT_RECORDER_RETENTION_HOURS * 3600)
                conn.execute("DELETE FROM metrics_ring WHERE timestamp < ?", (cutoff,))
                conn.execute("DELETE FROM system_events WHERE timestamp < ?", (cutoff,))
                conn.execute("DELETE FROM file_mutations WHERE timestamp < ?", (cutoff,))

    def record_event(
        self,
        event_type: str,
        source: str,
        severity: str,
        title: str,
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ):
        ts = timestamp or time.time()
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        details_str = json.dumps(details or {})
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO system_events
                (timestamp, iso_time, event_type, source, severity, title, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, iso, event_type, source, severity.upper(), title, details_str),
            )

    def record_file_mutation(
        self,
        action: str,
        file_path: str,
        details: str = "",
        timestamp: Optional[float] = None,
    ):
        ts = timestamp or time.time()
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO file_mutations
                (timestamp, iso_time, action, file_path, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, iso, action.upper(), file_path, details),
            )

    def get_recent_metrics(self, duration_minutes: int = 30) -> List[Dict[str, Any]]:
        since_ts = time.time() - (duration_minutes * 60)
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM metrics_ring WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since_ts,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_recent_events(
        self, duration_minutes: int = 60, min_severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        since_ts = time.time() - (duration_minutes * 60)
        query = "SELECT * FROM system_events WHERE timestamp >= ?"
        params: List[Any] = [since_ts]
        if min_severity:
            query += " AND severity = ?"
            params.append(min_severity.upper())
        query += " ORDER BY timestamp DESC"

        with self._connection() as conn:
            cur = conn.execute(query, params)
            results = []
            for row in cur.fetchall():
                d = dict(row)
                try:
                    d["details"] = json.loads(d["details_json"])
                except Exception:
                    d["details"] = {}
                results.append(d)
            return results

    def get_file_mutations(self, duration_minutes: int = 60) -> List[Dict[str, Any]]:
        since_ts = time.time() - (duration_minutes * 60)
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM file_mutations WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since_ts,),
            )
            return [dict(row) for row in cur.fetchall()]
