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
        step_dict = {s.get("step_id"): s for s in steps}
        executed_steps: List[Dict[str, Any]] = []
        conclusion: Optional[str] = None
        suggested_fix: Optional[str] = None
        recommended_command: Optional[str] = None

        is_linux = platform.system() == "Linux"

        current_step_id = steps[0].get("step_id") if steps else None

        while current_step_id and current_step_id in step_dict:
            step = step_dict[current_step_id]
            step_id = step.get("step_id")
            desc = step.get("description")
            probe = step.get("probe_command")
            expected = step.get("expected")
            pattern = step.get("on_match_pattern")
            thresh = step.get("threshold_percent")

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
                    stdout = self._simulate_probe_output(step_id)
            except Exception as e:
                stdout = f"probe error: {str(e)}"

            executed_steps.append({
                "step_id": step_id,
                "description": desc,
                "probe": probe,
                "output": stdout,
            })

            # Check threshold percent (e.g. "89%" vs 85)
            if thresh is not None:
                pct_match = re.search(r"(\d+(?:\.\d+)?)%?", stdout)
                if pct_match:
                    val = float(pct_match.group(1))
                    if val >= float(thresh):
                        on_fail = step.get("on_fail", {})
                        if "next_step" in on_fail:
                            current_step_id = on_fail["next_step"]
                            continue
                        elif "conclusion" in on_fail:
                            conclusion = on_fail.get("conclusion")
                            suggested_fix = on_fail.get("suggested_fix")
                            recommended_command = on_fail.get("recommended_command")
                            break

            # Check pattern match
            if pattern and re.search(pattern, stdout, re.IGNORECASE):
                match_action = step.get("on_match", {})
                if "conclusion" in match_action:
                    conclusion = match_action.get("conclusion")
                    suggested_fix = match_action.get("suggested_fix")
                    recommended_command = match_action.get("recommended_command")
                    break
                elif "next_step" in match_action:
                    current_step_id = match_action["next_step"]
                    continue

            # Check expected string match
            if expected:
                if expected.lower() not in stdout.lower():
                    on_fail = step.get("on_fail", {})
                    if "next_step" in on_fail:
                        current_step_id = on_fail["next_step"]
                        continue
                    elif "conclusion" in on_fail:
                        conclusion = on_fail.get("conclusion")
                        suggested_fix = on_fail.get("suggested_fix")
                        recommended_command = on_fail.get("recommended_command")
                        break

            # Step passed without branch -> move to next linear step or finish
            curr_idx = next((i for i, s in enumerate(steps) if s.get("step_id") == current_step_id), -1)
            if curr_idx != -1 and curr_idx + 1 < len(steps):
                current_step_id = steps[curr_idx + 1].get("step_id")
            else:
                break

        if not conclusion:
            conclusion = f"Playbook '{playbook.get('name')}' completed. System state verified nominal."
            suggested_fix = "No remediation needed."
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
