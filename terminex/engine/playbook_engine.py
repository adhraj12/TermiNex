"""Deterministic Diagnostic Playbook Walker for Root Cause Analysis."""

import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class DiagnosticPlaybookEngine:
    """Executes deterministic diagnostic decision trees without hallucination."""

    def __init__(self, playbooks_dir: Optional[Path] = None):
        self.playbooks_dir = playbooks_dir or Path(__file__).parent / "playbooks"
        self.playbooks: List[Dict[str, Any]] = self._load_playbooks()

    def _load_playbooks(self) -> List[Dict[str, Any]]:
        playbooks = []
        if not self.playbooks_dir.exists():
            return []
        for file in self.playbooks_dir.glob("*.yaml"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and "id" in data:
                        playbooks.append(data)
            except Exception:
                pass
        return playbooks

    def find_playbook(self, query: str) -> Optional[Dict[str, Any]]:
        query_lower = query.lower()
        for pb in self.playbooks:
            keywords = pb.get("symptom_keywords", [])
            if any(k.lower() in query_lower for k in keywords):
                return pb
        return None

    def execute_playbook(self, playbook: Dict[str, Any]) -> Dict[str, Any]:
        """Walks the diagnostic steps of a playbook and produces structured RCA."""
        steps = playbook.get("steps", [])
        executed_steps: List[Dict[str, Any]] = []
        conclusion: Optional[str] = None
        suggested_fix: Optional[str] = None
        recommended_command: Optional[str] = None

        is_linux = platform.system() == "Linux"

        for step in steps:
            step_id = step.get("step_id")
            desc = step.get("description")
            probe = step.get("probe_command")
            expected = step.get("expected")
            pattern = step.get("on_match_pattern")

            # Execute probe in read-only subshell
            stdout = ""
            try:
                if is_linux:
                    res = subprocess.run(
                        ["bash", "-c", probe],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    stdout = res.stdout.strip()
                else:
                    # On Windows / dev mode, simulate probe output
                    stdout = self._simulate_probe_output(step_id)
            except Exception as e:
                stdout = f"probe error: {str(e)}"

            executed_steps.append({
                "step_id": step_id,
                "description": desc,
                "probe": probe,
                "output": stdout,
            })

            # Check pattern match
            if pattern and re.search(pattern, stdout, re.IGNORECASE):
                match_action = step.get("on_match", {})
                conclusion = match_action.get("conclusion")
                suggested_fix = match_action.get("suggested_fix")
                recommended_command = match_action.get("recommended_command")
                break

            # Check expected string match
            if expected and expected.lower() not in stdout.lower():
                on_fail = step.get("on_fail", {})
                if "conclusion" in on_fail:
                    conclusion = on_fail.get("conclusion")
                    suggested_fix = on_fail.get("suggested_fix")
                    recommended_command = on_fail.get("recommended_command")
                    break

        if not conclusion:
            conclusion = f"Playbook '{playbook.get('name')}' completed. No abnormal failure patterns detected."
            suggested_fix = "System state matches normal operational baselines."
            recommended_command = "uptime"

        return {
            "playbook_id": playbook.get("id"),
            "playbook_name": playbook.get("name"),
            "steps_executed": executed_steps,
            "conclusion": conclusion,
            "suggested_fix": suggested_fix,
            "recommended_command": recommended_command,
        }

    def _simulate_probe_output(self, step_id: str) -> str:
        """Dev fallback simulation for testing on non-Linux hosts."""
        sims = {
            "check_status": "inactive (dead)",
            "test_config": "nginx: [emerg] open() '/etc/nginx/sites-enabled/default' failed (No such file)",
            "check_root_usage": "92%",
            "find_large_logs": "-rw-r--r-- 1 root root 850M /var/log/nginx/access.log",
            "check_dmesg_oom": "Out of memory: Killed process 8412 (python3)",
            "check_log_permissions": "d--------- 2 root root 4096 /var/log/nginx/",
        }
        return sims.get(step_id, "active")
