"""Risk Scorer and Tier Classification Engine for TermiNex."""

from typing import Any, Dict, List, Set

READ_ONLY_BINARIES: Set[str] = {
    "ls", "cat", "grep", "egrep", "fgrep", "find", "head", "tail", "less", "more",
    "ps", "top", "htop", "df", "du", "free", "uptime", "uname", "whoami", "id",
    "ss", "netstat", "ip", "ifconfig", "ping", "traceroute", "curl", "wget",
    "journalctl", "dmesg", "lsof", "wc", "stat", "file", "tree", "awk", "sed",
    "which", "whereis", "env", "printenv", "diff", "cmp"
}

MUTATING_BINARIES: Set[str] = {
    "touch", "mkdir", "cp", "mv", "ln", "tee", "tar", "gzip", "gunzip", "zip",
    "unzip", "sed", "systemctl", "service", "apt", "apt-get", "dpkg", "yum", "dnf",
    "pacman", "pip", "npm", "git"
}

HIGH_RISK_BINARIES: Set[str] = {
    "rm", "rmdir", "chmod", "chown", "chgrp", "kill", "pkill", "killall",
    "iptables", "ufw", "nft", "systemctl", "reboot", "shutdown", "poweroff",
    "truncate"
}


class RiskScorer:
    """Classifies candidate shell commands into Tier 0, Tier 1, or Tier 2."""

    def score_command(self, cmd_str: str, ast_info: Dict[str, Any]) -> Dict[str, Any]:
        if not ast_info.get("valid", True) or ast_info.get("is_dangerous", False):
            return {
                "tier": 2,
                "tier_name": "TIER_2_CRITICAL_DANGER",
                "color": "red",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": True,
                "can_auto_execute": False,
                "reason": "; ".join(ast_info.get("reasons", ["AST flag dangerous"])),
            }

        commands = ast_info.get("commands", [])
        if not commands:
            commands = [cmd_str.strip().split()[0].split("/")[-1]] if cmd_str.strip() else []

        # Check for High Risk binaries / operations
        for cmd in commands:
            if cmd in HIGH_RISK_BINARIES:
                # Special cases: systemctl status is Tier 0
                if cmd == "systemctl" and ("status" in cmd_str or "is-active" in cmd_str or "list-units" in cmd_str):
                    continue
                return {
                    "tier": 2,
                    "tier_name": "TIER_2_HIGH_RISK",
                    "color": "red",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": True,
                    "can_auto_execute": False,
                    "reason": f"Command uses potentially destructive binary '{cmd}' or system state modification",
                }

        # Check for Redirections into files
        if ast_info.get("redirections"):
            return {
                "tier": 1,
                "tier_name": "TIER_1_MUTATING",
                "color": "yellow",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": False,
                "can_auto_execute": True,
                "reason": "Command writes to files via stream redirection",
            }

        # Check for Mutating binaries
        for cmd in commands:
            if cmd in MUTATING_BINARIES:
                # If systemctl start/restart/reload -> Tier 1
                return {
                    "tier": 1,
                    "tier_name": "TIER_1_MUTATING",
                    "color": "yellow",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": False,
                    "can_auto_execute": True,
                    "reason": f"Command performs state mutation via '{cmd}'",
                }

        # Check if all commands are Read-Only
        if all(cmd in READ_ONLY_BINARIES for cmd in commands):
            return {
                "tier": 0,
                "tier_name": "TIER_0_READ_ONLY",
                "color": "green",
                "requires_rehearsal": False,
                "requires_explicit_confirmation": False,
                "can_auto_execute": True,
                "reason": "Safe read-only inspection command",
            }

        # Default fallback to Tier 1
        return {
            "tier": 1,
            "tier_name": "TIER_1_MUTATING",
            "color": "yellow",
            "requires_rehearsal": True,
            "requires_explicit_confirmation": False,
            "can_auto_execute": True,
            "reason": "Command contains unclassified or multi-step operations",
        }
