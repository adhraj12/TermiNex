"""Incident Timeline & Time-Travel root cause correlator for TermiNex."""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from terminex.recorder.store import FlightRecorderStore


class IncidentTimelineEngine:
    def __init__(self, store: Optional[FlightRecorderStore] = None):
        self.store = store or FlightRecorderStore()

    def generate_timeline(
        self, duration_minutes: int = 30, target_service: Optional[str] = None
    ) -> Dict[str, Any]:
        """Correlate metrics, system events, and file mutations into a chronological narrative."""
        events = self.store.get_recent_events(duration_minutes=duration_minutes)
        mutations = self.store.get_file_mutations(duration_minutes=duration_minutes)
        metrics = self.store.get_recent_metrics(duration_minutes=duration_minutes)

        timeline_items: List[Dict[str, Any]] = []

        # 1. Add System Events
        for ev in events:
            if target_service and target_service.lower() not in ev["source"].lower() and target_service.lower() not in ev["title"].lower():
                continue
            timeline_items.append({
                "timestamp": ev["timestamp"],
                "iso_time": ev["iso_time"],
                "type": "SYSTEM_EVENT",
                "category": ev["event_type"],
                "source": ev["source"],
                "severity": ev["severity"],
                "summary": ev["title"],
                "details": ev.get("details", {}),
            })

        # 2. Add File Mutations
        for mut in mutations:
            if target_service and target_service.lower() not in mut["file_path"].lower():
                continue
            timeline_items.append({
                "timestamp": mut["timestamp"],
                "iso_time": mut["iso_time"],
                "type": "FILE_MUTATION",
                "category": mut["action"],
                "source": "vfs",
                "severity": "WARN" if mut["action"] == "DELETE" else "INFO",
                "summary": f"File {mut['action']}: {mut['file_path']}",
                "details": {"details": mut["details"]},
            })

        # 3. Detect Metric Anomalies (Memory jumps, CPU spikes)
        for i in range(1, len(metrics)):
            curr = metrics[i]
            prev = metrics[i - 1]
            if curr["cpu_percent"] and curr["cpu_percent"] >= 90.0:
                timeline_items.append({
                    "timestamp": curr["timestamp"],
                    "iso_time": curr["iso_time"],
                    "type": "METRIC_ANOMALY",
                    "category": "CPU_SPIKE",
                    "source": "kernel",
                    "severity": "WARN",
                    "summary": f"High CPU utilization sustained at {curr['cpu_percent']}%",
                    "details": curr,
                })
            if curr["mem_percent"] and prev["mem_percent"] and (curr["mem_percent"] - prev["mem_percent"] > 25.0):
                timeline_items.append({
                    "timestamp": curr["timestamp"],
                    "iso_time": curr["iso_time"],
                    "type": "METRIC_ANOMALY",
                    "category": "MEMORY_SURGE",
                    "source": "kernel",
                    "severity": "CRITICAL",
                    "summary": f"Rapid memory surge from {prev['mem_percent']}% to {curr['mem_percent']}%",
                    "details": curr,
                })

        # Sort timeline chronologically (oldest to newest)
        timeline_items.sort(key=lambda x: x["timestamp"])

        # Determine Root Cause Candidate
        root_cause = self._identify_root_cause(timeline_items)

        return {
            "query_window_minutes": duration_minutes,
            "total_incidents": len(timeline_items),
            "timeline": timeline_items,
            "root_cause_summary": root_cause,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _identify_root_cause(self, timeline: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Heuristic causal chain builder: e.g. File deletion -> Service crash."""
        if not timeline:
            return None

        # Look for a file mutation followed closely by a service failure
        for i, item in enumerate(timeline):
            if item["type"] == "FILE_MUTATION" and item["category"] in ("DELETE", "MODIFY"):
                # Check if a subsequent item is a service failure
                for next_item in timeline[i + 1 :]:
                    if next_item.get("category") == "SERVICE_FAIL":
                        return {
                            "primary_cause": f"Configuration/Dependency issue: {item['summary']}",
                            "trigger_event": item,
                            "impact_event": next_item,
                            "confidence": "HIGH",
                            "recommendation": f"Inspect or restore {item['summary'].split(': ')[-1]} and restart {next_item['source']}.",
                        }

        # Fallback to the highest severity event
        critical_events = [t for t in timeline if t.get("severity") == "CRITICAL"]
        if critical_events:
            return {
                "primary_cause": critical_events[0]["summary"],
                "trigger_event": critical_events[0],
                "confidence": "MEDIUM",
                "recommendation": "Review recent logs and verify service configuration.",
            }

        return None
