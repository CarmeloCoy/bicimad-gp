#!/usr/bin/env python3
"""Log in with MPass and fetch BiciMAD stations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fetch_trips_with_login import (
    EMAIL_ENV_VAR,
    InvalidLocalDeviceIdError,
    MissingAccountCredentialsError,
    PASSWORD_ENV_VAR,
    _prompt_values,
)
from local_secrets import MissingLocalTechnicalConfigError
from mpass_client import (
    ProbeRequestError,
    build_login_device_model,
    fetch_stations as _fetch_stations,
    login,
)
from normalize_stations import normalize_stations_response
from safe_output import safe_api_code

PRIVATE_OUTPUT_DIR = Path(__file__).resolve().parent / "private"
RAW_OUTPUT_PATH = PRIVATE_OUTPUT_DIR / "stations_raw.json"
OUTPUT_PATH = PRIVATE_OUTPUT_DIR / "stations_normalized.json"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    raw_output_path = PRIVATE_OUTPUT_DIR / args.raw_filename
    output_path = PRIVATE_OUTPUT_DIR / args.normalized_filename

    stage = "entrada"
    try:
        values = _prompt_values()
        stage = "login"
        login_result = login(
            email=values["email"],
            password=values["password"],
            pass_key=values["pass_key"],
            x_client_id=values["x_client_id"],
            device_id=values["device_id"],
            login_device_model=build_login_device_model(
                values["device_model_visible"],
                values["android_version"],
            ),
        )
        stage = "estaciones"
        response = _fetch_stations(
            access_token=login_result.access_token,
            email=values["email"],
            user_id=login_result.user_id,
            device_id=values["device_id"],
            device_model=values["device_model_visible"],
        )
        status = response.status
        payload = response.payload
        stations = normalize_stations_response(payload)
        _write_raw_response(payload, raw_output_path)
        _write_stations(stations, output_path)
        expiration = (
            login_result.token_sec_expiration
            if login_result.token_sec_expiration is not None
            else "-"
        )
        print("Login MPass: correcto")
        print(f"Caducidad declarada del token: {expiration} segundos")
        _print_success_summary(
            status,
            payload,
            stations,
            raw_output_path=raw_output_path,
            output_path=output_path,
        )
        return 0
    except InvalidLocalDeviceIdError:
        print("El deviceId local tiene un formato inválido")
        return 1
    except MissingLocalTechnicalConfigError:
        print("Falta la configuración técnica local.")
        print("Ejecuta:")
        print("python tools/bicimad_probe/configure_local_probe.py")
        return 1
    except MissingAccountCredentialsError:
        print(f"Configura ambas variables {EMAIL_ENV_VAR} y {PASSWORD_ENV_VAR}.")
        return 1
    except ProbeRequestError as error:
        _print_safe_error(error)
        return 1
    except (OSError, TypeError, ValueError) as error:
        _print_error_summary(
            stage=stage,
            status=None,
            error_type=type(error).__name__,
        )
        return 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and normalize BiciMAD stations into the private directory."
    )
    parser.add_argument(
        "--raw-filename",
        type=_filename_argument,
        default=RAW_OUTPUT_PATH.name,
        help=f"raw response filename in {PRIVATE_OUTPUT_DIR} (default: %(default)s)",
    )
    parser.add_argument(
        "--normalized-filename",
        type=_filename_argument,
        default=OUTPUT_PATH.name,
        help=f"normalized stations filename in {PRIVATE_OUTPUT_DIR} (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.raw_filename == args.normalized_filename:
        parser.error("raw and normalized output filenames must be different")
    return args


def _filename_argument(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\0" in value
    ):
        raise argparse.ArgumentTypeError("provide a filename, not a path")
    return value


def _write_stations(
    stations: list[dict[str, Any]], output_path: Path | None = None
) -> None:
    output_path = output_path or OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_raw_response(
    payload: dict[str, Any], output_path: Path | None = None
) -> None:
    output_path = output_path or RAW_OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _print_success_summary(
    status: int,
    payload: dict[str, Any],
    stations: list[dict[str, Any]],
    *,
    raw_output_path: Path | None = None,
    output_path: Path | None = None,
) -> None:
    raw_output_path = raw_output_path or RAW_OUTPUT_PATH
    output_path = output_path or OUTPUT_PATH
    received = payload.get("data")
    received_count = len(received) if isinstance(received, list) else 0
    print(f"HTTP {status}")
    print(f"Codigo de API: {safe_api_code(payload.get('code')) or '-'}")
    print(f"Estaciones recibidas: {received_count}")
    print(f"Estaciones normalizadas: {len(stations)}")
    print(f"Respuesta original: {raw_output_path.as_posix()}")
    print(f"Resultado normalizado: {output_path.as_posix()}")


def _print_error_summary(
    *,
    stage: str,
    status: int | None,
    error_type: str,
) -> None:
    print(f"Etapa fallida: {stage}")
    print(f"HTTP {status if status is not None else '-'}")
    print(f"Tipo de error: {error_type}")


def _print_safe_error(error: ProbeRequestError) -> None:
    print(f"Etapa fallida: {error.stage}")
    print(f"HTTP {error.status if error.status is not None else '-'}")
    if error.api_code is not None:
        print(f"Codigo de API: {error.api_code}")
    print(f"Tipo de excepcion: {error.error_type}")


if __name__ == "__main__":
    raise SystemExit(main())
