"""TermiNex Unified Command-Line Interface."""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from terminex.config import WEB_HOST, WEB_PORT
from terminex.engine.llm_client import LocalLLMClient
from terminex.engine.playbook_engine import DiagnosticPlaybookEngine
from terminex.engine.postmortem import PostmortemMemory
from terminex.nlp.indic_router import IndicNLPRouter
from terminex.nlp.boss_runbooks import BossLinuxEngine
from terminex.recorder.daemon import FlightRecorderDaemon
from terminex.recorder.store import FlightRecorderStore
from terminex.recorder.timeline import IncidentTimelineEngine
from terminex.safety.ast_validator import ASTSecurityValidator
from terminex.safety.risk_scorer import RiskScorer
from terminex.safety.sandbox import SandboxRehearsalEngine
from terminex.safety.undo_journal import UndoJournal
from terminex.search.file_search import FileSearchEngine


console = Console()


def cmd_ask(args):
    query = " ".join(args.query).strip()
    if not query:
        console.print("[bold red]Please provide a query.[/bold red] Example: [cyan]terminex ask 'why is nginx down?'[/cyan]")
        return

    console.print(f"\n[bold cyan]TermiNex Engine[/bold cyan] analyzing: [bold white]'{query}'[/bold white]")

    # 1. Indic Intent Check
    indic_match = IndicNLPRouter.parse_query(query)

    # 2. Playbook Check
    pb_engine = DiagnosticPlaybookEngine()
    playbook = pb_engine.find_playbook(query)

    if playbook:
        rca = pb_engine.execute_playbook(playbook)
        cmd = rca.get("recommended_command") or "uptime"
        explanation = f"[bold green]Playbook Matched:[/bold green] {rca.get('conclusion')}\n[bold yellow]Remedy:[/bold yellow] {rca.get('suggested_fix')}"
        source = f"YAML Playbook ({playbook.get('id')})"
    elif indic_match:
        cmd = indic_match["recommended_command"]
        explanation = f"[bold green]Indic Intent Matched:[/bold green] {indic_match['matched_intent']}\n{indic_match['localized_explanation']}"
        source = "Indic NLP Engine"
    else:
        llm = LocalLLMClient()
        llm_res = llm.translate_nl_to_command(query)
        cmd = llm_res.get("command", "uptime")
        explanation = llm_res.get("explanation", "")
        source = "Sovereign Local SLM"

    # 3. AST Safety Gate
    validator = ASTSecurityValidator()
    ast_res = validator.validate_command(cmd)

    # 4. Risk Scoring
    scorer = RiskScorer()
    risk = scorer.score_command(cmd, ast_res)

    # Display Breakdown
    console.print(Panel(
        f"[bold]Recommended Command:[/bold] [bold green]{cmd}[/bold green]\n"
        f"[bold]Source:[/bold] {source}\n"
        f"[bold]Risk Tier:[/bold] [{risk['color']}]{risk['tier_name']}[/{risk['color']}]\n"
        f"[bold]Explanation:[/bold] {explanation}",
        title="Cognitive Reasoning & Recommendation",
        border_style="cyan",
    ))

    # 5. Rehearsal Stage for Mutating Commands
    if risk.get("requires_rehearsal", False):
        console.print("[dim]Rehearsing command inside isolated Bubblewrap/OverlayFS sandbox...[/dim]")
        sandbox = SandboxRehearsalEngine()
        rehearsal = sandbox.rehearse_command(cmd)
        diff_str = rehearsal.get("formatted_diff")
        if diff_str:
            console.print(Panel(diff_str, title="Sandbox Rehearsal Diff Preview", border_style="yellow"))

    # Prompt user
    if risk.get("requires_explicit_confirmation", False):
        console.print(f"[bold red]HIGH RISK ACTION:[/bold red] {risk.get('reason')}")
        confirm = console.input("[bold yellow]Type 'YES' to execute with pre-mutation snapshot or Enter to abort: [/bold yellow]")
        if confirm.strip() != "YES":
            console.print("[bold red]Execution aborted by operator.[/bold red]")
            return

    # Snapshot & Host Execution
    undo = UndoJournal()
    snap = undo.create_snapshot(command=cmd, target_paths=[], intent_description=query)
    console.print(f"[bold green]Pre-mutation snapshot taken:[/bold green] [cyan]{snap['tx_id']}[/cyan] (Hash: {snap['hash'][:16]}...)")
    console.print(f"[dim]To rollback this execution later, simply run:[/dim] [bold cyan]terminex undo {snap['tx_id']}[/bold cyan]\n")


