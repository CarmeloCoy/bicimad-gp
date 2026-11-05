"""Small allowlist for server data that may be written to a shared console."""

from __future__ import annotations

import re


def safe_api_code(value: object) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[0-9]{2}", value) else None
    )
