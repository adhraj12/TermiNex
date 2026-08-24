"""Model Context Protocol (MCP) Server for TermiNex."""

import json
from typing import Any, Dict, List, Optional
from terminex.engine.llm_client import LocalLLMClient
from terminex.engine.playbook_engine import DiagnosticPlaybookEngine
from terminex.recorder.store import FlightRecorderStore
from terminex.recorder.timeline import IncidentTimelineEngine
from terminex.safety.ast_validator import ASTSecurityValidator
from terminex.safety.risk_scorer import RiskScorer
from terminex.safety.sandbox import SandboxRehearsalEngine
from terminex.safety.undo_journal import UndoJournal
from terminex.search.file_search import FileSearchEngine


class TermiNexMCPServer:
    """Exposes TermiNex diagnostic, safety, and search capabilities as standard MCP tools."""

    def __init__(self):
        self.store = FlightRecorderStore()
        self.timeline_engine = IncidentTimelineEngine(self.store)
        self.playbook_engine = DiagnosticPlaybookEngine()
        self.validator = ASTSecurityValidator()
        self.risk_scorer = RiskScorer()
        self.sandbox = SandboxRehearsalEngine()
        self.undo_journal = UndoJournal()
        self.search_engine = FileSearchEngine()
        self.llm_client = LocalLLMClient()

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_flight_recorder_timeline",
                "description": "Retroactively queries the black-box flight recorder to reconstruct incident timeline.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_minutes": {"type": "integer", "default": 30},
                        "service_name": {"type": "string", "description": "Optional service name to filter"},
                    },
                },
            },
            {
                "name": "diagnose_system_issue",
                "description": "Walks deterministic diagnostic playbooks for root cause analysis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language symptom or error"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "rehearse_linux_command",
                "description": "Rehearses mutating commands in a sandbox and returns observed file diff.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to dry-run and rehearse"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "search_files_and_configs",
                "description": "Searches files with structural outline compression and zero-leak secret scrubbing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search pattern or content query"},
                        "content_search": {"type": "boolean", "default": False},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "rollback_transaction",
                "description": "Performs one-command atomic rollback of a past transaction.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tx_id": {"type": "string", "description": "Transaction ID (e.g. TX-1092)"},
                    },
                    "required": ["tx_id"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_flight_recorder_timeline":
            minutes = args.get("duration_minutes", 30)
            svc = args.get("service_name")
            return self.timeline_engine.generate_timeline(duration_minutes=minutes, target_service=svc)

        elif tool_name == "diagnose_system_issue":
            query = args.get("query", "")
            pb = self.playbook_engine.find_playbook(query)
            if pb:
                return self.playbook_engine.execute_playbook(pb)
            # Fallback to LLM translation
            return self.llm_client.translate_nl_to_command(query)

        elif tool_name == "rehearse_linux_command":
            cmd = args.get("command", "")
            ast_res = self.validator.validate_command(cmd)
            risk = self.risk_scorer.score_command(cmd, ast_res)
            rehearsal = self.sandbox.rehearse_command(cmd)
            return {
                "command": cmd,
                "ast_analysis": ast_res,
                "risk_tier": risk,
                "rehearsal": rehearsal,
            }

        elif tool_name == "search_files_and_configs":
            query = args.get("query", "")
            if args.get("content_search", False):
                return {"results": self.search_engine.search_content(query)}
            return {"results": self.search_engine.search_by_name(query)}

        elif tool_name == "rollback_transaction":
            tx_id = args.get("tx_id", "")
            return self.undo_journal.rollback(tx_id)

        return {"error": f"Unknown tool '{tool_name}'"}
