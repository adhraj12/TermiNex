"""TermiNex Unified Command-Line Interface."""

import argparse
import os
import platform
import subprocess
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

    # 1. Check Past Incident Memory first (Learning from experience)
    postmortem_mem = PostmortemMemory()
    similar_incidents = postmortem_mem.find_similar(query)
    if similar_incidents:
        past = similar_incidents[0]
        console.print(Panel(
            f"[bold yellow]Found matching historical resolution in incident memory:[/bold yellow]\n"
            f"[bold]Past Symptom:[/bold] {past['symptom']}\n"
            f"[bold]Root Cause:[/bold] {past['root_cause']}\n"
            f"[bold green]Tested Solution:[/bold green] {past['resolution_command']}",
            title="Incident Memory Match",
            border_style="yellow",
        ))

    # 2. Indic Intent Check
    indic_match = IndicNLPRouter.parse_query(query)

    # 3. Playbook Check
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

    # 4. AST Safety Gate
    validator = ASTSecurityValidator()
    ast_res = validator.validate_command(cmd)

    # 5. Risk Scoring
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

    affected_paths = []
    # 6. Rehearsal Stage for Mutating Commands
    if risk.get("requires_rehearsal", False):
        console.print("[dim]Rehearsing command inside isolated Bubblewrap/OverlayFS sandbox...[/dim]")
        sandbox = SandboxRehearsalEngine()
        rehearsal = sandbox.rehearse_command(cmd)
        affected_paths = rehearsal.get("affected_paths", [])
        diff_str = rehearsal.get("formatted_diff")
        if diff_str:
            console.print(Panel(diff_str, title="Sandbox Rehearsal Diff Preview", border_style="yellow"))

    # Prompt user if dangerous or mutating
    if risk.get("requires_explicit_confirmation", False):
        console.print(f"[bold red]HIGH RISK ACTION:[/bold red] {risk.get('reason')}")
        confirm = console.input("[bold yellow]Type 'YES' to execute with pre-mutation snapshot or Enter to abort: [/bold yellow]")
        if confirm.strip() != "YES":
            console.print("[bold red]Execution aborted by operator.[/bold red]")
            return
    elif risk.get("tier", 0) > 0:
        confirm = console.input("[bold yellow]Execute command with snapshot? [Y/n]: [/bold yellow]")
        if confirm.strip().lower() in ("n", "no"):
            console.print("[bold red]Execution aborted by operator.[/bold red]")
            return

    # 7. Take Real Snapshot of Affected Paths
    undo = UndoJournal()
    snap = undo.create_snapshot(command=cmd, target_paths=affected_paths, intent_description=query)
    console.print(f"[bold green]Pre-mutation snapshot taken:[/bold green] [cyan]{snap['tx_id']}[/cyan] ({len(affected_paths)} target paths protected)")

    # 8. Real Host Execution
    console.print(f"[dim]Executing on host: {cmd}...[/dim]")
    is_linux = platform.system() == "Linux"
    shell_cmd = ["bash", "-c", cmd] if is_linux else ["powershell", "-Command", cmd]

    try:
        proc = subprocess.run(shell_cmd, capture_output=True, text=True, timeout=30)
        exit_code = proc.returncode
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if stdout:
            console.print(f"[bold white]{stdout}[/bold white]")
        if stderr:
            console.print(f"[yellow]{stderr}[/yellow]")

        if exit_code == 0:
            console.print(f"[bold green]Execution Succeeded (ExitCode: 0)[/bold green]")
            # Save to incident memory for continuous learning
            postmortem_mem.save_postmortem(
                symptom=query,
                root_cause=explanation,
                resolution_command=cmd,
                notes=f"Snapshot: {snap['tx_id']}",
            )
        else:
            console.print(f"[bold red]Command exited with error code {exit_code}[/bold red]")

    except Exception as e:
        console.print(f"[bold red]Execution error: {str(e)}[/bold red]")

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


def cmd_boss(args):
    """Lists C-DAC BOSS Linux specialized runbooks."""
    runbooks = BossLinuxEngine.list_runbooks()
    console.print(Panel.fit(
        "[bold cyan]C-DAC BOSS Linux (Bharat Operating System Solutions) Runbooks[/bold cyan]\n"
        "[dim]Native diagnostic routines for Pragya 10.0, Secure BOSS (MAC), & Meghdoot Cloud[/dim]",
        border_style="cyan",
    ))

    table = Table(title="Available BOSS Linux Diagnostic Profiles")
    table.add_column("Key", style="cyan")
    table.add_column("Distribution / Target", style="bold green")
    table.add_column("Description", style="white")

    for rb in runbooks:
        table.add_row(rb["id"], rb["distro"], rb["description"])
    console.print(table)


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

    # boss
    p_boss = subparsers.add_parser("boss", help="List C-DAC BOSS Linux diagnostic profiles")
    p_boss.set_defaults(func=cmd_boss)

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
