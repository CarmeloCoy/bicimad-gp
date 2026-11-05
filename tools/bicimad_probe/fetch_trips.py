#!/usr/bin/env python3
"""Fetch and normalize own BiciMAD trips using a locally provided access token.

This script performs exactly one read-only GET request to the observed trips
endpoint. It does not implement login and does not persist credentials.
"""

from __future__ import annotations

import getpass
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from normalize import normalize_response
from safe_output import safe_api_code

ENDPOINT = "https://apiemtpay.emtmadrid.es/v2/bicimad/trips/"
TIMEOUT_SECONDS = 20
OUTPUT_PATH = Path("tools/bicimad_probe/private/trips_normalized.json")

STATIC_HEADERS = {
    "appName": "bicimad",
    "appPlatform": "Android",
    "appPlatformVersion": "Android TIRAMISU",
    "appVersion": "5.8.8",
    "language": "es",
    "mode": "mPass",
}


def main() -> int:
    try:
        secret_headers = _prompt_private_headers()
        status, payload = _fetch_trips(secret_headers)
        normalized = normalize_response(payload)
        _write_normalized_trips(normalized)
        _print_success_summary(status, payload, normalized)
        return 0
    except urllib.error.HTTPError as error:
        payload = _safe_error_payload(error)
        _print_error_summary(
            status=error.code,
            error_type=type(error).__name__,
            payload=payload,
        )
        return 1
    except urllib.error.URLError as error:
        _print_error_summary(
            status=None,
            error_type=type(error.reason).__name__,
            payload=None,
        )
        return 1
    except TimeoutError:
        _print_error_summary(status=None, error_type="TimeoutError", payload=None)
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _print_error_summary(status=None, error_type=type(error).__name__, payload=None)
        return 1


def _prompt_private_headers() -> dict[str, str]:
    access_token = getpass.getpass("accessToken: ").strip()
    email = input("email: ").strip()
    user_id = input("userId: ").strip()
    nif = input("nif: ").strip()
    device_id = input("deviceId: ").strip()
    device_model = input("deviceModel: ").strip()

    values = {
        "accessToken": access_token,
        "email": email,
        "userId": user_id,
        "nif": nif,
        "deviceId": device_id,
        "deviceModel": device_model,
        "session": user_id,
        "User-Agent": "okhttp/4.x",
    }

    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError("Missing required local input")

    return values


def _fetch_trips(secret_headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    headers = {**STATIC_HEADERS, **secret_headers}
    request = urllib.request.Request(ENDPOINT, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        status = response.status
        body = response.read()
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Unexpected response shape")
    return status, payload


def _write_normalized_trips(normalized: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _print_success_summary(
    status: int,
    payload: dict[str, Any],
    normalized: list[dict[str, Any]],
) -> None:
    print(f"HTTP {status}")
    print(f"Codigo de API: {safe_api_code(payload.get('code')) or '-'}")
    received_count = (
        len(payload.get("data", [])) if isinstance(payload.get("data"), list) else 0
    )
    print(f"Viajes recibidos: {received_count}")
    print(f"Viajes normalizados: {len(normalized)}")

    print(f"Archivo generado: {OUTPUT_PATH.as_posix()}")


def _safe_error_payload(error: urllib.error.HTTPError) -> dict[str, Any] | None:
    try:
        body = error.read()
        payload = json.loads(body.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _print_error_summary(
    *,
    status: int | None,
    error_type: str,
    payload: dict[str, Any] | None,
) -> None:
    print(f"HTTP {status if status is not None else '-'}")
    print(f"Tipo de error: {error_type}")
    if payload is not None:
        print(f"Codigo de API: {safe_api_code(payload.get('code')) or '-'}")


if __name__ == "__main__":
    raise SystemExit(main())
