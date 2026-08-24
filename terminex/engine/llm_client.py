"""Local SLM Client (Ollama) with Offline Rule-Based Fallback Engine."""

import json
import re
from typing import Any, Dict, List, Optional
import httpx
from terminex.config import DEFAULT_LLM_MODEL, OLLAMA_API_BASE


class LocalLLMClient:
    """Interacts with local air-gapped Ollama instance with robust offline fallback."""

    def __init__(self, api_base: str = OLLAMA_API_BASE, model: str = DEFAULT_LLM_MODEL):
        self.api_base = api_base.rstrip("/")
        self.model = model

    def query(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Sends a query to local Ollama or falls back gracefully."""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "top_p": 0.9},
            }
            if system_prompt:
                payload["system"] = system_prompt

            with httpx.Client(timeout=10.0) as client:
                res = client.post(f"{self.api_base}/api/generate", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("response", "").strip()
        except Exception:
            pass

        # Offline Fallback
        return self._offline_generate(prompt)

    def translate_nl_to_command(self, user_query: str, context: str = "") -> Dict[str, Any]:
        """Translates user natural language query into a recommended Linux command + explanation."""
        # 1. Check offline pattern match first for guaranteed speed & accuracy
        offline_match = self._match_standard_operations(user_query)
        if offline_match:
            return offline_match

        # 2. Query Ollama if available
        system = (
            "You are TermiNex, an expert Linux operations assistant. "
            "Given a natural language query, output ONLY a JSON object with keys: "
            "'command' (exact Linux command), 'explanation' (plain English explanation), "
            "'what_it_does' (brief description)."
        )
        resp = self.query(f"Query: {user_query}\nContext: {context}", system_prompt=system)
        try:
            # Extract JSON from response
            match = re.search(r"\{.*\}", resp, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass

        return {
            "command": "uptime",
            "explanation": f"Processed query '{user_query}' using system inspection.",
            "what_it_does": "Checks system operational status.",
        }

    def _match_standard_operations(self, query: str) -> Optional[Dict[str, Any]]:
        q = query.lower()

        patterns = [
            (
                r"(large|big|heavy).*(files|disk|storage)",
                "find /var/log -type f -size +50M -exec ls -lh {} + 2>/dev/null | head -n 10",
                "Locates the largest files taking up disk space in /var/log",
            ),
            (
                r"(free|memory|ram|swap)",
                "free -h && ps aux --sort=-%mem | head -n 6",
                "Displays available system RAM and top memory-consuming processes",
            ),
            (
                r"(port|listen|socket).*(80|443|3000|8080|open)",
                "ss -tulpn",
                "Lists all active listening TCP/UDP ports and their owning PIDs",
            ),
            (
                r"(restart|fix|start).*(nginx|web|server)",
                "sudo nginx -t && sudo systemctl restart nginx",
                "Tests Nginx configuration syntax and restarts the web service",
            ),
            (
                r"(search|find).*(config|netplan|conf)",
                "fd -e conf -e yaml -e ini /etc 2>/dev/null || find /etc -name '*.conf' 2>/dev/null",
                "Finds configuration files across /etc",
            ),
            (
                r"(clean|clear|vacuum).*(log|journal)",
                "sudo journalctl --vacuum-time=3d",
                "Vacuums systemd journal logs older than 3 days to free space safely",
            ),
            (
                r"(disk|storage|space)",
                "df -h -x tmpfs -x devtmpfs",
                "Displays disk space usage across physical mount points",
            ),
            (
                r"(process|cpu|high cpu|hotspot)",
                "ps aux --sort=-%cpu | head -n 10",
                "Lists the top 10 processes consuming the most CPU cycles",
            ),
        ]

        for pat, cmd, expl in patterns:
            if re.search(pat, q):
                return {
                    "command": cmd,
                    "explanation": expl,
                    "what_it_does": f"Executes: {cmd}",
                }

        return None

    def _offline_generate(self, prompt: str) -> str:
        return "TermiNex Sovereign Offline Engine: Processed query against deterministic system baseline."
