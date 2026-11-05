#!/usr/bin/env python3
"""Analyze a sanitized HAR capture and summarize candidate BiciMAD endpoints."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

REPORT_JSON = "bicimad_probe_report.json"
REPORT_TXT = "bicimad_probe_report.txt"
REDACTED_MARKERS = {
    "<REDACTED_TOKEN>",
    "<REDACTED_PASSWORD>",
    "<REDACTED_COOKIE>",
    "<REDACTED_PERSONAL_DATA>",
}
SENSITIVE_VALUE_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "password",
    "passwd",
    "secret",
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
    "email",
    "username",
    "phone",
    "telephone",
    "document",
    "dni",
}
SECRET_PATTERNS = [
    re.compile(r"\bBearer\s+(?!<REDACTED_TOKEN>)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{8}[A-Za-z]\b"),
    re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]

RELEVANT_TERMS = {
    "auth",
    "login",
    "signin",
    "oauth",
    "token",
    "refresh",
    "session",
    "user",
    "profile",
    "customer",
    "account",
    "trip",
    "trips",
    "ride",
    "rides",
    "journey",
    "journeys",
    "travel",
    "history",
    "historical",
    "movement",
    "rental",
    "consumption",
    "station",
    "origin",
    "destination",
    "duration",
}

PAGINATION_FIELDS = {
    "page",
    "size",
    "limit",
    "offset",
    "cursor",
    "next",
    "total",
    "totalpages",
    "hasmore",
    "from",
    "to",
    "startdate",
    "enddate",
}

RELEVANT_HEADER_NAMES = {
    "authorization",
    "content-type",
    "accept",
    "x-api-key",
    "cookie",
    "set-cookie",
    "user-agent",
    "x-requested-with",
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python analyze_har.py capture.sanitized.har", file=sys.stderr)
        return 2

    input_path = Path(argv[1])
    if not input_path.name.endswith(".sanitized.har"):
        print(
            "Refusing to analyze non-sanitized input. Use *.sanitized.har.",
            file=sys.stderr,
        )
        return 1

    try:
        har = json.loads(input_path.read_text(encoding="utf-8"))
        _ensure_sanitized(har)
        report = analyze_har(har)
        Path(REPORT_JSON).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(REPORT_TXT).write_text(render_text_report(report), encoding="utf-8")
    except json.JSONDecodeError:
        print("Invalid HAR: file is not valid JSON", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"Reports written: {REPORT_TXT}, {REPORT_JSON}", file=sys.stderr)
    return 0


def analyze_har(har: dict[str, Any]) -> dict[str, Any]:
    entries = _entries_from_har(har)
    relevant = []
    for index, entry in enumerate(entries):
        summary = _summarize_entry(index, entry)
        if summary["matched_terms"]:
            relevant.append(summary)

    return {
        "note": "Clasificación heurística sobre HAR sanitizado; no es una conclusión definitiva.",
        "total_entries": len(entries),
        "relevant_entries": relevant,
    }


def _ensure_sanitized(node: Any, key_hint: str | None = None) -> None:
    if isinstance(node, dict):
        if (
            key_hint
            and key_hint.lower() == "cookies"
            and "value" in node
            and node.get("value") not in REDACTED_MARKERS
        ):
            raise ValueError("Input does not appear sanitized: cookie value remains")
        pair_name = node.get("name")
        if isinstance(pair_name, str) and "value" in node:
            _ensure_sanitized(node.get("value"), pair_name)
        for key, value in node.items():
            if key != "value":
                _ensure_sanitized(value, key)
        return

    if isinstance(node, list):
        for item in node:
            _ensure_sanitized(item, key_hint)
        return

    if not isinstance(node, str):
        return

    if (
        key_hint
        and key_hint.lower() in SENSITIVE_VALUE_KEYS
        and node not in REDACTED_MARKERS
    ):
        raise ValueError("Input does not appear sanitized: sensitive value remains")

    for pattern in SECRET_PATTERNS:
        if pattern.search(node):
            raise ValueError(
                "Input does not appear sanitized: sensitive pattern remains"
            )


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        "BiciMAD HAR probe report",
        "Clasificación heurística sobre HAR sanitizado; no es una conclusión definitiva.",
        f"Entradas totales: {report['total_entries']}",
        f"Entradas relevantes: {len(report['relevant_entries'])}",
        "",
    ]

    for entry in report["relevant_entries"]:
        lines.extend(
            [
                f"[{entry['index']}] {entry['startedDateTime']}",
                f"  {entry['method']} {entry['host']}{entry['path']} -> {entry['status']}",
                f"  content-type: {entry['content_type'] or '-'}",
                f"  clasificación: {', '.join(entry['classification']) or 'sin clasificar'}",
                f"  query params: {', '.join(entry['query_parameter_names']) or '-'}",
                f"  cabeceras relevantes: {', '.join(entry['relevant_header_names']) or '-'}",
                f"  request JSON: {', '.join(entry['request_json_fields']) or '-'}",
                f"  response JSON: {', '.join(entry['response_json_fields']) or '-'}",
                f"  paginación: {', '.join(entry['pagination_indicators']) or '-'}",
                "",
            ]
        )
    return "\n".join(lines)


def _entries_from_har(har: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(har, dict):
        raise TypeError("Invalid HAR: root must be an object")
    log = har.get("log")
    if not isinstance(log, dict):
        raise TypeError("Invalid HAR: missing log object")
    entries = log.get("entries")
    if not isinstance(entries, list):
        raise TypeError("Invalid HAR: missing log.entries array")
    return [entry for entry in entries if isinstance(entry, dict)]


def _summarize_entry(index: int, entry: dict[str, Any]) -> dict[str, Any]:
    request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
    response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
    url = str(request.get("url") or "")
    parts = urlsplit(url)
    path = parts.path or "/"
    query_names = _query_names(request, parts.query)
    request_headers = _header_names(request)
    response_headers = _header_names(response)
    content_type = _content_type(response, request)
    request_json_fields = _json_field_names(_request_text(request))
    response_json_fields = _json_field_names(_response_text(response))
    all_names = (
        query_names
        | request_headers
        | response_headers
        | request_json_fields
        | response_json_fields
    )
    searchable = " ".join(
        [
            str(request.get("method") or ""),
            parts.netloc,
            path,
            " ".join(all_names),
        ]
    ).lower()
    matched_terms = sorted(term for term in RELEVANT_TERMS if term in searchable)

    return {
        "index": index,
        "startedDateTime": entry.get("startedDateTime"),
        "method": request.get("method"),
        "host": parts.netloc,
        "path": path,
        "status": response.get("status"),
        "content_type": content_type,
        "query_parameter_names": sorted(query_names),
        "relevant_header_names": sorted(
            name
            for name in request_headers | response_headers
            if name.lower() in RELEVANT_HEADER_NAMES
        ),
        "request_json_fields": sorted(request_json_fields),
        "response_json_fields": sorted(response_json_fields),
        "classification": _classify(searchable),
        "pagination_indicators": sorted(_pagination_indicators(all_names)),
        "matched_terms": matched_terms,
    }


def _query_names(request: dict[str, Any], raw_query: str) -> set[str]:
    names = {key for key, _value in parse_qsl(raw_query, keep_blank_values=True)}
    query_string = request.get("queryString")
    if isinstance(query_string, list):
        for item in query_string:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"])
    return names


def _header_names(message: dict[str, Any]) -> set[str]:
    headers = message.get("headers")
    if not isinstance(headers, list):
        return set()
    return {
        item["name"]
        for item in headers
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _content_type(response: dict[str, Any], request: dict[str, Any]) -> str | None:
    for message in (response, request):
        headers = message.get("headers")
        if not isinstance(headers, list):
            continue
        for header in headers:
            if (
                isinstance(header, dict)
                and str(header.get("name", "")).lower() == "content-type"
            ):
                value = header.get("value")
                return str(value) if value is not None else "present"
    return None


def _request_text(request: dict[str, Any]) -> str | None:
    post_data = request.get("postData")
    if isinstance(post_data, dict) and isinstance(post_data.get("text"), str):
        return post_data["text"]
    return None


def _response_text(response: dict[str, Any]) -> str | None:
    content = response.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return None


def _json_field_names(text: str | None) -> set[str]:
    if not text:
        return set()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return set()

    names: set[str] = set()
    _collect_field_names(decoded, names)
    return names


def _collect_field_names(node: Any, names: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            names.add(str(key))
            _collect_field_names(value, names)
    elif isinstance(node, list):
        for item in node:
            _collect_field_names(item, names)


def _classify(searchable: str) -> list[str]:
    classifications = []
    if any(term in searchable for term in ("login", "signin", "oauth", "auth")):
        classifications.append("posible login")
    if "refresh" in searchable:
        classifications.append("posible refresh")
    if any(term in searchable for term in ("profile", "user", "customer", "account")):
        classifications.append("posible perfil")
    if any(
        term in searchable
        for term in (
            "trip",
            "trips",
            "ride",
            "rides",
            "journey",
            "journeys",
            "history",
            "historical",
        )
    ):
        classifications.append("posible historial")
    if any(
        term in searchable
        for term in (
            "movement",
            "rental",
            "consumption",
            "station",
            "origin",
            "destination",
            "duration",
        )
    ):
        classifications.append("posible detalle de viaje")
    return classifications


def _pagination_indicators(names: set[str]) -> set[str]:
    return {name for name in names if name.lower() in PAGINATION_FIELDS}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
