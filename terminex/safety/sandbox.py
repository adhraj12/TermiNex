"""Sandbox Rehearsal Engine using Bubblewrap / OverlayFS / Isolated Workspace Mirror."""

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from terminex.config import SANDBOX_TEMP_DIR
from terminex.safety.diff_engine import DiffEngine


class SandboxRehearsalEngine:
    """Executes mutating commands inside an isolated scratch workspace mirror to preview diffs."""

    def __init__(self, sandbox_base: Path = SANDBOX_TEMP_DIR):
        self.sandbox_base = Path(sandbox_base)
        self.sandbox_base.mkdir(parents=True, exist_ok=True)

    def rehearse_command(
        self,
        command: str,
        target_dir: Optional[Path] = None,
        timeout_seconds: int = 10,
    ) -> Dict[str, Any]:
        """Rehearse a command in an isolated environment and return the observed diff & affected paths."""
        work_dir = Path(tempfile.mkdtemp(prefix="terminex_sandbox_", dir=str(self.sandbox_base)))
        pre_state_dir = work_dir / "pre"
        post_state_dir = work_dir / "post"

        pre_state_dir.mkdir()
        post_state_dir.mkdir()

        # Copy target directory context if provided
        target = Path(target_dir).resolve() if target_dir else Path.cwd().resolve()
        if target.exists() and target.is_dir():
            self._safe_copy_tree(target, pre_state_dir)
            self._safe_copy_tree(target, post_state_dir)

        is_linux = platform.system() == "Linux"
        bwrap_available = shutil.which("bwrap") is not None

        env = os.environ.copy()
        env["TERMINEX_SANDBOX"] = "1"

        try:
            if is_linux and bwrap_available:
                proc = subprocess.run(
                    [
                        "bwrap",
                        "--ro-bind", "/usr", "/usr",
                        "--ro-bind", "/bin", "/bin",
                        "--ro-bind", "/lib", "/lib",
                        "--ro-bind", "/lib64", "/lib64",
                        "--bind", str(post_state_dir), str(post_state_dir),
                        "--chdir", str(post_state_dir),
                        "--unshare-all",
                        "--",
                        "bash", "-c", command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=env,
                )
            else:
                shell_cmd = ["bash", "-c", command] if is_linux else ["powershell", "-Command", command]
                proc = subprocess.run(
                    shell_cmd,
                    cwd=str(post_state_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=env,
                )

            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr

        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout = ""
            stderr = f"Sandbox rehearsal timed out after {timeout_seconds}s"
        except Exception as err:
            exit_code = -1
            stdout = ""
            stderr = f"Sandbox execution error: {str(err)}"

        # Compute observed diff
        diff_data = DiffEngine.compare_directories(pre_state_dir, post_state_dir)

        # Extract list of affected host paths for the snapshot engine
        affected_paths: List[Path] = []
        for f in diff_data.get("added_files", []):
            affected_paths.append(target / f)
        for f in diff_data.get("deleted_files", []):
            affected_paths.append(target / f)
        for d in diff_data.get("file_diffs", []):
            p = target / d["path"]
            if p not in affected_paths:
                affected_paths.append(p)

        # Also extract any explicit absolute paths from command string (e.g. /etc/nginx/...)
        for token in command.split():
            if token.startswith("/") and len(token) > 2 and not token.startswith("/bin") and not token.startswith("/usr/bin"):
                p_cand = Path(token.split("=")[-1])
                if p_cand not in affected_paths and (p_cand.exists() or p_cand.parent.exists()):
                    affected_paths.append(p_cand)

        # Cleanup sandbox temp directory
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

        return {
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "diff_data": diff_data,
            "has_mutations": diff_data.get("has_changes", False),
            "affected_paths": [str(p) for p in affected_paths],
            "formatted_diff": DiffEngine.format_diff_for_terminal(diff_data),
        }

    def _safe_copy_tree(self, src: Path, dst: Path, max_files: int = 150):
        count = 0
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv")]
            rel_root = Path(root).relative_to(src)
            target_sub = dst / rel_root
            target_sub.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.startswith("."):
                    continue
                src_file = Path(root) / f
                dst_file = target_sub / f
                try:
                    if src_file.is_file() and src_file.stat().st_size < 1_000_000:
                        shutil.copy2(src_file, dst_file)
                        count += 1
                        if count >= max_files:
                            return
                except Exception:
                    pass
