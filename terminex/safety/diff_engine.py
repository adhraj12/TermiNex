"""Diff Engine for generating terraform-plan style unified file diffs."""

import difflib
from pathlib import Path
from typing import Any, Dict, List


class DiffEngine:
    """Computes file additions, modifications, and deletions between pre-state and post-state."""

    @staticmethod
    def compare_directories(pre_dir: Path, post_dir: Path) -> Dict[str, Any]:
        pre_dir = Path(pre_dir)
        post_dir = Path(post_dir)

        pre_files = {p.relative_to(pre_dir): p for p in pre_dir.rglob("*") if p.is_file()}
        post_files = {p.relative_to(post_dir): p for p in post_dir.rglob("*") if p.is_file()}

        all_rel_paths = sorted(set(pre_files.keys()) | set(post_files.keys()))

        added_files: List[str] = []
        deleted_files: List[str] = []
        modified_files: List[Dict[str, Any]] = []

        for rel in all_rel_paths:
            in_pre = rel in pre_files
            in_post = rel in post_files
            rel_str = str(rel).replace("\\", "/")

            if in_post and not in_pre:
                added_files.append(rel_str)
                # Capture content of added file
                try:
                    content = post_files[rel].read_text(errors="replace")
                except Exception:
                    content = "<binary file>"
                diff_text = "\n".join(f"+{line}" for line in content.splitlines()[:50])
                modified_files.append({
                    "path": rel_str,
                    "change_type": "ADDED",
                    "diff": diff_text,
                })

            elif in_pre and not in_post:
                deleted_files.append(rel_str)
                try:
                    content = pre_files[rel].read_text(errors="replace")
                except Exception:
                    content = "<binary file>"
                diff_text = "\n".join(f"-{line}" for line in content.splitlines()[:50])
                modified_files.append({
                    "path": rel_str,
                    "change_type": "DELETED",
                    "diff": diff_text,
                })

            else:
                # File present in both, compare content
                try:
                    pre_content = pre_files[rel].read_text(errors="replace").splitlines(keepends=True)
                    post_content = post_files[rel].read_text(errors="replace").splitlines(keepends=True)
                    if pre_content != post_content:
                        diff = difflib.unified_diff(
                            pre_content,
                            post_content,
                            fromfile=f"a/{rel_str}",
                            tofile=f"b/{rel_str}",
                            lineterm="",
                        )
                        diff_text = "".join(diff)
                        modified_files.append({
                            "path": rel_str,
                            "change_type": "MODIFIED",
                            "diff": diff_text,
                        })
                except Exception as e:
                    pass

        has_changes = bool(added_files or deleted_files or modified_files)

        return {
            "has_changes": has_changes,
            "added_count": len(added_files),
            "deleted_count": len(deleted_files),
            "modified_count": len(modified_files),
            "added_files": added_files,
            "deleted_files": deleted_files,
            "file_diffs": modified_files,
        }

    @staticmethod
    def format_diff_for_terminal(diff_data: Dict[str, Any]) -> str:
        """Format the diff result with color-coded syntax for terminal display."""
        if not diff_data.get("has_changes"):
            return "[dim]No filesystem modifications observed in rehearsal.[/dim]"

        lines: List[str] = [
            f"[bold cyan]🔍 Rehearsal Diff Preview ({diff_data['modified_count']} files changed):[/bold cyan]"
        ]

        for item in diff_data.get("file_diffs", []):
            change_type = item["change_type"]
            path = item["path"]
            if change_type == "ADDED":
                lines.append(f"[bold green]+ [CREATE] {path}[/bold green]")
            elif change_type == "DELETED":
                lines.append(f"[bold red]- [DELETE] {path}[/bold red]")
            else:
                lines.append(f"[bold yellow]~ [MODIFY] {path}[/bold yellow]")

            for line in item["diff"].splitlines()[:20]:
                if line.startswith("+"):
                    lines.append(f"  [green]{line}[/green]")
                elif line.startswith("-"):
                    lines.append(f"  [red]{line}[/red]")
                elif line.startswith("@@"):
                    lines.append(f"  [cyan]{line}[/cyan]")
                else:
                    lines.append(f"  [dim]{line}[/dim]")

        return "\n".join(lines)