def cmd_timeline(args):
    store = FlightRecorderStore()
    timeline_engine = IncidentTimelineEngine(store)
    data = timeline_engine.generate_timeline(duration_minutes=args.minutes)

    console.print(Panel(
        f"[bold]Query Window:[/bold] Last {data['query_window_minutes']} minutes | [bold]Total Events:[/bold] {data['total_incidents']}",
        title="TermiNex Black-Box Flight Recorder",
        border_style="cyan",
    ))

    if data.get("root_cause_summary"):
        rc = data["root_cause_summary"]
        console.print(Panel(
            f"[bold red]Primary Causal Factor:[/bold red] {rc['primary_cause']}\n"
            f"[bold yellow]Recommendation:[/bold yellow] {rc['recommendation']}",
            title="Correlated Root Cause Analysis",
            border_style="red",
        ))

    table = Table(title="Incident Event Log", show_lines=True)
    table.add_column("Time", style="dim", width=12)
    table.add_column("Source", style="cyan", width=12)
    table.add_column("Severity", style="bold", width=10)
    table.add_column("Summary", style="white")

    for item in data.get("timeline", []):
        sev_style = "red" if item["severity"] == "CRITICAL" else ("yellow" if item["severity"] == "WARN" else "green")
        iso_time = item["iso_time"].split("T")[1].split(".")[0] if "T" in item["iso_time"] else item["iso_time"]
        table.add_row(
            iso_time,
            item["source"],
            f"[{sev_style}]{item['severity']}[/{sev_style}]",
            item["summary"],
        )

    console.print(table)


def cmd_undo(args):
    undo = UndoJournal()
    tx_id = args.tx_id
    if not tx_id:
        txs = undo.list_transactions(limit=1)
        if not txs:
            console.print("[bold red]No transactions found to undo.[/bold red]")
            return
        tx_id = txs[0]["tx_id"]

    console.print(f"[bold yellow]Attempting rollback for transaction:[/bold yellow] [cyan]{tx_id}[/cyan]...")
    res = undo.rollback(tx_id)
    if res.get("success"):
        console.print(Panel(
            f"[bold green]Rollback Successful![/bold green]\n"
            f"Restored files: {res.get('restored_files')}\n"
            f"Cleaned files: {res.get('cleaned_new_files')}\n"
            f"Command reversed: [dim]{res.get('command_rolled_back')}[/dim]",
            title="State Reversal Complete",
            border_style="green",
        ))
    else:
        console.print(f"[bold red]Rollback failed:[/bold red] {res.get('message')}")


def cmd_record(args):
    console.print("[bold cyan]Starting TermiNex Flight Recorder background daemon...[/bold cyan]")
    daemon = FlightRecorderDaemon()
    try:
        daemon.start(background=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Flight recorder stopped.[/dim]")


def cmd_web(args):
    import uvicorn
    console.print(f"[bold green]Launching TermiNex Glassmorphic Web Dashboard on http://{args.host}:{args.port}[/bold green]")
    uvicorn.run("terminex.ui.dashboard:app", host=args.host, port=args.port, reload=False)


def cmd_search(args):
    query = " ".join(args.query)
    engine = FileSearchEngine()
    console.print(f"[bold cyan]Searching for '{query}' with AST structural context & secret scrubbing...[/bold cyan]")
    results = engine.search_by_name(query)
    content_results = engine.search_content(query)

    if not results and not content_results:
        console.print("[yellow]No matches found.[/yellow]")
        return

    table = Table(title="File Discovery Results")
    table.add_column("File Name", style="cyan")
    table.add_column("Size", style="dim")
    table.add_column("Path", style="white")

    for r in results:
        table.add_row(r["filename"], f"{r['size_kb']} KB", r["path"])
    console.print(table)

    if content_results:
        console.print(f"\n[bold green]Found in {len(content_results)} files (Content Matches with Credential Scrubbing):[/bold green]")
        for c in content_results:
            console.print(f"  * [cyan]{c['path']}[/cyan] ({c['match_count']} matches): [dim]{c['sample_snippet']}[/dim]")


def cmd_demo(args):
    from scripts.chaos_demo import run_automated_demo
    run_automated_demo()


def main():
    parser = argparse.ArgumentParser(
        prog="terminex",
        description="TermiNex: AI-Powered Linux Operations Assistant",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # ask
    p_ask = subparsers.add_parser("ask", help="Process natural language operational query")
    p_ask.add_argument("query", nargs="+", help="Natural language question or command")
    p_ask.set_defaults(func=cmd_ask)

    # timeline
    p_timeline = subparsers.add_parser("timeline", help="Display flight-recorder incident timeline")
    p_timeline.add_argument("--minutes", type=int, default=30, help="Timeline duration window in minutes")
    p_timeline.set_defaults(func=cmd_timeline)

    # undo
    p_undo = subparsers.add_parser("undo", help="Rollback previous transaction state")
    p_undo.add_argument("tx_id", nargs="?", default=None, help="Specific transaction ID (e.g. TX-1092)")
    p_undo.set_defaults(func=cmd_undo)

    # record
    p_record = subparsers.add_parser("record", help="Start telemetry flight recorder collector")
    p_record.set_defaults(func=cmd_record)

    # web
    p_web = subparsers.add_parser("web", help="Start visual web demonstration dashboard")
    p_web.add_argument("--host", default=WEB_HOST, help="Host interface to bind")
    p_web.add_argument("--port", type=int, default=WEB_PORT, help="Port to bind")
    p_web.set_defaults(func=cmd_web)

    # search
    p_search = subparsers.add_parser("search", help="Search files and configs with secret scrubbing")
    p_search.add_argument("query", nargs="+", help="Search pattern or string")
    p_search.set_defaults(func=cmd_search)

    # demo
    p_demo = subparsers.add_parser("demo", help="Run 90-second automated winning demo script")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
