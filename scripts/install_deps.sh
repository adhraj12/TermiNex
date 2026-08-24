#!/usr/bin/env bash
# ==============================================================================
# TermiNex Dependency & Environment Installer for Linux / C-DAC BOSS Linux 10
# ==============================================================================

set -e

echo "🛡️ Installing TermiNex system dependencies and Python runtime..."

if [ -f /etc/debian_version ] || [ -f /etc/boss_version ]; then
    echo "📦 Detected Debian / BOSS Linux / Ubuntu environment..."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv bubblewrap ripgrep fd-find
elif [ -f /etc/redhat-release ]; then
    echo "📦 Detected RHEL / CentOS / Fedora environment..."
    sudo dnf install -y python3 python3-pip bubblewrap ripgrep fd-find
fi

# Install Python package dependencies
echo "🐍 Installing Python package requirements..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -e .

echo "✅ TermiNex installation complete. Run 'terminex --help' or 'python3 -m terminex.cli demo' to get started."
