"""Incident Postmortem Memory database for continuous organizational learning."""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from terminex.config import INCIDENTS_DB_PATH


class PostmortemMemory:
    """Stores resolved incidents and retrieves past solutions to prevent repeating mistakes."""

    def __init__(self, db_path: Path = INCIDENTS_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS postmortems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    resolution_command TEXT NOT NULL,
                    notes TEXT
                );
            """)

    def save_postmortem(
        self, symptom: str, root_cause: str, resolution_command: str, notes: str = ""
    ) -> int:
        ts = time.time()
        iso = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO postmortems (timestamp, iso_time, symptom, root_cause, resolution_command, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts, iso, symptom, root_cause, resolution_command, notes),
            )
            return cur.lastrowid

    def find_similar(self, query: str) -> List[Dict[str, Any]]:
        tokens = [t.lower() for t in query.split() if len(t) > 3]
        if not tokens:
            return []

        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM postmortems ORDER BY timestamp DESC LIMIT 20")
            all_records = [dict(row) for row in cur.fetchall()]

        matches = []
        for r in all_records:
            score = sum(1 for t in tokens if t in r["symptom"].lower() or t in r["root_cause"].lower())
            if score > 0:
                matches.append((score, r))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches[:3]]
