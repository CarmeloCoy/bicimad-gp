#!/usr/bin/env python3
"""Sanitize a local HAR capture before analysis or sharing.

The script never prints source values. It only writes a sanitized HAR.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED_TOKEN = "<REDACTED_TOKEN>"
REDACTED_PASSWORD = "<REDACTED_PASSWORD>"
REDACTED_COOKIE = "<REDACTED_COOKIE>"
REDACTED_PERSONAL_DATA = "<REDACTED_PERSONAL_DATA>"

TOKEN_KEYS = {
    "authorization",
    "proxy-authorization",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "x-api-key",
    "client_secret",
    "session",
    "session_id",
    "jwt",
    "secret",
}
PASSWORD_KEYS = {"password", "passwd"}
COOKIE_KEYS = {"cookie", "set-cookie"}
COOKIE_CONTAINER_KEYS = {"cookies"}
PERSONAL_KEYS = {
    "email",
    "username",
    "phone",
    "telephone",
    "document",
    "dni",
}
SENSITIVE_KEYS = TOKEN_KEYS | PASSWORD_KEYS | COOKIE_KEYS | PERSONAL_KEYS

TOKEN_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
]
PERSONAL_PATTERNS = [
    re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+?\d[\s-]?){8,15}\b"),
    re.compile(r"\b\d{8}[A-Za-z]\b"),
]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "Usage: python sanitize_har.py input.har output.sanitized.har",
            file=sys.stderr,
        )
        return 2

    input_path = Path(argv[1])
    output_path = Path(argv[2])

    try:
        har = _load_har(input_path)
        sanitized = sanitize_har(har)
        output_path.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except HarValidationError as error:
        print(f"Invalid HAR: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"File error: {error.strerror}", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print("Invalid HAR: file is not valid JSON", file=sys.stderr)
        return 1

    print(f"Sanitized HAR written to {output_path}", file=sys.stderr)
    return 0


class HarValidationError(ValueError):
    pass


def sanitize_har(har: dict[str, Any]) -> dict[str, Any]:
    _validate_har(har)
    sanitized = deepcopy(har)
    return _sanitize_node(sanitized)


def _load_har(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise HarValidationError("root must be a JSON object")
    _validate_har(data)
    return data


def _validate_har(har: dict[str, Any]) -> None:
    log = har.get("log")
    if not isinstance(log, dict):
        raise HarValidationError("missing log object")
    entries = log.get("entries")
    if not isinstance(entries, list):
        raise HarValidationError("missing log.entries array")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise HarValidationError(f"entry {index} is not an object")
        if not isinstance(entry.get("request"), dict):
            raise HarValidationError(f"entry {index} missing request object")
        if not isinstance(entry.get("response"), dict):
            raise HarValidationError(f"entry {index} missing response object")


def _sanitize_node(node: Any, key_hint: str | None = None) -> Any:
    marker = _marker_for_key(key_hint)
    if marker is not None:
        return _redact_value_shape(node, marker)

    if isinstance(node, dict):
        sanitized: dict[str, Any] = {}
        pair_name = node.get("name")
        if isinstance(pair_name, str) and "value" in node:
            pair_marker = _marker_for_key(pair_name)
            if pair_marker is not None:
                sanitized.update(node)
                sanitized["value"] = _redact_value_shape(node.get("value"), pair_marker)
                for nested_key, nested_value in node.items():
                    if nested_key not in {"value"}:
                        sanitized[nested_key] = _sanitize_node(nested_value, nested_key)
                return sanitized

        for key, value in node.items():
            if key == "url" and isinstance(value, str):
                sanitized[key] = _sanitize_url(value)
            elif key.lower() in COOKIE_CONTAINER_KEYS and isinstance(value, list):
                sanitized[key] = [_sanitize_cookie(item) for item in value]
            elif key == "text" and isinstance(value, str):
                sanitized[key] = _sanitize_text_field(value)
            else:
                sanitized[key] = _sanitize_node(value, key)
        return sanitized

    if isinstance(node, list):
        return [_sanitize_node(item, key_hint) for item in node]

    if isinstance(node, str):
        return _sanitize_free_text(node)

    return node


def _marker_for_key(key: str | None) -> str | None:
    if key is None:
        return None
    normalized = key.lower()
    if normalized in COOKIE_KEYS:
        return REDACTED_COOKIE
    if normalized in PASSWORD_KEYS:
        return REDACTED_PASSWORD
    if normalized in PERSONAL_KEYS:
        return REDACTED_PERSONAL_DATA
    if normalized in TOKEN_KEYS:
        return REDACTED_TOKEN
    return None


def _redact_value_shape(value: Any, marker: str) -> Any:
    if isinstance(value, list):
        return [_redact_value_shape(item, marker) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value_shape(item, marker) for key, item in value.items()}
    return marker


def _sanitize_cookie(item: Any) -> Any:
    if isinstance(item, dict):
        return {
            key: REDACTED_COOKIE
            if key.lower() == "value"
            else _sanitize_node(value, key)
            for key, value in item.items()
        }
    return REDACTED_COOKIE


def _sanitize_text_field(value: str) -> str:
    decoded = _try_decode_json(value)
    if decoded is not None:
        return json.dumps(
            _sanitize_node(decoded), ensure_ascii=False, separators=(",", ":")
        )

    decoded_base64 = _try_decode_base64_json(value)
    if decoded_base64 is not None:
        sanitized_json = json.dumps(
            _sanitize_node(decoded_base64),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return base64.b64encode(sanitized_json.encode("utf-8")).decode("ascii")

    return _sanitize_free_text(value)


def _try_decode_json(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _try_decode_base64_json(value: str) -> Any | None:
    try:
        decoded_bytes = base64.b64decode(value, validate=True)
        decoded_text = decoded_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return _try_decode_json(decoded_text)


def _sanitize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return _sanitize_free_text(url)

    netloc = parts.netloc
    if "@" in netloc:
        host = netloc.rsplit("@", 1)[1]
        netloc = f"{REDACTED_PERSONAL_DATA}@{host}"

    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        marker = _marker_for_key(key)
        safe_value = marker if marker is not None else _sanitize_free_text(value)
        query_items.append((key, safe_value))

    return urlunsplit(
        (
            parts.scheme,
            netloc,
            _sanitize_free_text(parts.path),
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _sanitize_free_text(value: str) -> str:
    sanitized = value
    for pattern in TOKEN_PATTERNS:
        sanitized = pattern.sub(REDACTED_TOKEN, sanitized)
    for pattern in PERSONAL_PATTERNS:
        sanitized = pattern.sub(REDACTED_PERSONAL_DATA, sanitized)
    return sanitized


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
