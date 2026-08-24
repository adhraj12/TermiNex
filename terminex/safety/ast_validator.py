"""AST Syntax Analyzer & Safety Validator using bashlex."""

import re
from typing import Any, Dict, List, Set, Tuple
import bashlex


# Privilege escalation and wrapper binaries
PRIVILEGE_WRAPPERS: Set[str] = {"sudo", "doas", "pkexec", "su", "env", "nohup", "nice", "xargs"}
SHELL_WRAPPERS: Set[str] = {"sh", "bash", "dash", "zsh", "ksh", "csh", "tcsh"}

# High risk & blacklisted commands / patterns
DANGEROUS_BINARIES: Set[str] = {
    "mkfs", "fdisk", "parted", "dd", "format", "shred", "wipefs",
    "userdel", "groupdel", "killall5", "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs"
}

CRITICAL_SYSTEM_PATHS: Set[str] = {
    "/", "/bin", "/sbin", "/lib", "/lib64", "/usr", "/boot", "/sys", "/dev", "/proc", "/etc"
}


class ASTSecurityValidator:
    """Evaluates shell commands at the Abstract Syntax Tree level to isolate security risks."""

    def __init__(self):
        pass

    def validate_command(self, cmd_str: str, depth: int = 0) -> Dict[str, Any]:
        cmd_str = cmd_str.strip()
        if not cmd_str:
            return {"valid": False, "reason": "Empty command string", "risk_level": "UNKNOWN", "is_dangerous": False}

        # Prevent runaway recursion on nested shells
        if depth > 5:
            return {"valid": False, "is_dangerous": True, "reasons": ["Excessive subshell recursion depth"], "raw_command": cmd_str}

        # 1. Regex check for obvious fork bombs & destructive pipes
        if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", cmd_str):
            return {
                "valid": False,
                "is_dangerous": True,
                "commands": [":(){ :|:& };:"],
                "subshells": [],
                "redirections": [],
                "reasons": ["Fork bomb signature detected"],
                "risk_level": "CRITICAL_BLOCKED",
                "raw_command": cmd_str,
            }

        if re.search(r"curl.*\|\s*(ba)?sh", cmd_str) or re.search(r"wget.*\|\s*(ba)?sh", cmd_str):
            return {
                "valid": False,
                "is_dangerous": True,
                "commands": ["curl|sh"],
                "subshells": [],
                "redirections": [],
                "reasons": ["Insecure remote pipe execution (curl|sh / wget|sh) blocked"],
                "risk_level": "CRITICAL_BLOCKED",
                "raw_command": cmd_str,
            }

        # 2. Parse into AST via bashlex
        try:
            nodes = bashlex.parse(cmd_str)
        except Exception as parse_err:
            return self._fallback_validation(cmd_str, str(parse_err))

        commands_found: List[str] = []
        unwrapped_commands: List[str] = []
        subshells_found: List[str] = []
        redirections_found: List[str] = []
        is_dangerous = False
        danger_reasons: List[str] = []

        def visitor(node):
            nonlocal is_dangerous
            kind = getattr(node, "kind", "")

            if kind == "command":
                parts = [getattr(p, "word", "") for p in getattr(node, "parts", []) if hasattr(p, "word")]
                if parts:
                    raw_binary = parts[0].split("/")[-1]
                    commands_found.append(raw_binary)

                    # Unwrap privilege escalators (e.g. sudo rm -rf / -> binary = rm)
                    effective_binary, effective_args = self._unwrap_command(parts)
                    unwrapped_commands.append(effective_binary)

                    # Check shell -c encapsulation (e.g. sudo sh -c "rm -rf /")
                    if effective_binary in SHELL_WRAPPERS:
                        for i, arg in enumerate(effective_args):
                            if arg == "-c" and i + 1 < len(effective_args):
                                inner_payload = effective_args[i + 1]
                                subshells_found.append(inner_payload)
                                inner_res = self.validate_command(inner_payload, depth=depth + 1)
                                if inner_res.get("is_dangerous", False):
                                    is_dangerous = True
                                    danger_reasons.extend(inner_res.get("reasons", ["Dangerous command in shell -c wrapper"]))

                    # 1. Check dangerous binaries
                    if effective_binary in DANGEROUS_BINARIES or any(b in DANGEROUS_BINARIES for b in parts):
                        is_dangerous = True
                        danger_reasons.append(f"Direct invocation of destructive binary '{effective_binary}'")

                    # 2. Check for rm -rf / or rm -rf /* or rm on system root
                    if effective_binary == "rm":
                        args_set = set(effective_args)
                        has_recursive = any(
                            a in args_set for a in ["-r", "-R", "-rf", "-fr", "-rfa", "-rfv", "-f", "-frv"]
                        )
                        for a in effective_args:
                            if a.startswith("-"):
                                continue
                            clean_a = a.rstrip("/*")
                            if (has_recursive or "-f" in args_set) and (clean_a in CRITICAL_SYSTEM_PATHS or clean_a == ""):
                                is_dangerous = True
                                danger_reasons.append(f"Recursive or forced deletion targeted at critical system root '{a}'")

                    # 3. Check for chmod -R 777 /
                    if effective_binary == "chmod":
                        if any(a in ["-R", "-r"] for a in effective_args):
                            if any(target in CRITICAL_SYSTEM_PATHS for target in effective_args):
                                is_dangerous = True
                                danger_reasons.append("Recursive permission change on root/system directory")

                    # 4. Check find -delete targeted at root
                    if effective_binary == "find":
                        if "-delete" in effective_args:
                            if any(target in CRITICAL_SYSTEM_PATHS for target in effective_args if not target.startswith("-")):
                                is_dangerous = True
                                danger_reasons.append("High-risk 'find -delete' targeted at root system path")

            # Check subshells and command substitution
            elif kind in ("commandsubstitution", "processsubstitution"):
                sub_str = cmd_str[node.pos[0] : node.pos[1]]
                subshells_found.append(sub_str)
                # Strip $(...) or `...`
                inner = sub_str.strip("$()`")
                if inner:
                    sub_res = self.validate_command(inner, depth=depth + 1)
                    if sub_res.get("is_dangerous", False):
                        is_dangerous = True
                        danger_reasons.extend(sub_res.get("reasons", ["Dangerous subshell substitution"]))

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
            "commands": unwrapped_commands or commands_found,
            "raw_commands": commands_found,
            "subshells": subshells_found,
            "redirections": redirections_found,
            "reasons": danger_reasons if is_dangerous else ["AST validation passed"],
            "raw_command": cmd_str,
        }

    def _unwrap_command(self, parts: List[str]) -> Tuple[str, List[str]]:
        """Unwraps sudo, doas, pkexec, env var prefixes to find real underlying binary & args."""
        idx = 0
        while idx < len(parts):
            p = parts[idx]
            # Skip environment assignments (e.g. FOO=1)
            if "=" in p and not p.startswith("-"):
                idx += 1
                continue
            binary = p.split("/")[-1]
            if binary in PRIVILEGE_WRAPPERS:
                idx += 1
                # Skip flags passed to sudo (e.g. sudo -u root rm)
                while idx < len(parts) and parts[idx].startswith("-"):
                    if parts[idx] in ("-u", "-g", "-C", "-D") and idx + 1 < len(parts):
                        idx += 2
                    else:
                        idx += 1
                continue
            # Found actual binary
            return binary, parts[idx + 1 :]
        return parts[0].split("/")[-1] if parts else "", parts[1:] if len(parts) > 1 else []

    def _walk_node(self, node: Any, visitor: Any):
        visitor(node)
        for part in getattr(node, "parts", []):
            self._walk_node(part, visitor)
        for child in getattr(node, "list", []):
            self._walk_node(child, visitor)

    def _fallback_validation(self, cmd_str: str, error_msg: str) -> Dict[str, Any]:
        """Fallback heuristics for multi-line or specialized shell constructs."""
        tokens = cmd_str.split()
        if not tokens:
            return {"valid": False, "reason": "Empty command", "is_dangerous": True}

        effective_binary, effective_args = self._unwrap_command(tokens)
        is_dangerous = effective_binary in DANGEROUS_BINARIES

        if effective_binary == "rm" and any(a in ["-rf", "-fr", "-r", "-R"] for a in effective_args):
            if any(target in CRITICAL_SYSTEM_PATHS for target in effective_args if not target.startswith("-")):
                is_dangerous = True

        # Check sh -c in fallback
        if effective_binary in SHELL_WRAPPERS and "-c" in effective_args:
            idx = effective_args.index("-c")
            if idx + 1 < len(effective_args):
                inner_cmd = " ".join(effective_args[idx + 1 :])
                if any(b in inner_cmd for b in DANGEROUS_BINARIES) or "rm -rf" in inner_cmd:
                    is_dangerous = True

        return {
            "valid": not is_dangerous,
            "is_dangerous": is_dangerous,
            "commands": [effective_binary],
            "subshells": [],
            "redirections": [],
            "reasons": [f"AST fallback validation: {error_msg}"] if not is_dangerous else ["Destructive command pattern detected in fallback check"],
            "raw_command": cmd_str,
        }
