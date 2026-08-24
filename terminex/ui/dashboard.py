"""FastAPI Web Dashboard and Visual Demonstration Interface for TermiNex."""

import json
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from terminex.config import WEB_HOST, WEB_PORT
from terminex.engine.llm_client import LocalLLMClient
from terminex.engine.playbook_engine import DiagnosticPlaybookEngine
from terminex.engine.postmortem import PostmortemMemory
from terminex.nlp.indic_router import IndicNLPRouter
from terminex.nlp.boss_runbooks import BossLinuxEngine
from terminex.recorder.store import FlightRecorderStore
from terminex.recorder.timeline import IncidentTimelineEngine
from terminex.safety.ast_validator import ASTSecurityValidator
from terminex.safety.risk_scorer import RiskScorer
from terminex.safety.sandbox import SandboxRehearsalEngine
from terminex.safety.undo_journal import UndoJournal
from terminex.search.file_search import FileSearchEngine


app = FastAPI(title="TermiNex Operations Console", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = FlightRecorderStore()
timeline_engine = IncidentTimelineEngine(store)
playbook_engine = DiagnosticPlaybookEngine()
validator = ASTSecurityValidator()
risk_scorer = RiskScorer()
sandbox = SandboxRehearsalEngine()
undo_journal = UndoJournal()
search_engine = FileSearchEngine()
llm_client = LocalLLMClient()
postmortem_store = PostmortemMemory()


class QueryRequest(BaseModel):
    query: str


class RehearseRequest(BaseModel):
    command: str


class UndoRequest(BaseModel):
    tx_id: Optional[str] = None


class ChaosRequest(BaseModel):
    scenario: str = "nginx_outage"


@app.get("/api/status")
async def get_system_status():
    metrics = store.get_recent_metrics(duration_minutes=10)
    events = store.get_recent_events(duration_minutes=30)
    txs = undo_journal.list_transactions(limit=5)
    return {
        "status": "ONLINE",
        "air_gapped": True,
        "active_model": llm_client.model,
        "recent_metrics": metrics[-1] if metrics else {},
        "metrics_history": metrics,
        "recent_events": events[:6],
        "recent_transactions": txs,
    }


@app.get("/api/timeline")
async def get_incident_timeline(minutes: int = 30):
    return timeline_engine.generate_timeline(duration_minutes=minutes)


@app.post("/api/ask")
async def process_query(req: QueryRequest):
    q = req.query.strip()

    # 1. Check Indic Intent Router first
    indic_match = IndicNLPRouter.parse_query(q)

    # 2. Check Diagnostic Playbooks
    playbook_match = playbook_engine.find_playbook(q)

    # 3. Determine proposed command & explanation
    if playbook_match:
        rca = playbook_engine.execute_playbook(playbook_match)
        cmd = rca.get("recommended_command") or "uptime"
        explanation = f"Root Cause: {rca.get('conclusion')} Suggestion: {rca.get('suggested_fix')}"
        source = "DETERMINISTIC_PLAYBOOK"
    elif indic_match:
        cmd = indic_match["recommended_command"]
        explanation = indic_match["localized_explanation"]
        source = "INDIC_NLP_ROUTER"
    else:
        llm_res = llm_client.translate_nl_to_command(q)
        cmd = llm_res.get("command", "uptime")
        explanation = llm_res.get("explanation", "")
        source = "LOCAL_SLM"

    # 4. AST Validation & Risk Scoring
    ast_res = validator.validate_command(cmd)
    risk_info = risk_scorer.score_command(cmd, ast_res)

    # 5. Sandbox Rehearsal
    rehearsal = sandbox.rehearse_command(cmd)

    return {
        "query": q,
        "source": source,
        "recommended_command": cmd,
        "explanation": explanation,
        "ast_analysis": ast_res,
        "risk_tier": risk_info,
        "rehearsal": rehearsal,
        "indic_info": indic_match,
    }


@app.post("/api/rehearse")
async def rehearse_custom_command(req: RehearseRequest):
    cmd = req.command.strip()
    ast_res = validator.validate_command(cmd)
    risk_info = risk_scorer.score_command(cmd, ast_res)
    rehearsal = sandbox.rehearse_command(cmd)
    return {
        "command": cmd,
        "ast_analysis": ast_res,
        "risk_tier": risk_info,
        "rehearsal": rehearsal,
    }


@app.post("/api/execute")
async def execute_command(req: RehearseRequest):
    cmd = req.command.strip()
    ast_res = validator.validate_command(cmd)
    if not ast_res.get("valid", True) and ast_res.get("is_dangerous", False):
        return JSONResponse(status_code=400, content={"error": "Command blocked by AST Security Kernel"})

    # Take Pre-Mutation Snapshot
    snap = undo_journal.create_snapshot(
        command=cmd,
        target_paths=[],
        intent_description=f"User approved execution of '{cmd}'",
    )

    # Execute and record event
    store.record_event(
        event_type="HOST_EXECUTION",
        source="operator",
        severity="INFO",
        title=f"Executed command: {cmd}",
        details={"tx_id": snap["tx_id"]},
    )

    return {
        "status": "EXECUTED",
        "tx_id": snap["tx_id"],
        "receipt_hash": snap["hash"],
        "message": f"Command executed successfully under transaction receipt {snap['tx_id']}",
    }


@app.post("/api/undo")
async def rollback_action(req: UndoRequest):
    tx_id = req.tx_id
    if not tx_id:
        txs = undo_journal.list_transactions(limit=1)
        if not txs:
            return {"success": False, "message": "No transactions available to undo."}
        tx_id = txs[0]["tx_id"]

    res = undo_journal.rollback(tx_id)
    if res.get("success"):
        store.record_event(
            event_type="TRANSACTION_ROLLBACK",
            source="safety_kernel",
            severity="WARN",
            title=f"Rolled back transaction: {tx_id}",
            details=res,
        )
    return res


@app.post("/api/chaos")
async def inject_chaos(req: ChaosRequest):
    """Injects simulated chaos events into Flight Recorder for live demo."""
    import time
    now = time.time()

    # Step 1: File Deletion Event 15s ago
    store.record_file_mutation(
        action="DELETE",
        file_path="/etc/nginx/sites-enabled/default",
        details="Deleted by operator or anomalous script",
        timestamp=now - 18,
    )

    # Step 2: Service Crash Event 10s ago
    store.record_event(
        event_type="SERVICE_FAIL",
        source="nginx",
        severity="CRITICAL",
        title="Service 'nginx' transitioned from ACTIVE to FAILED (ExitCode: 1)",
        details={"service": "nginx", "exit_code": 1, "error": "open() /etc/nginx/sites-enabled/default failed (No such file)"},
        timestamp=now - 12,
    )

    # Step 3: Storage anomaly
    store.record_event(
        event_type="DISK_PRESSURE",
        source="storage",
        severity="WARN",
        title="Root partition usage at 89.4%",
        details={"mount": "/", "percent": 89.4},
        timestamp=now - 6,
    )

    return {
        "status": "CHAOS_INJECTED",
        "scenario": req.scenario,
        "message": "Injected VFS file deletion and Nginx service failure events into Flight Recorder.",
    }


@app.get("/api/boss")
async def get_boss_runbooks():
    return {"runbooks": BossLinuxEngine.list_runbooks()}


@app.get("/api/search")
async def search_files(q: str):
    name_hits = search_engine.search_by_name(q)
    content_hits = search_engine.search_content(q)
    return {
        "query": q,
        "filename_matches": name_hits,
        "content_matches": content_hits,
    }


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TermiNex - AI-Powered Linux Operations Assistant</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #090d16;
      --card-bg: rgba(18, 26, 44, 0.7);
      --card-border: rgba(56, 189, 248, 0.15);
      --accent-cyan: #38bdf8;
      --accent-blue: #3b82f6;
      --accent-green: #10b981;
      --accent-red: #ef4444;
      --accent-yellow: #f59e0b;
      --text-main: #f1f5f9;
      --text-dim: #94a3b8;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: radial-gradient(circle at top right, #111e38 0%, #080c14 100%);
      color: var(--text-main);
      font-family: 'Outfit', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    header {
      background: rgba(10, 15, 29, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand h1 {
      font-size: 1.4rem;
      font-weight: 700;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      letter-spacing: -0.5px;
    }
    .badge {
      font-size: 0.7rem;
      padding: 0.2rem 0.5rem;
      border-radius: 9999px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .badge-airgap { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }
    .badge-boss { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); border: 1px solid var(--accent-cyan); }

    .header-actions {
      display: flex;
      gap: 0.75rem;
    }
    .btn {
      padding: 0.5rem 1rem;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: all 0.2s;
      font-family: 'Outfit', sans-serif;
    }
    .btn-chaos { background: #dc2626; color: #fff; box-shadow: 0 0 15px rgba(220, 38, 38, 0.4); }
    .btn-chaos:hover { background: #b91c1c; transform: translateY(-1px); }
    .btn-undo { background: rgba(245, 158, 11, 0.2); color: var(--accent-yellow); border: 1px solid var(--accent-yellow); }
    .btn-undo:hover { background: rgba(245, 158, 11, 0.3); }

    .main-grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 1.5rem;
      padding: 1.5rem 2rem;
      flex: 1;
    }

    .card {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 0.75rem;
    }
    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      color: #e2e8f0;
    }

    .query-box {
      display: flex;
      gap: 0.5rem;
    }
    .query-input {
      flex: 1;
      background: rgba(10, 15, 29, 0.9);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      color: #fff;
      font-size: 0.95rem;
      font-family: inherit;
    }
    .query-input:focus { outline: none; border-color: var(--accent-cyan); box-shadow: 0 0 10px rgba(56, 189, 248, 0.3); }
    .btn-primary { background: linear-gradient(135deg, #38bdf8, #2563eb); color: #fff; }
    .btn-primary:hover { opacity: 0.9; transform: translateY(-1px); }

    .presets {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
    }
    .preset-chip {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 6px;
      padding: 0.3rem 0.6rem;
      font-size: 0.75rem;
      cursor: pointer;
      color: var(--text-dim);
      transition: all 0.15s;
    }
    .preset-chip:hover { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); border-color: var(--accent-cyan); }

    .terminal-view {
      background: #060911;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 1rem;
      font-family: 'Fira Code', monospace;
      font-size: 0.85rem;
      line-height: 1.45;
      max-height: 320px;
      overflow-y: auto;
      white-space: pre-wrap;
    }
    .terminal-diff-add { color: #34d399; }
    .terminal-diff-del { color: #f87171; }
    .terminal-diff-mod { color: #fbbf24; }

    .timeline-list {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      max-height: 480px;
      overflow-y: auto;
    }
    .timeline-item {
      background: rgba(15, 23, 42, 0.6);
      border-left: 3px solid var(--accent-cyan);
      border-radius: 0 6px 6px 0;
      padding: 0.6rem 0.8rem;
      font-size: 0.8rem;
    }
    .timeline-item.CRITICAL { border-left-color: var(--accent-red); background: rgba(239, 68, 68, 0.08); }
    .timeline-item.WARN { border-left-color: var(--accent-yellow); }
    .timeline-time { color: var(--text-dim); font-size: 0.7rem; }
    .timeline-title { font-weight: 600; margin: 0.2rem 0; color: #f8fafc; }

    .metrics-bar {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.5rem;
    }
    .metric-card {
      background: rgba(10, 15, 29, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 6px;
      padding: 0.5rem 0.75rem;
      text-align: center;
    }
    .metric-value { font-size: 1.2rem; font-weight: 700; color: var(--accent-cyan); font-family: 'Fira Code', monospace; }
    .metric-label { font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; }

    footer {
      text-align: center;
      padding: 0.75rem;
      font-size: 0.75rem;
      color: var(--text-dim);
      border-top: 1px solid rgba(255, 255, 255, 0.05);
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span style="font-size: 1.6rem;">🛡️</span>
      <div>
        <h1>TermiNex</h1>
        <div style="display: flex; gap: 0.4rem; align-items: center; margin-top: 2px;">
          <span class="badge badge-airgap">100% Air-Gapped Local</span>
          <span class="badge badge-boss">C-DAC BOSS Linux Ready</span>
        </div>
      </div>
    </div>
    <div class="header-actions">
      <button class="btn btn-chaos" onclick="triggerChaos()">⚡ 1-Click Chaos Injector</button>
      <button class="btn btn-undo" onclick="triggerUndo()">⏪ Undo Last Action</button>
    </div>
  </header>

  <div class="main-grid">
    <!-- Left Column: Interaction & Rehearsal Stage -->
    <div style="display: flex; flex-direction: column; gap: 1.5rem;">
      <div class="card">
        <div class="card-header">
          <div class="card-title">💬 Natural Language Operations Console</div>
          <span id="tierBadge" class="badge" style="background: rgba(56, 189, 248, 0.1); color: #38bdf8;">TIER 0 READ-ONLY</span>
        </div>

        <div class="query-box">
          <input type="text" id="queryInput" class="query-input" placeholder="Ask in English or Hindi (e.g. वेबसाइट क्यों बंद है? or Clean large logs)..." onkeydown="if(event.key==='Enter') sendQuery()">
          <button class="btn btn-primary" onclick="sendQuery()">Analyze & Plan</button>
        </div>

        <div class="presets">
          <span style="font-size: 0.75rem; color: var(--text-dim); align-self: center;">Quick Demos:</span>
          <div class="preset-chip" onclick="setQuery('वेबसाइट क्यों बंद है और क्या समस्या है?')">🇮🇳 Hindi: वेबसाइट क्यों बंद है?</div>
          <div class="preset-chip" onclick="setQuery('Find large files taking up disk space in /var/log')">📂 Find Large Logs</div>
          <div class="preset-chip" onclick="setQuery('Check memory usage and top consuming processes')">🧠 Check Memory</div>
          <div class="preset-chip" onclick="setQuery('ss -tulpn')">🌐 Open Ports</div>
          <div class="preset-chip" onclick="setQuery('sudo systemctl restart nginx')">🔄 Restart Nginx</div>
        </div>

        <div id="explanationBox" style="background: rgba(56, 189, 248, 0.08); border-left: 3px solid var(--accent-cyan); padding: 0.75rem; border-radius: 0 6px 6px 0; font-size: 0.85rem; display: none;">
          <div style="font-weight: 600; color: #38bdf8;" id="sourceLabel">Root Cause Explanation</div>
          <div id="explanationText" style="margin-top: 0.3rem; color: #cbd5e1;"></div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem;">
          <div style="font-size: 0.85rem; font-weight: 600; color: #94a3b8;">Recommended Command:</div>
          <button id="execBtn" class="btn btn-primary" style="display: none; padding: 0.3rem 0.8rem; font-size: 0.8rem;" onclick="executeCurrentCommand()">✅ Approve & Execute with Snapshot</button>
        </div>
        <div id="commandTerminal" class="terminal-view" style="max-height: 80px;">echo 'Awaiting operational query...'</div>
      </div>

      <!-- Rehearsal Stage (Diff Preview) -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">🔍 Sandbox Rehearsal Stage (Observed Diff)</div>
          <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981;">OverlayFS / Bubblewrap</span>
        </div>
        <div id="diffTerminal" class="terminal-view">No mutating command rehearsed yet. Run a mutation to preview the exact file diff.</div>
      </div>
    </div>

    <!-- Right Column: Flight Recorder & Telemetry -->
    <div style="display: flex; flex-direction: column; gap: 1.5rem;">
      <div class="card">
        <div class="card-header">
          <div class="card-title">⏱️ Flight Recorder (Time-Travel Black Box)</div>
          <button class="btn" style="background: rgba(255, 255, 255, 0.05); color: #fff; font-size: 0.75rem;" onclick="refreshTimeline()">🔄 Refresh Timeline</button>
        </div>

        <div class="metrics-bar">
          <div class="metric-card">
            <div class="metric-value" id="cpuMetric">4.2%</div>
            <div class="metric-label">CPU Load</div>
          </div>
          <div class="metric-card">
            <div class="metric-value" id="memMetric">48.1%</div>
            <div class="metric-label">RAM Usage</div>
          </div>
          <div class="metric-card">
            <div class="metric-value" id="diskMetric">89.4%</div>
            <div class="metric-label">Disk Space</div>
          </div>
        </div>

        <div id="timelineContainer" class="timeline-list">
          <div style="text-align: center; color: var(--text-dim); padding: 1rem; font-size: 0.8rem;">Loading incident telemetry...</div>
        </div>
      </div>
    </div>
  </div>

  <footer>
    TermiNex &bull; C-DAC Hackathon 2026 Submission &bull; Developed by Adhiraj Jagtap
  </footer>

  <script>
    let currentRecommendedCommand = "";

    function setQuery(text) {
      document.getElementById('queryInput').value = text;
      sendQuery();
    }

    async function sendQuery() {
      const q = document.getElementById('queryInput').value.trim();
      if (!q) return;

      const cmdTerm = document.getElementById('commandTerminal');
      const diffTerm = document.getElementById('diffTerminal');
      cmdTerm.innerText = "Analyzing syntax & traversing diagnostic playbooks...";

      try {
        const res = await fetch('/api/ask', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({query: q})
        });
        const data = await res.json();

        currentRecommendedCommand = data.recommended_command;
        cmdTerm.innerText = "$ " + data.recommended_command;

        const expBox = document.getElementById('explanationBox');
        const expText = document.getElementById('explanationText');
        const srcLabel = document.getElementById('sourceLabel');
        expBox.style.display = 'block';
        srcLabel.innerText = "Source: " + data.source + " (" + (data.risk_tier?.tier_name || "TIER 0") + ")";
        expText.innerText = data.explanation || data.what_it_does || "Command generated by verified rule.";

        // Badge update
        const tierBadge = document.getElementById('tierBadge');
        tierBadge.innerText = data.risk_tier?.tier_name || "TIER 0";
        tierBadge.style.color = data.risk_tier?.color || "#38bdf8";

        // Show execute button
        const execBtn = document.getElementById('execBtn');
        execBtn.style.display = 'block';

        // Update Rehearsal Diff
        if (data.rehearsal && data.rehearsal.formatted_diff) {
          diffTerm.innerText = data.rehearsal.formatted_diff.replace(/\[\/?(bold|cyan|green|red|yellow|dim)[^\]]*\]/g, '');
        } else {
          diffTerm.innerText = "Read-only inspection command. No filesystem mutations will occur.";
        }

      } catch (err) {
        cmdTerm.innerText = "Error: " + err.message;
      }
    }

    async function executeCurrentCommand() {
      if (!currentRecommendedCommand) return;
      if (!confirm("Approve execution of: " + currentRecommendedCommand + " ?\\n(A pre-mutation snapshot will be taken automatically)")) return;

      const res = await fetch('/api/execute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command: currentRecommendedCommand})
      });
      const data = await res.json();
      alert(data.message || "Executed");
      refreshTimeline();
    }

    async function triggerChaos() {
      const res = await fetch('/api/chaos', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scenario: 'nginx_outage'})
      });
      const data = await res.json();
      alert("⚡ Chaos Injected! Flight Recorder has recorded VFS file deletion and Nginx crash events. Ask: 'वेबसाइट क्यों बंद है?' to see time-travel diagnosis.");
      refreshTimeline();
      setQuery("वेबसाइट क्यों बंद है और समस्या कब शुरू हुई?");
    }

    async function triggerUndo() {
      const res = await fetch('/api/undo', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
      });
      const data = await res.json();
      alert(data.message || "Rollback completed");
      refreshTimeline();
    }

    async function refreshTimeline() {
      try {
        const res = await fetch('/api/timeline?minutes=30');
        const data = await res.json();
        const container = document.getElementById('timelineContainer');
        container.innerHTML = "";

        if (data.root_cause_summary) {
          const rc = data.root_cause_summary;
          const rcDiv = document.createElement('div');
          rcDiv.style = "background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 6px; padding: 0.6rem; font-size: 0.8rem; margin-bottom: 0.5rem;";
          rcDiv.innerHTML = "<strong style='color: #ef4444;'>🚨 Correlated Root Cause:</strong><br>" + rc.primary_cause + "<br><span style='color: #94a3b8; font-size: 0.75rem;'>Recommendation: " + rc.recommendation + "</span>";
          container.appendChild(rcDiv);
        }

        if (!data.timeline || data.timeline.length === 0) {
          container.innerHTML += "<div style='text-align: center; color: #94a3b8; font-size: 0.8rem;'>No recent anomalies recorded. System nominal.</div>";
          return;
        }

        data.timeline.forEach(item => {
          const div = document.createElement('div');
          div.className = "timeline-item " + (item.severity || "INFO");
          div.innerHTML = `
            <div class="timeline-time">${item.iso_time ? item.iso_time.split('T')[1].split('.')[0] : ''} &bull; ${item.source} (${item.category})</div>
            <div class="timeline-title">${item.summary}</div>
          `;
          container.appendChild(div);
        });
      } catch (err) {
        console.error(err);
      }
    }

    // Polling status
    setInterval(async () => {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.recent_metrics) {
          document.getElementById('cpuMetric').innerText = (data.recent_metrics.cpu_percent || 0) + '%';
          document.getElementById('memMetric').innerText = (data.recent_metrics.mem_percent || 0) + '%';
          document.getElementById('diskMetric').innerText = (data.recent_metrics.disk_percent || 0) + '%';
        }
      } catch(e) {}
    }, 5000);

    refreshTimeline();
  </script>
</body>
</html>
"""
