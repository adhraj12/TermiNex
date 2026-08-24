"""Model Context Protocol (MCP) Server for TermiNex.

Allows AI environments (Cursor, Claude Desktop, Antigravity IDE) to query
TermiNex Flight Recorder telemetry and execute safe rehearsed Linux operations.
"""

import json
import sys
from typing import Any, Dict, List, Optional
from terminex.recorder.store import FlightRecorderStore
from terminex.recorder.timeline import IncidentTimelineEngine
from terminex.safety.ast_validator import ASTSecurityValidator
from terminex.safety.risk_scorer import RiskScorer
from terminex.safety.sandbox import SandboxRehearsalEngine
from terminex.safety.undo_journal import UndoJournal
from terminex.search.file_search import FileSearchEngine


class TermiNexMCPServer:
    """Core Tool Handlers for TermiNex MCP Protocol."""

    def __init__(self):
        self.store = FlightRecorderStore()
        self.timeline_engine = IncidentTimelineEngine(self.store)
        self.validator = ASTSecurityValidator()
        self.risk_scorer = RiskScorer()
        self.sandbox = SandboxRehearsalEngine()
        self.undo_journal = UndoJournal()
        self.search_engine = FileSearchEngine()

    def get_incident_timeline(self, minutes: int = 30) -> Dict[str, Any]:
        """Query 24-hour black-box flight recorder for anomalies and root-cause correlation."""
        return self.timeline_engine.generate_timeline(duration_minutes=minutes)

    def rehearse_command(self, command: str) -> Dict[str, Any]:
        """Execute command in isolated Bubblewrap/OverlayFS sandbox to preview unified file diffs."""
        ast_res = self.validator.validate_command(command)
        risk = self.risk_scorer.score_command(command, ast_res)
        rehearsal = self.sandbox.rehearse_command(command)
        return {
            "command": command,
            "ast_validation": ast_res,
            "risk_tier": risk,
            "rehearsal": rehearsal,
        }

    def rollback_transaction(self, tx_id: Optional[str] = None) -> Dict[str, Any]:
        """Revert machine state to pre-mutation snapshot using cryptographic audit receipt."""
        if not tx_id:
            txs = self.undo_journal.list_transactions(limit=1)
            if not txs:
                return {"success": False, "message": "No transactions to undo."}
            tx_id = txs[0]["tx_id"]
        return self.undo_journal.rollback(tx_id)

    def search_system_files(self, query: str) -> Dict[str, Any]:
        """Search Linux configurations with AST structural compression and secret redaction."""
        return {
            "query": query,
            "filenames": self.search_engine.search_by_name(query),
            "content_matches": self.search_engine.search_content(query),
        }


def run_fastmcp():
    """Runs FastMCP server if fastmcp is installed, else standard stdio tool server."""
    try:
        from fastmcp import FastMCP
        mcp = FastMCP("TermiNex")
        server = TermiNexMCPServer()

        @mcp.tool()
        def get_timeline(minutes: int = 30) -> str:
            """Query black-box flight recorder telemetry and root cause analysis."""
            return json.dumps(server.get_incident_timeline(minutes), indent=2)

        @mcp.tool()
        def rehearse(command: str) -> str:
            """Rehearse a bash command inside isolated Bubblewrap/OverlayFS twin to preview diffs."""
            return json.dumps(server.rehearse_command(command), indent=2)

        @mcp.tool()
        def undo(tx_id: str = "") -> str:
            """Atomically rollback machine state to pre-mutation snapshot."""
            return json.dumps(server.rollback_transaction(tx_id or None), indent=2)

        @mcp.tool()
        def search_configs(query: str) -> str:
            """Search system files with AST structural compression and secret scrubbing."""
            return json.dumps(server.search_system_files(query), indent=2)

        mcp.run()

    except ImportError:
        # Fallback to standard stdio JSON-RPC loop
        server = TermiNexMCPServer()
        sys.stderr.write("[TermiNex MCP] Running in standard stdio tool mode...\n")
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                req = json.loads(line)
                action = req.get("action")
                args = req.get("args", {})
                if action == "timeline":
                    res = server.get_incident_timeline(args.get("minutes", 30))
                elif action == "rehearse":
                    res = server.rehearse_command(args.get("command", "uptime"))
                elif action == "undo":
                    res = server.rollback_transaction(args.get("tx_id"))
                elif action == "search":
                    res = server.search_system_files(args.get("query", ""))
                else:
                    res = {"error": f"Unknown action: {action}"}
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
            except Exception as e:
                sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    run_fastmcp()
