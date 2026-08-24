"""Indic Multilingual Natural Language Intent Router (Hindi & Marathi)."""

import re
from typing import Any, Dict, List, Optional, Tuple


class IndicNLPRouter:
    """Parses queries in Hindi, Marathi, and Hinglish into standardized administrative intents."""

    # Intent Mappings: (Regex Pattern, Intent Name, Standard Command, Explanation)
    INDIC_INTENTS: List[Tuple[str, str, str, str]] = [
        # Hindi & Marathi Disk Queries
        (
            r"(?i)(डिस्क|स्टोरेज|मेमोरी|जागा|भरली|भर गई|मोठी फाइल|बड़ी फाइल|साफ करा|खाली करो|space|storage)",
            "STORAGE_CLEANUP_ANALYSIS",
            "find /var/log -type f -size +50M -exec ls -lh {} + 2>/dev/null | head -n 10",
            "डेटा स्टोरेज और बड़ी लॉग फाइलों की जांच कर रहा है (Analyzing storage & large log files)",
        ),
        # Hindi & Marathi Web/Service Down Queries
        (
            r"(?i)(वेबसाइट|साइट|सर्व्हर|बंद|का बंद|समस्या|काय झाले|का झालं|nginx|apache|web server)",
            "WEB_SERVER_DIAGNOSTIC",
            "sudo nginx -t && sudo systemctl status nginx",
            "वेब सर्वर की स्थिति और कॉन्फ़िगरेशन सिंटैक्स की जांच (Checking web server status & config)",
        ),
        # Hindi & Marathi Memory / RAM Queries
        (
            r"(?i)(रॅम|मेमरी|रैम|मेमोरी|वापर|कमी|उपयोग|फुल|ram|memory)",
            "MEMORY_INSPECTION",
            "free -h && ps aux --sort=-%mem | head -n 6",
            "सिस्टम रैम उपयोग और शीर्ष मेमोरी प्रक्रियाओं का निरीक्षण (Checking RAM & top processes)",
        ),
        # Hindi & Marathi Port Queries
        (
            r"(?i)(पोर्ट|पोर्ट्स|उघडे|खुले|कनेक्शन|नेटवर्क|ports|listen)",
            "PORT_LISTENER_AUDIT",
            "ss -tulpn",
            "सक्रिय लिसनिंग नेटवर्क पोर्ट और प्रक्रियाओं की सूची (Listing active network ports)",
        ),
        # Hindi & Marathi Log Queries
        (
            r"(?i)(लॉग|एरर|लॉग्स|त्रुटी|इश्यू|logs|errors)",
            "RECENT_SYSTEM_LOGS",
            "journalctl --since '10 minutes ago' -p err..emerg -n 30",
            "पिछले 10 मिनट के महत्वपूर्ण सिस्टम एरर लॉग्स (Retrieving high-severity system error logs)",
        ),
        # Hindi & Marathi Undo Queries
        (
            r"(?i)(पूर्ववत|वापस|रोलबैक|बदलाव रद्द|undo|rollback)",
            "TRANSACTION_ROLLBACK",
            "terminex undo",
            "अंतिम सिस्टम बदलाव को पूर्ववत (Undo) किया जा रहा है (Rolling back last transaction)",
        ),
    ]

    @classmethod
    def parse_query(cls, user_text: str) -> Optional[Dict[str, Any]]:
        for pat, intent_name, cmd, expl in cls.INDIC_INTENTS:
            if re.search(pat, user_text):
                return {
                    "is_indic": True,
                    "matched_intent": intent_name,
                    "recommended_command": cmd,
                    "localized_explanation": expl,
                    "original_query": user_text,
                }
        return None
