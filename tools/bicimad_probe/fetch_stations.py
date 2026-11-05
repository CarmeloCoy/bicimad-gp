#!/usr/bin/env python3
"""Log in with an own BiciMAD account and fetch EMT OpenAPI stations."""

from __future__ import annotations

import getpass
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from normalize_stations import normalize_stations_response
from safe_output import safe_api_code

LOGIN_ENDPOINT = "https://openapi.emtmadrid.es/v1/mobilitylabs/user/login/"
ENDPOINT = "https://openapi.emtmadrid.es/v2/transport/bicimad/stations/"
TIMEOUT_SECONDS = 20
RAW_OUTPUT_PATH = Path("tools/bicimad_probe/private/stations_raw.json")
OUTPUT_PATH = Path("tools/bicimad_probe/private/stations_normalized.json")


def main() -> int:
    stage = "login"
    try:
        email = input("Usuario/email EMT OpenAPI: ").strip()
        password = getpass.getpass("Contraseña: ")
        if not email or not password:
            raise ValueError("Missing required local input")

        access_token = _login(email, password)
        stage = "estaciones"
        status, payload = _fetch_stations(access_token)
        stations = normalize_stations_response(payload)
        _write_raw_response(payload)
        _write_stations(stations)
        _print_success_summary(status, payload, stations)
        return 0
    except urllib.error.HTTPError as error:
        _print_error_summary(
            stage=stage,
            status=error.code,
            error_type=type(error).__name__,
            payload=_safe_error_payload(error),
        )
        return 1
    except OpenApiLoginError as error:
        print("Etapa fallida: login")
        print(f"HTTP {error.status}")
        print(f"Tipo de error: {error.error_type}")
        if error.api_code is not None:
            print(f"Codigo de API: {error.api_code}")
        return 1
    except urllib.error.URLError as error:
        _print_error_summary(
            stage=stage,
            status=None,
            error_type=type(error.reason).__name__,
            payload=None,
        )
        return 1
    except TimeoutError:
        _print_error_summary(
            stage=stage,
            status=None,
            error_type="TimeoutError",
            payload=None,
        )
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _print_error_summary(
            stage=stage,
            status=None,
            error_type=type(error).__name__,
            payload=None,
        )
        return 1


def _login(
    email: str,
    password: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    status, payload = _fetch_json(
        LOGIN_ENDPOINT,
        headers={"email": email, "password": password},
        opener=opener,
    )
    if payload.get("code") != "00":
        raise OpenApiLoginError(status, payload.get("code"), "ApiError")

    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise OpenApiLoginError(status, payload.get("code"), "InvalidResponse")
    access_token = data[0].get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise OpenApiLoginError(status, payload.get("code"), "MissingAccessToken")
    return access_token


def _fetch_stations(
    access_token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[int, dict[str, Any]]:
    return _fetch_json(
        ENDPOINT,
        headers={"accessToken": access_token, "Accept": "application/json"},
        opener=opener,
    )


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    with opener(request, timeout=TIMEOUT_SECONDS) as response:
        status = response.status
        body = response.read()
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Unexpected response shape")
    return status, payload


def _write_stations(stations: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_raw_response(payload: dict[str, Any]) -> None:
    RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _print_success_summary(
    status: int,
    payload: dict[str, Any],
    stations: list[dict[str, Any]],
) -> None:
    received = payload.get("data")
    received_count = len(received) if isinstance(received, list) else 0
    print(f"HTTP {status}")
    print(f"Codigo de API: {safe_api_code(payload.get('code')) or '-'}")
    print(f"Estaciones recibidas: {received_count}")
    print(f"Estaciones normalizadas: {len(stations)}")
    print(f"Respuesta original: {RAW_OUTPUT_PATH.as_posix()}")
    print(f"Resultado normalizado: {OUTPUT_PATH.as_posix()}")


def _safe_error_payload(error: urllib.error.HTTPError) -> dict[str, Any] | None:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _print_error_summary(
    *,
    stage: str,
    status: int | None,
    error_type: str,
    payload: dict[str, Any] | None,
) -> None:
    print(f"Etapa fallida: {stage}")
    print(f"HTTP {status if status is not None else '-'}")
    print(f"Tipo de error: {error_type}")
    if payload is not None:
        print(f"Codigo de API: {safe_api_code(payload.get('code')) or '-'}")


class OpenApiLoginError(ValueError):
    def __init__(self, status: int, api_code: object, error_type: str) -> None:
        super().__init__(error_type)
        self.status = status
        self.api_code = safe_api_code(api_code)
        self.error_type = error_type


if __name__ == "__main__":
    raise SystemExit(main())
