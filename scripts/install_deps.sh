#!/usr/bin/env bash
# ==============================================================================
# TermiNex Dependency & Environment Installer for Linux / C-DAC BOSS Linux 10
# ==============================================================================

set -e

echo "[+] Installing TermiNex system dependencies and Python runtime..."

if [ -f /etc/debian_version ] || [ -f /etc/boss_version ]; then
    echo "[*] Detected Debian / BOSS Linux / Ubuntu environment..."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv bubblewrap ripgrep fd-find
elif [ -f /etc/redhat-release ]; then
    echo "[*] Detected RHEL / CentOS / Fedora environment..."
    sudo dnf install -y python3 python3-pip bubblewrap ripgrep fd-find
fi

# Ensure Python Virtual Environment to comply with PEP 668
if [ -z "$VIRTUAL_ENV" ]; then
    echo "[*] Setting up TermiNex virtual environment (.venv)..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "[*] Virtual environment activated: $VIRTUAL_ENV"
fi

echo "[*] Installing Python package requirements..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo "[SUCCESS] TermiNex installation complete. Run 'terminex --help' or 'terminex selftest' to get started."
