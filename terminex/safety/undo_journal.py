"""Pre-Mutation Snapshot & One-Command Undo Journal with SHA-256 Audit Trail."""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from terminex.config import AUDIT_LOG_PATH, SNAPSHOTS_DIR


class UndoJournal:
    """Manages pre-mutation file backups, hash-chained receipts, and rollback transactions."""

    def __init__(self, snapshots_dir: Path = SNAPSHOTS_DIR, audit_log: Path = AUDIT_LOG_PATH):
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log = Path(audit_log)
        self._last_hash = self._get_last_audit_hash()

    def _get_last_audit_hash(self) -> str:
        if not self.audit_log.exists():
            return "0" * 64
        try:
            with open(self.audit_log, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                if lines:
                    last_record = json.loads(lines[-1])
                    return last_record.get("hash", "0" * 64)
        except Exception:
            pass
        return "0" * 64

    def create_snapshot(
        self,
        command: str,
        target_paths: List[Path],
        intent_description: str = "",
    ) -> Dict[str, Any]:
        """Creates a pre-mutation snapshot of target paths and generates a transaction receipt."""
        tx_id = f"TX-{int(time.time() * 1000) % 1000000:06d}"
        tx_dir = self.snapshots_dir / tx_id
        tx_dir.mkdir(parents=True, exist_ok=True)

        backup_manifest: List[Dict[str, Any]] = []

        for p in target_paths:
            path_obj = Path(p).resolve()
            if path_obj.exists():
                rel_id = hashlib.md5(str(path_obj).encode()).hexdigest()[:10]
                if path_obj.is_file():
                    dest = tx_dir / f"file_{rel_id}_{path_obj.name}"
                    shutil.copy2(path_obj, dest)
                    backup_manifest.append({
                        "type": "FILE",
                        "original_path": str(path_obj),
                        "backup_file": str(dest.name),
                        "exists_originally": True,
                    })
                elif path_obj.is_dir():
                    dest = tx_dir / f"dir_{rel_id}_{path_obj.name}"
                    shutil.copytree(path_obj, dest, dirs_exist_ok=True)
                    backup_manifest.append({
                        "type": "DIR",
                        "original_path": str(path_obj),
                        "backup_file": str(dest.name),
                        "exists_originally": True,
                    })
            else:
                # File does not exist yet (will be created by command)
                backup_manifest.append({
                    "type": "NEW_FILE",
                    "original_path": str(path_obj),
                    "backup_file": None,
                    "exists_originally": False,
                })

        manifest_file = tx_dir / "manifest.json"
        manifest_data = {
            "tx_id": tx_id,
            "timestamp": time.time(),
            "iso_time": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "intent": intent_description,
            "items": backup_manifest,
            "status": "RECORDED",
        }
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # Append to SHA-256 hash-chained audit log
        raw_payload = f"{self._last_hash}:{tx_id}:{command}:{manifest_data['iso_time']}"
        curr_hash = hashlib.sha256(raw_payload.encode()).hexdigest()

        audit_entry = {
            "tx_id": tx_id,
            "hash": curr_hash,
            "prev_hash": self._last_hash,
            "iso_time": manifest_data["iso_time"],
            "command": command,
            "intent": intent_description,
            "backed_up_count": len(backup_manifest),
        }
        with open(self.audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\n")

        self._last_hash = curr_hash

        return {
            "tx_id": tx_id,
            "hash": curr_hash,
            "tx_dir": str(tx_dir),
            "manifest": manifest_data,
        }

    def rollback(self, tx_id: str) -> Dict[str, Any]:
        """Restores machine state to the pre-mutation snapshot of the given transaction ID."""
        tx_dir = self.snapshots_dir / tx_id
        if not tx_dir.exists():
            return {
                "success": False,
                "tx_id": tx_id,
                "message": f"Transaction '{tx_id}' not found in snapshot journal.",
            }

        manifest_file = tx_dir / "manifest.json"
        if not manifest_file.exists():
            return {
                "success": False,
                "tx_id": tx_id,
                "message": "Manifest file is missing for this transaction.",
            }

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        restored_count = 0
        deleted_count = 0
        errors: List[str] = []

        for item in manifest.get("items", []):
            orig = Path(item["original_path"])
            orig_existed = item.get("exists_originally", True)
            backup_name = item.get("backup_file")

            try:
                if not orig_existed:
                    # File was newly created by the command -> delete it to rollback
                    if orig.exists():
                        if orig.is_file():
                            orig.unlink()
                        elif orig.is_dir():
                            shutil.rmtree(orig)
                        deleted_count += 1
                else:
                    # File existed -> restore from backup
                    if backup_name:
                        backup_src = tx_dir / backup_name
                        if backup_src.is_file():
                            orig.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(backup_src, orig)
                            restored_count += 1
                        elif backup_src.is_dir():
                            if orig.exists():
                                shutil.rmtree(orig)
                            shutil.copytree(backup_src, orig)
                            restored_count += 1
            except Exception as e:
                errors.append(f"Failed to restore {orig}: {str(e)}")

        manifest["status"] = "ROLLED_BACK"
        manifest["rollback_time"] = datetime.now(timezone.utc).isoformat()
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return {
            "success": len(errors) == 0,
            "tx_id": tx_id,
            "command_rolled_back": manifest.get("command"),
            "restored_files": restored_count,
            "cleaned_new_files": deleted_count,
            "errors": errors,
            "message": f"Transaction '{tx_id}' successfully undone ({restored_count} restored, {deleted_count} removed).",
        }

    def list_transactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        transactions: List[Dict[str, Any]] = []
        if not self.snapshots_dir.exists():
            return []

        dirs = sorted(self.snapshots_dir.glob("TX-*"), key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs[:limit]:
            manifest_file = d / "manifest.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        transactions.append(json.load(f))
                except Exception:
                    pass
        return transactions
