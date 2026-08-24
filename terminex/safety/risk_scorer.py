"""Risk Scorer and Tier Classification Engine for TermiNex."""

import re
from typing import Any, Dict, List, Set

READ_ONLY_BINARIES: Set[str] = {
    "ls", "cat", "grep", "egrep", "fgrep", "find", "head", "tail", "less", "more",
    "ps", "top", "htop", "df", "du", "free", "uptime", "uname", "whoami", "id",
    "ss", "netstat", "ip", "ifconfig", "ping", "traceroute", "curl", "wget",
    "journalctl", "dmesg", "lsof", "wc", "stat", "file", "tree", "awk",
    "which", "whereis", "env", "printenv", "diff", "cmp"
}

MUTATING_BINARIES: Set[str] = {
    "touch", "mkdir", "cp", "mv", "ln", "tee", "tar", "gzip", "gunzip", "zip",
    "unzip", "service", "apt", "apt-get", "dpkg", "yum", "dnf",
    "pacman", "pip", "npm", "git", "truncate"
}

HIGH_RISK_BINARIES: Set[str] = {
    "rm", "rmdir", "chmod", "chown", "chgrp", "kill", "pkill", "killall",
    "iptables", "ufw", "nft", "reboot", "shutdown", "poweroff"
}

SYSTEMCTL_READ_ONLY: Set[str] = {
    "status", "is-active", "is-enabled", "is-failed", "show", "cat", "list-units", "list-unit-files"
}


