"""Global configuration and paths for TermiNex."""

import os
from pathlib import Path

# Base configuration directory
TERMINEX_HOME = Path(os.environ.get("TERMINEX_HOME", Path.home() / ".terminex"))
TERMINEX_HOME.mkdir(parents=True, exist_ok=True)

# Storage directories
RECORDER_DB_PATH = TERMINEX_HOME / "flight_recorder.db"
INCIDENTS_DB_PATH = TERMINEX_HOME / "incidents.db"
SNAPSHOTS_DIR = TERMINEX_HOME / "snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_LOG_PATH = TERMINEX_HOME / "audit.jsonl"
SANDBOX_TEMP_DIR = TERMINEX_HOME / "sandbox"
SANDBOX_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Telemetry Ring Buffer Configuration
FLIGHT_RECORDER_INTERVAL_SECONDS = 5
FLIGHT_RECORDER_RETENTION_HOURS = 24
MAX_METRIC_RECORDS = 50000

# LLM Configuration
OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
DEFAULT_LLM_MODEL = os.environ.get("TERMINEX_MODEL", "qwen2.5-coder:7b")
FALLBACK_LLM_MODEL = "llama3.1:8b"

# Web UI Configuration
WEB_HOST = "127.0.0.1"
WEB_PORT = 8420
