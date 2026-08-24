"""C-DAC BOSS Linux (Bharat Operating System Solutions) Specialized Runbooks."""

from typing import Any, Dict, List, Optional


BOSS_RUNBOOKS: Dict[str, Dict[str, Any]] = {
    "boss_pragya_desktop": {
        "distro": "BOSS Linux 10.0 (Pragya)",
        "description": "Standard desktop health & package manager integrity for Pragya",
        "checks": [
            {"name": "APT Package Cache", "cmd": "apt-get check 2>&1"},
            {"name": "Display Server / Cinnamon", "cmd": "systemctl status lightdm || systemctl status gdm3"},
            {"name": "BOSS Repository Reachability", "cmd": "apt-cache policy"},
        ],
        "common_fix": "sudo apt-get update && sudo dpkg --configure -a",
    },
    "secure_boss_mac": {
        "distro": "Secure BOSS (Defence/Enterprise)",
        "description": "Mandatory Access Control (MAC) and security audit runbook",
        "checks": [
            {"name": "SELinux / AppArmor Status", "cmd": "sestatus 2>/dev/null || aa-status 2>/dev/null"},
            {"name": "Security Audit Violations", "cmd": "ausearch -m avc -ts recent 2>/dev/null | tail -n 10"},
            {"name": "Unauthorized SUID Binaries", "cmd": "find / -perm -4000 -type f 2>/dev/null | head -n 10"},
        ],
        "common_fix": "sudo audit2why < /var/log/audit/audit.log 2>/dev/null || true",
    },
    "meghdoot_cloud_suite": {
        "distro": "BOSS Server & Meghdoot",
        "description": "C-DAC Meghdoot Cloud & Enterprise Virtualization services",
        "checks": [
            {"name": "Meghdoot Controller Services", "cmd": "systemctl list-units 'meghdoot*' --all"},
            {"name": "LDAP Directory Service", "cmd": "systemctl is-active slapd || echo inactive"},
            {"name": "Secure Mail Gateway", "cmd": "systemctl is-active postfix || echo inactive"},
        ],
        "common_fix": "sudo systemctl restart meghdoot-node slapd postfix",
    },
}


class BossLinuxEngine:
    """Provides C-DAC BOSS Linux specific diagnostic runbooks and distribution detection."""

    @classmethod
    def get_runbook(cls, runbook_key: str) -> Optional[Dict[str, Any]]:
        return BOSS_RUNBOOKS.get(runbook_key)

    @classmethod
    def list_runbooks(cls) -> List[Dict[str, Any]]:
        return [{"id": k, **v} for k, v in BOSS_RUNBOOKS.items()]