class RiskScorer:
    """Classifies candidate shell commands into Tier 0, Tier 1, or Tier 2."""

    def score_command(self, cmd_str: str, ast_info: Dict[str, Any]) -> Dict[str, Any]:
        cmd_clean = cmd_str.strip()

        # 1. Critical AST rejection
        if not ast_info.get("valid", True) or ast_info.get("is_dangerous", False):
            return {
                "tier": 2,
                "tier_name": "TIER_2_CRITICAL_DANGER",
                "color": "red",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": True,
                "can_auto_execute": False,
                "reason": "; ".join(ast_info.get("reasons", ["AST flagged critical danger"])),
            }

        commands = ast_info.get("commands", [])
        if not commands:
            commands = [cmd_clean.split()[0].split("/")[-1]] if cmd_clean else []

        tokens = cmd_clean.split()

        # 2. Check find with -delete vs -exec <binary>
        if "find" in commands:
            if "-delete" in tokens:
                return {
                    "tier": 2,
                    "tier_name": "TIER_2_HIGH_RISK",
                    "color": "red",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": True,
                    "can_auto_execute": False,
                    "reason": "Command uses 'find -delete' which directly removes files",
                }
            if "-exec" in tokens or "-execdir" in tokens:
                # Extract binary invoked by -exec
                exec_idx = tokens.index("-exec") if "-exec" in tokens else tokens.index("-execdir")
                if exec_idx + 1 < len(tokens):
                    sub_bin = tokens[exec_idx + 1].split("/")[-1]
                    if sub_bin in READ_ONLY_BINARIES:
                        pass  # e.g. find ... -exec ls -lh {} + is safe read-only!
                    elif sub_bin in HIGH_RISK_BINARIES or sub_bin in ("sh", "bash"):
                        return {
                            "tier": 2,
                            "tier_name": "TIER_2_HIGH_RISK",
                            "color": "red",
                            "requires_rehearsal": True,
                            "requires_explicit_confirmation": True,
                            "can_auto_execute": False,
                            "reason": f"Command uses 'find -exec' with potentially destructive binary '{sub_bin}'",
                        }

        # 3. Check systemctl operations (even in compound commands like `sudo nginx -t && sudo systemctl status nginx`)
        if "systemctl" in commands:
            systemctl_actions: List[str] = []
            for i, t in enumerate(tokens):
                if t.endswith("systemctl") or t == "systemctl":
                    # Scan following tokens for non-flag action
                    for nxt in tokens[i + 1 : i + 4]:
                        if not nxt.startswith("-") and nxt not in ("sudo", "doas", "pkexec", "&&", "||", ";"):
                            systemctl_actions.append(nxt)
                            break

            is_all_read = bool(systemctl_actions) and all(act in SYSTEMCTL_READ_ONLY for act in systemctl_actions)
            if is_all_read:
                # Verify other commands in pipeline/compound are also read-only or nominal syntax tests
                other_cmds = [c for c in commands if c != "systemctl"]
                if all(c in READ_ONLY_BINARIES or c == "nginx" for c in other_cmds):
                    return {
                        "tier": 0,
                        "tier_name": "TIER_0_READ_ONLY",
                        "color": "green",
                        "requires_rehearsal": False,
                        "requires_explicit_confirmation": False,
                        "can_auto_execute": True,
                        "reason": f"Read-only systemctl inspection action '{', '.join(systemctl_actions)}'",
                    }

            return {
                "tier": 1,
                "tier_name": "TIER_1_MUTATING",
                "color": "yellow",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": False,
                "can_auto_execute": True,
                "reason": "Command modifies system service lifecycle state",
            }

        # 4. Check High-Risk binaries
        for cmd in commands:
            if cmd in HIGH_RISK_BINARIES:
                return {
                    "tier": 2,
                    "tier_name": "TIER_2_HIGH_RISK",
                    "color": "red",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": True,
                    "can_auto_execute": False,
                    "reason": f"Command uses potentially destructive binary '{cmd}'",
                }

        # 5. Check curl / wget file writes
        if "curl" in commands and ("-o" in tokens or "-O" in tokens or "--output" in tokens):
            dest_etc = any(t.startswith("/etc") for t in tokens)
            return {
                "tier": 2 if dest_etc else 1,
                "tier_name": "TIER_2_HIGH_RISK" if dest_etc else "TIER_1_MUTATING",
                "color": "red" if dest_etc else "yellow",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": dest_etc,
                "can_auto_execute": not dest_etc,
                "reason": "curl downloading and saving output file to local filesystem",
            }

        if "wget" in commands and ("-O" in tokens or "-P" in tokens or any(t.startswith("http") for t in tokens)):
            return {
                "tier": 1,
                "tier_name": "TIER_1_MUTATING",
                "color": "yellow",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": False,
                "can_auto_execute": True,
                "reason": "wget downloading file to local filesystem",
            }

        # 6. Check sed with in-place flag (-i)
        if "sed" in commands:
            if "-i" in tokens or any(t.startswith("-i") for t in tokens):
                return {
                    "tier": 1,
                    "tier_name": "TIER_1_MUTATING",
                    "color": "yellow",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": False,
                    "can_auto_execute": True,
                    "reason": "sed performing in-place file mutation (-i)",
                }
            return {
                "tier": 0,
                "tier_name": "TIER_0_READ_ONLY",
                "color": "green",
                "requires_rehearsal": False,
                "requires_explicit_confirmation": False,
                "can_auto_execute": True,
                "reason": "sed stream inspection without in-place modification",
            }

        # 7. Check file stream redirections
        if ast_info.get("redirections"):
            dest_is_root = any(r.startswith("/etc") or r.startswith("/usr") for r in ast_info["redirections"])
            return {
                "tier": 2 if dest_is_root else 1,
                "tier_name": "TIER_2_HIGH_RISK" if dest_is_root else "TIER_1_MUTATING",
                "color": "red" if dest_is_root else "yellow",
                "requires_rehearsal": True,
                "requires_explicit_confirmation": dest_is_root,
                "can_auto_execute": not dest_is_root,
                "reason": "Command writes to files via stream redirection",
            }

        # 8. Check Mutating binaries
        for cmd in commands:
            if cmd in MUTATING_BINARIES:
                return {
                    "tier": 1,
                    "tier_name": "TIER_1_MUTATING",
                    "color": "yellow",
                    "requires_rehearsal": True,
                    "requires_explicit_confirmation": False,
                    "can_auto_execute": True,
                    "reason": f"Command performs state mutation via '{cmd}'",
                }

        # 9. Check if all commands are Read-Only
        if all(cmd in READ_ONLY_BINARIES or cmd in ("nginx", "true", "echo") for cmd in commands):
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
            "reason": "Command contains multi-step operations",
        }
