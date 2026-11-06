#!/usr/bin/env python3
"""Run the local read-only BiciMAD experiment with an interactive MPass login."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

from local_secrets import MissingLocalTechnicalConfigError, load_technical_config
from mpass_client import ProbeRequestError, run_login_trip_flow

DEFAULT_DEVICE_MODEL = "Samsung SM-A127F"
DEFAULT_ANDROID_VERSION = "13"
GENERATED_DEVICE_ID_PATH = Path("tools/bicimad_probe/private/generated_device_id.txt")
DEVICE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
EMAIL_ENV_VAR = "BICIMAD_EMT_EMAIL"
PASSWORD_ENV_VAR = "BICIMAD_EMT_PASSWORD"


class InvalidLocalDeviceIdError(ValueError):
    pass


class MissingAccountCredentialsError(ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        values = _prompt_values()
        result = run_login_trip_flow(**values)
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
    except (OSError, ValueError) as error:
        print("Etapa fallida: entrada")
        print("HTTP -")
        print(f"Tipo de excepcion: {type(error).__name__}")
        return 1

    print("Login MPass: correcto")
    expiration = (
        result.token_sec_expiration if result.token_sec_expiration is not None else "-"
    )
    print(f"Caducidad declarada del token: {expiration} segundos")
    print("Datos de usuario: correctos")
    print(f"HTTP viajes: {result.trips_status}")
    print(f"Codigo de API: {result.trips_api_code or '-'}")
    print(f"Viajes recibidos: {result.received_count}")
    print(f"Viajes normalizados: {result.normalized_count}")
    print(f"Archivo generado: {result.output_path.as_posix()}")
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local read-only BiciMAD experiment with MPass login.",
    )
    parser.add_argument(
        "--auto-device-id",
        action="store_true",
        help="Deprecated no-op. A generated local deviceId is now always used.",
    )
    return parser.parse_args(argv)


def _prompt_values() -> dict[str, str]:
    email_env = os.environ.get(EMAIL_ENV_VAR)
    password_env = os.environ.get(PASSWORD_ENV_VAR)
    if email_env is not None or password_env is not None:
        if not email_env or not password_env or not email_env.strip():
            raise MissingAccountCredentialsError()
        email = email_env.strip()
        password = password_env
    else:
        email = input("Email: ").strip()
        password = getpass.getpass("Contraseña: ")
    technical_config = load_technical_config()
    device_id = get_or_create_generated_device_id()
    device_model_visible = DEFAULT_DEVICE_MODEL
    android_version = DEFAULT_ANDROID_VERSION

    values = {
        "email": email,
        "password": password,
        "pass_key": technical_config.pass_key,
        "x_client_id": technical_config.x_client_id,
        "device_id": device_id,
        "device_model_visible": device_model_visible,
        "android_version": android_version,
    }
    if any(not value for value in values.values()):
        raise ValueError("Missing required local input")
    return values


def get_or_create_generated_device_id(
    path: Path = GENERATED_DEVICE_ID_PATH,
) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if not DEVICE_ID_PATTERN.fullmatch(value):
            raise InvalidLocalDeviceIdError()
        return value

    value = secrets.token_hex(8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def _input_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _print_safe_error(error: ProbeRequestError) -> None:
    print(f"Etapa fallida: {error.stage}")
    print(f"HTTP {error.status if error.status is not None else '-'}")
    if error.api_code is not None:
        print(f"Codigo de API: {error.api_code}")
    print(f"Tipo de excepcion: {error.error_type}")


if __name__ == "__main__":
    raise SystemExit(main())
