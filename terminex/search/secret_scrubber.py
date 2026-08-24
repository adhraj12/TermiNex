"""Automated Credential Redactor & Zero-Leak Secret Scrubber."""

import re
from typing import Any, Dict, List, Tuple


class SecretScrubber:
    """Intersects text streams and redacts sensitive credentials, tokens, and hashes."""

    PATTERNS: List[Tuple[str, str, str]] = [
        ("PRIVATE_KEY", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
        ("AWS_KEY_ID", r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b", "[REDACTED_AWS_ACCESS_KEY]"),
        ("AWS_SECRET", r"(?i)aws_secret_access_key\s*=\s*['\"]?[0-9a-zA-Z/+=]{40}['\"]?", "aws_secret_access_key = '[REDACTED_AWS_SECRET]'"),
        ("DATABASE_URI", r"(?i)(postgres|mysql|mongodb|redis):\/\/[^:\s]+:([^@\s]+)@", r"\1://user:[REDACTED_DB_PASS]@"),
        ("JWT_BEARER", r"Bearer\s+eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "Bearer [REDACTED_JWT_TOKEN]"),
        ("SHADOW_HASH", r":\$[156]\$[a-zA-Z0-9./]{8}\$[a-zA-Z0-9./]{22,86}:", ":[REDACTED_PASSWD_HASH]:"),
        ("PASSWORD_ASSIGN", r"(?i)(password|passwd|db_pass|secret|api_key|auth_token)\s*([:=])\s*['\"]?([^\s,;'\"]{4,})['\"]?", r"\1\2 '[REDACTED_SECRET]'"),
    ]

    @classmethod
    def sanitize(cls, text: str) -> Dict[str, Any]:
        redacted_count = 0
        cleaned = text

        for label, pat, repl in cls.PATTERNS:
            matches = list(re.finditer(pat, cleaned))
            if matches:
                redacted_count += len(matches)
                cleaned = re.sub(pat, repl, cleaned)

        return {
            "cleaned_text": cleaned,
            "secrets_found": redacted_count,
            "is_sanitized": redacted_count > 0,
        }

    @classmethod
    def clean(cls, text: str) -> str:
        return cls.sanitize(text)["cleaned_text"]
