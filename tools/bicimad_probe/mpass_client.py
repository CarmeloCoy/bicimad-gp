#!/usr/bin/env python3
"""Minimal read-only MPass/BiciMAD client for local experiments.

The module intentionally exposes small functions that are easy to test with a
mocked opener. It does not persist credentials, tokens or raw responses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normalize import normalize_response
from safe_output import safe_api_code

LOGIN_ENDPOINT = "https://api.mpass.mobi/v1/core/identity/login/integrator"
USERDATA_ENDPOINT = "https://apiemtpay.emtmadrid.es/v2/bicimad/userdata/"
TRIPS_ENDPOINT = "https://apiemtpay.emtmadrid.es/v2/bicimad/trips/"
TIMEOUT_SECONDS = 20
OUTPUT_PATH = Path("tools/bicimad_probe/private/trips_normalized.json")

STATIC_BICIMAD_HEADERS = {
    "appName": "bicimad",
    "appPlatform": "Android",
    "appPlatformVersion": "Android TIRAMISU",
    "appVersion": "5.8.8",
    "language": "es",
    "mode": "mPass",
}

Opener = Callable[..., Any]


@dataclass(frozen=True, repr=False)
class LoginResult:
    access_token: str
    user_id: str
    token_sec_expiration: int | None


@dataclass(frozen=True, repr=False)
class JsonResponse:
    status: int
    payload: dict[str, Any]


@dataclass(frozen=True, repr=False)
class FlowResult:
    token_sec_expiration: int | None
    trips_status: int
    trips_api_code: str | None
    received_count: int
    normalized_count: int
    output_path: Path


class ProbeRequestError(Exception):
    def __init__(
        self,
        *,
        stage: str,
        status: int | None,
        api_code: str | None,
        api_description: str | None,
        error_type: str,
    ) -> None:
        super().__init__(error_type)
        self.stage = stage
        self.status = status
        self.api_code = safe_api_code(api_code)
        # A backend description can echo credentials or personal information.
        # Keep the attribute for existing diagnostic clients, but not its content.
        self.api_description = None
        self.error_type = error_type


def build_login_device_model(visible_name: str, android_version: str) -> str:
    return json.dumps(
        {
            "name": visible_name,
            "model": "Android",
            "version": android_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def login(
    *,
    email: str,
    password: str,
    pass_key: str,
    x_client_id: str,
    device_id: str,
    login_device_model: str,
    opener: Opener = urllib.request.urlopen,
) -> LoginResult:
    response = _request_json(
        stage="login",
        url=LOGIN_ENDPOINT,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "appName": "bicimad",
            "appPlatform": "Android",
            "appPlatformVersion": "Android TIRAMISU",
            "appVersion": "5.8.8",
            "debug": "1",
            "deviceId": device_id,
            "deviceModel": login_device_model,
            "language": "ES",
            "X-ClientId": x_client_id,
        },
        body={
            "email": email,
            "passKey": pass_key,
            "password": password,
            "X-ClientId": x_client_id,
        },
        opener=opener,
    )
    _ensure_login_success(response)

    data = response.payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ProbeRequestError(
            stage="login",
            status=response.status,
            api_code=_safe_str(response.payload.get("code")),
            api_description=_safe_str(response.payload.get("description")),
            error_type="InvalidResponse",
        )

    first = data[0]
    access_token = first.get("accessToken")
    user_id = first.get("idUser")
    if not isinstance(access_token, str) or not access_token:
        raise ProbeRequestError(
            stage="login",
            status=response.status,
            api_code=_safe_str(response.payload.get("code")),
            api_description=_safe_str(response.payload.get("description")),
            error_type="MissingAccessToken",
        )
    if not isinstance(user_id, str) or not user_id:
        raise ProbeRequestError(
            stage="login",
            status=response.status,
            api_code=_safe_str(response.payload.get("code")),
            api_description=_safe_str(response.payload.get("description")),
            error_type="MissingUserId",
        )

    expiration = first.get("tokenSecExpiration")
    return LoginResult(
        access_token=access_token,
        user_id=user_id,
        token_sec_expiration=expiration if isinstance(expiration, int) else None,
    )


def fetch_userdata_dn(
    *,
    access_token: str,
    email: str,
    user_id: str,
    device_id: str,
    device_model: str,
    opener: Opener = urllib.request.urlopen,
) -> str:
    response = _request_json(
        stage="userdata",
        url=USERDATA_ENDPOINT,
        method="GET",
        headers=build_authenticated_headers(
            access_token=access_token,
            email=email,
            user_id=user_id,
            nif=None,
            device_id=device_id,
            device_model=device_model,
        ),
        body=None,
        opener=opener,
    )
    _ensure_userdata_success(response)

    data = response.payload.get("data")
    if not isinstance(data, dict):
        raise ProbeRequestError(
            stage="userdata",
            status=response.status,
            api_code=_safe_str(response.payload.get("code")),
            api_description=_safe_str(response.payload.get("description")),
            error_type="InvalidResponse",
        )

    dn = data.get("DS_DN")
    if not isinstance(dn, str) or not dn.strip():
        raise ProbeRequestError(
            stage="userdata",
            status=response.status,
            api_code=_safe_str(response.payload.get("code")),
            api_description=_safe_str(response.payload.get("description")),
            error_type="MissingRequiredField",
        )
    return dn.strip()


def fetch_trips(
    *,
    access_token: str,
    email: str,
    user_id: str,
    nif: str,
    device_id: str,
    device_model: str,
    page: int | None = None,
    opener: Opener = urllib.request.urlopen,
) -> JsonResponse:
    headers = build_authenticated_headers(
        access_token=access_token,
        email=email,
        user_id=user_id,
        nif=nif,
        device_id=device_id,
        device_model=device_model,
    )
    if page is not None:
        if page < 1:
            raise ValueError("page must be at least 1")
        headers["page"] = str(page)

    response = _request_json(
        stage="trips",
        url=TRIPS_ENDPOINT,
        method="GET",
        headers=headers,
        body=None,
        opener=opener,
    )
    _ensure_trips_success(response)
    return response


def build_authenticated_headers(
    *,
    access_token: str,
    email: str,
    user_id: str,
    nif: str | None,
    device_id: str,
    device_model: str,
) -> dict[str, str]:
    headers = {
        **STATIC_BICIMAD_HEADERS,
        "accessToken": access_token,
        "email": email,
        "userId": user_id,
        "session": user_id,
        "deviceId": device_id,
        "deviceModel": device_model,
        "User-Agent": "okhttp/4.x",
    }
    if nif is not None:
        headers["nif"] = nif
    return headers


def run_login_trip_flow(
    *,
    email: str,
    password: str,
    pass_key: str,
    x_client_id: str,
    device_id: str,
    device_model_visible: str,
    android_version: str,
    output_path: Path = OUTPUT_PATH,
    opener: Opener = urllib.request.urlopen,
) -> FlowResult:
    login_result = login(
        email=email,
        password=password,
        pass_key=pass_key,
        x_client_id=x_client_id,
        device_id=device_id,
        login_device_model=build_login_device_model(
            device_model_visible,
            android_version,
        ),
        opener=opener,
    )
    nif = fetch_userdata_dn(
        access_token=login_result.access_token,
        email=email,
        user_id=login_result.user_id,
        device_id=device_id,
        device_model=device_model_visible,
        opener=opener,
    )
    trips_response = fetch_trips(
        access_token=login_result.access_token,
        email=email,
        user_id=login_result.user_id,
        nif=nif,
        device_id=device_id,
        device_model=device_model_visible,
        opener=opener,
    )
    normalized = normalize_response(trips_response.payload)
    write_normalized_trips(normalized, output_path)

    data = trips_response.payload.get("data")
    return FlowResult(
        token_sec_expiration=login_result.token_sec_expiration,
        trips_status=trips_response.status,
        trips_api_code=safe_api_code(trips_response.payload.get("code")),
        received_count=len(data) if isinstance(data, list) else 0,
        normalized_count=len(normalized),
        output_path=output_path,
    )


def write_normalized_trips(
    normalized: list[dict[str, Any]],
    output_path: Path = OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _request_json(
    *,
    stage: str,
    url: str,
    method: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    opener: Opener,
) -> JsonResponse:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            raw_body = response.read()
    except urllib.error.HTTPError as error:
        payload = _safe_error_payload(error)
        raise ProbeRequestError(
            stage=stage,
            status=error.code,
            api_code=_safe_str(payload.get("code")) if payload else None,
            api_description=_safe_str(payload.get("description")) if payload else None,
            error_type=type(error).__name__,
        ) from None
    except urllib.error.URLError as error:
        raise ProbeRequestError(
            stage=stage,
            status=None,
            api_code=None,
            api_description=None,
            error_type=type(error.reason).__name__,
        ) from None
    except TimeoutError:
        raise ProbeRequestError(
            stage=stage,
            status=None,
            api_code=None,
            api_description=None,
            error_type="TimeoutError",
        ) from None

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeRequestError(
            stage=stage,
            status=status,
            api_code=None,
            api_description=None,
            error_type="InvalidJson",
        ) from None
    if not isinstance(payload, dict):
        raise ProbeRequestError(
            stage=stage,
            status=status,
            api_code=None,
            api_description=None,
            error_type="InvalidResponse",
        )
    return JsonResponse(status=status, payload=payload)


def _ensure_login_success(response: JsonResponse) -> None:
    code = response.payload.get("code")
    if code != "00":
        raise ProbeRequestError(
            stage="login",
            status=response.status,
            api_code=_safe_str(code),
            api_description=_safe_str(response.payload.get("description")),
            error_type="ApiError",
        )


def _ensure_userdata_success(response: JsonResponse) -> None:
    code = response.payload.get("code")
    if code not in {"00", "01"}:
        raise ProbeRequestError(
            stage="userdata",
            status=response.status,
            api_code=_safe_str(code),
            api_description=_safe_str(response.payload.get("description")),
            error_type="ApiError",
        )


def _ensure_trips_success(response: JsonResponse) -> None:
    code = response.payload.get("code")
    if code != "00":
        raise ProbeRequestError(
            stage="trips",
            status=response.status,
            api_code=_safe_str(code),
            api_description=_safe_str(response.payload.get("description")),
            error_type="ApiError",
        )


def _safe_error_payload(error: urllib.error.HTTPError) -> dict[str, Any] | None:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
