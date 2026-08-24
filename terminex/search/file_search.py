"""High-Performance File and Document Search with Structural Context."""

import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from terminex.search.secret_scrubber import SecretScrubber
from terminex.search.structural_outline import StructuralOutlineExtractor


class FileSearchEngine:
    """Discovers files and documents with automatic content summaries and secret scrubbing."""

    def __init__(self, default_root: Optional[Path] = None):
        self.default_root = Path(default_root) if default_root else Path.cwd()

    def search_by_name(
        self, pattern: str, root_dir: Optional[Path] = None, max_results: int = 20
    ) -> List[Dict[str, Any]]:
        root = Path(root_dir) if root_dir else self.default_root
        results: List[Dict[str, Any]] = []

        if not root.exists():
            return []

        pattern_lower = pattern.lower()

        for current_root, dirs, files in os.walk(root):
            # Exclude noisy folders
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv")]

            for f in files:
                if f.startswith("."):
                    continue
                if fnmatch.fnmatch(f.lower(), f"*{pattern_lower}*"):
                    file_path = Path(current_root) / f
                    try:
                        size_kb = round(file_path.stat().st_size / 1024.0, 1)
                    except Exception:
                        size_kb = 0.0

                    results.append({
                        "filename": f,
                        "path": str(file_path),
                        "size_kb": size_kb,
                        "extension": file_path.suffix,
                    })
                    if len(results) >= max_results:
                        return results

        return results

    def search_content(
        self, query: str, root_dir: Optional[Path] = None, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Searches for files containing text query and generates sanitized snippets."""
        root = Path(root_dir) if root_dir else self.default_root
        results: List[Dict[str, Any]] = []

        if not root.exists():
            return []

        query_lower = query.lower()

        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv")]

            for f in files:
                file_path = Path(current_root) / f
                if file_path.suffix.lower() in (".png", ".jpg", ".exe", ".bin", ".tar", ".gz", ".zip", ".pyc"):
                    continue

                try:
                    if file_path.stat().st_size > 2_000_000:
                        continue
                    text = file_path.read_text(errors="ignore")
                    if query_lower in text.lower():
                        sanitized = SecretScrubber.clean(text)
                        # Extract matching snippet line
                        matching_lines = [
                            l.strip() for l in sanitized.splitlines() if query_lower in l.lower()
                        ]
                        results.append({
                            "filename": f,
                            "path": str(file_path),
                            "match_count": len(matching_lines),
                            "sample_snippet": matching_lines[0][:120] if matching_lines else "",
                        })
                        if len(results) >= max_results:
                            return results
                except Exception:
                    pass

        return results

    def get_file_summary(self, file_path: Path) -> Dict[str, Any]:
        """Returns compressed structural outline with secret scrubbing."""
        return StructuralOutlineExtractor.extract_outline(file_path)
