# 🛡️ TermiNex: AI-Powered Linux Operations Assistant

> **Problem Statement:** AI-Powered Linux Operations Assistant Using Natural Language Queries (C-DAC Hackathon)  
> *Diagnose system issues, search files and documents, and provide easy-to-understand solutions with safe, recommended Linux commands.*

---

## ⚡ Overview
**TermiNex** is an air-gapped, kernel-grounded, reversible Linux operations assistant. Unlike standard LLM terminal wrappers that simply guess bash commands, TermiNex answers **what happened, what will change, and how to undo it**:

1. **Flight Recorder**: 24-hour circular telemetry ring buffer (SQLite) for retroactive time-travel root cause analysis.
2. **Rehearsal Stage**: Ephemeral `bubblewrap` + `overlayfs` sandbox displaying color-coded visual file diffs (`terraform plan` for Linux) before touching the host.
3. **Atomic Undo Engine**: SHA-256 hash-chained snapshots enabling one-command instant rollback (`terminex undo <tx-id>`).
4. **Structural File Search & Secret Sanitizer**: AST-based outline compression (55% context reduction) with automatic credential redaction.
5. **Bharat Alignment**: Native runbooks for **C-DAC BOSS Linux 10 (Pragya)** / **Secure BOSS** and multilingual (Hindi/Marathi) natural language query intake.
6. **Model Context Protocol (MCP)**: Universal MCP server exposing diagnostics to Cursor, Claude Desktop, and modern IDEs.

---

## 📋 Full Architecture & Roadmap
See [implementation.md](implementation.md) for the complete blueprint, 5-minute judge demo script, and 48-hour build milestones.

---

## 👥 Authors
- **Adhiraj Jagtap** (<adhirajjagtap12@gmail.com>)
