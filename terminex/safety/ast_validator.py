"""AST Syntax Analyzer & Safety Validator using bashlex."""

import re
from typing import Any, Dict, List, Set
import bashlex


# High risk & blacklisted commands / patterns
DANGEROUS_BINARIES: Set[str] = {
    "mkfs", "fdisk", "parted", "dd", "format", "shred", "wipefs",
    "userdel", "groupdel", "killall5"
}

CRITICAL_SYSTEM_PATHS: Set[str] = {
    "/", "/bin", "/sbin", "/lib", "/lib64", "/usr", "/boot", "/sys", "/dev", "/proc"
}

EVAL_VECTORS: Set[str] = {"eval", "exec", "source"}


class ASTSecurityValidator:
    """Evaluates shell commands at the Abstract Syntax Tree level to isolate security risks."""

    def __init__(self):
        pass

    def validate_command(self, cmd_str: str) -> Dict[str, Any]:
        cmd_str = cmd_str.strip()
        if not cmd_str:
            return {"valid": False, "reason": "Empty command string", "risk_level": "UNKNOWN"}

        # 1. Regex check for obvious fork bombs & destructive pipes
        if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", cmd_str):
            return {
                "valid": False,
                "is_dangerous": True,
                "reason": "Fork bomb signature detected",
                "risk_level": "CRITICAL_BLOCKED",
                "tokens": [],
            }

        if re.search(r"curl.*\|\s*(ba)?sh", cmd_str) or re.search(r"wget.*\|\s*(ba)?sh", cmd_str):
            return {
                "valid": False,
                "is_dangerous": True,
                "reason": "Insecure remote pipe execution (curl|sh / wget|sh) blocked",
                "risk_level": "CRITICAL_BLOCKED",
                "tokens": [],
            }

        # 2. Parse into AST via bashlex
        try:
            nodes = bashlex.parse(cmd_str)
        except Exception as parse_err:
            # If bashlex fails (e.g. specialized flags), use token fallback
            return self._fallback_validation(cmd_str, str(parse_err))

        commands_found: List[str] = []
        subshells_found: List[str] = []
        redirections_found: List[str] = []
        is_dangerous = False
        danger_reasons: List[str] = []

        def visitor(node):
            nonlocal is_dangerous
            kind = getattr(node, "kind", "")

            # Check commands
            if kind == "command":
                parts = [getattr(p, "word", "") for p in getattr(node, "parts", []) if hasattr(p, "word")]
                if parts:
                    binary = parts[0].split("/")[-1]
                    commands_found.append(binary)
                    
                    if binary in DANGEROUS_BINARIES:
                        is_dangerous = True
                        danger_reasons.append(f"Direct invocation of destructive binary '{binary}'")

                    # Check for rm -rf / or rm -rf /*
                    if binary == "rm":
                        args = set(parts[1:])
                        has_recursive = any(a in args for a in ["-r", "-R", "-rf", "-fr", "-rfa", "-rfv"])
                        for a in args:
                            clean_a = a.rstrip("/*")
                            if has_recursive and (clean_a in CRITICAL_SYSTEM_PATHS or clean_a == ""):
                                is_dangerous = True
                                danger_reasons.append(f"Recursive deletion targeted at critical system root '{a}'")

                    # Check for chmod -R 777 /
                    if binary == "chmod":
                        args = list(parts[1:])
                        if "-R" in args or "-r" in args:
                            if any(target in CRITICAL_SYSTEM_PATHS for target in args):
                                is_dangerous = True
                                danger_reasons.append("Recursive permission change on root/system directory")

            # Check subshells and command substitution
            elif kind in ("commandsubstitution", "processsubstitution"):
                subshells_found.append(cmd_str[node.pos[0] : node.pos[1]])

            # Check redirections (e.g. > /etc/shadow or > /dev/sda)
            elif kind == "redirect":
                output = getattr(node, "output", None)
                if output and hasattr(output, "word"):
                    dest = output.word
                    redirections_found.append(dest)
                    if any(dest.startswith(p) for p in ["/dev/sd", "/dev/nvme", "/etc/shadow", "/etc/sudoers"]):
                        is_dangerous = True
                        danger_reasons.append(f"Dangerous write redirection to protected file/device '{dest}'")

        # Walk AST
        for node in nodes:
            self._walk_node(node, visitor)

        return {
            "valid": not is_dangerous,
            "is_dangerous": is_dangerous,
            "commands": commands_found,
            "subshells": subshells_found,
            "redirections": redirections_found,
            "reasons": danger_reasons if is_dangerous else ["AST validation passed"],
            "raw_command": cmd_str,
        }

    def _walk_node(self, node: Any, visitor: Any):
        visitor(node)
        for part in getattr(node, "parts", []):
            self._walk_node(part, visitor)
        for child in getattr(node, "list", []):
            self._walk_node(child, visitor)

    def _fallback_validation(self, cmd_str: str, error_msg: str) -> Dict[str, Any]:
        """Fallback heuristics for multi-line or unparseable shell constructs."""
        tokens = cmd_str.split()
        if not tokens:
            return {"valid": False, "reason": "Empty command", "is_dangerous": True}

        first_token = tokens[0].split("/")[-1]
        is_dangerous = first_token in DANGEROUS_BINARIES

        if "rm" in tokens and ("-rf" in tokens or "-fr" in tokens) and ("/" in tokens or "/*" in tokens):
            is_dangerous = True

        return {
            "valid": not is_dangerous,
            "is_dangerous": is_dangerous,
            "commands": [first_token],
            "subshells": [],
            "redirections": [],
            "reasons": [f"AST fallback validation: {error_msg}"] if not is_dangerous else ["Destructive command pattern detected in fallback check"],
            "raw_command": cmd_str,
        }
