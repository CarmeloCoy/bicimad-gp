#!/usr/bin/env python3
"""Diagnose BiciMAD trip pagination without persisting or exposing trip data.

The official Android client loads the first page without a ``page`` header and
then sends ``page: 1``, ``page: 2`` and so on. This tool reproduces that
read-only sequence and prints aggregate results only.
"""

from __future__ import annotations

import argparse
import getpass
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fetch_trips_with_login import (
    DEFAULT_ANDROID_VERSION,
    DEFAULT_DEVICE_MODEL,
    InvalidLocalDeviceIdError,
    get_or_create_generated_device_id,
)
from local_secrets import MissingLocalTechnicalConfigError, load_technical_config
from mpass_client import (
    JsonResponse,
    ProbeRequestError,
    build_login_device_model,
    fetch_trips,
    fetch_userdata_dn,
    login_or_reuse,
)

DEFAULT_MAX_PAGES = 100
DEFAULT_PAUSE_SECONDS = 0.2
DEFAULT_TRANSIENT_RETRIES = 1
DEFAULT_RETRY_DELAY_SECONDS = 2.0
RETRYABLE_ERROR_TYPES = {"SSLZeroReturnError"}
PAGINATION_MECHANISM = (
    "cabecera HTTP page; primera peticion sin page, despues 1, 2, 3..."
)

FetchPage = Callable[[int | None], JsonResponse]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class PaginationResult:
    page_size: int
    requests_made: int
    pages_with_data: int
    unique_trip_count: int
    duplicate_trip_count: int
    overlap_page_count: int
    transient_retry_count: int
    missing_trip_id_count: int
    oldest_month: str | None
    newest_month: str | None
    stop_reason: str
    stop_detail: str
    limit_assessment: str
    error_status: int | None = None
    error_api_code: str | None = None
    error_type: str | None = None


def paginate_trip_history(
    fetch_page: FetchPage,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    transient_retries: int = DEFAULT_TRANSIENT_RETRIES,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> PaginationResult:
    """Fetch pages using the official sequence and retain aggregate state only."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if pause_seconds < 0:
        raise ValueError("pause_seconds cannot be negative")
    if transient_retries < 0:
        raise ValueError("transient_retries cannot be negative")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")

    seen_trip_ids: set[str] = set()
    page_size = 0
    requests_made = 0
    pages_with_data = 0
    duplicate_trip_count = 0
    overlap_page_count = 0
    transient_retry_count = 0
    missing_trip_id_count = 0
    oldest: datetime | None = None
    newest: datetime | None = None

    for request_index in range(max_pages):
        page_header = None if request_index == 0 else request_index
        page_attempt = 0
        while True:
            try:
                requests_made += 1
                response = fetch_page(page_header)
                break
            except ProbeRequestError as error:
                if (
                    error.error_type in RETRYABLE_ERROR_TYPES
                    and page_attempt < transient_retries
                ):
                    page_attempt += 1
                    transient_retry_count += 1
                    if retry_delay_seconds:
                        sleeper(retry_delay_seconds)
                    continue
                return _result(
                    page_size=page_size,
                    requests_made=requests_made,
                    pages_with_data=pages_with_data,
                    seen_trip_ids=seen_trip_ids,
                    duplicate_trip_count=duplicate_trip_count,
                    overlap_page_count=overlap_page_count,
                    transient_retry_count=transient_retry_count,
                    missing_trip_id_count=missing_trip_id_count,
                    oldest=oldest,
                    newest=newest,
                    stop_reason="backend_error",
                    stop_detail=(
                        "el backend cerro o rechazo la peticion tras los "
                        "reintentos permitidos"
                    ),
                    limit_assessment=(
                        "posible fallo TLS transitorio; no demuestra un limite "
                        "del historico"
                    ),
                    error=error,
                )

        data = response.payload.get("data")
        if not isinstance(data, list):
            return _result(
                page_size=page_size,
                requests_made=requests_made,
                pages_with_data=pages_with_data,
                seen_trip_ids=seen_trip_ids,
                duplicate_trip_count=duplicate_trip_count,
                overlap_page_count=overlap_page_count,
                transient_retry_count=transient_retry_count,
                missing_trip_id_count=missing_trip_id_count,
                oldest=oldest,
                newest=newest,
                stop_reason="invalid_response",
                stop_detail="data no era una lista",
                limit_assessment="indeterminado por respuesta inesperada",
            )

        if request_index == 0:
            page_size = len(data)

        if not data:
            return _result(
                page_size=page_size,
                requests_made=requests_made,
                pages_with_data=pages_with_data,
                seen_trip_ids=seen_trip_ids,
                duplicate_trip_count=duplicate_trip_count,
                overlap_page_count=overlap_page_count,
                transient_retry_count=transient_retry_count,
                missing_trip_id_count=missing_trip_id_count,
                oldest=oldest,
                newest=newest,
                stop_reason="empty_page",
                stop_detail="el endpoint devolvio una pagina vacia",
                limit_assessment="historico aparentemente agotado",
            )

        pages_with_data += 1
        page_trip_ids: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                missing_trip_id_count += 1
                continue
            trip_id = item.get("trip_id")
            if isinstance(trip_id, (str, int)) and str(trip_id).strip():
                page_trip_ids.append(str(trip_id).strip())
            else:
                missing_trip_id_count += 1
            trip_date = _extract_trip_date(item)
            if trip_date is not None:
                oldest = trip_date if oldest is None else min(oldest, trip_date)
                newest = trip_date if newest is None else max(newest, trip_date)

        page_id_set = set(page_trip_ids)
        duplicates_in_page = len(page_trip_ids) - len(page_id_set)
        overlap_ids = page_id_set & seen_trip_ids
        duplicate_trip_count += duplicates_in_page + len(overlap_ids)
        if duplicates_in_page or overlap_ids:
            overlap_page_count += 1

        if page_id_set and page_id_set.issubset(seen_trip_ids):
            return _result(
                page_size=page_size,
                requests_made=requests_made,
                pages_with_data=pages_with_data,
                seen_trip_ids=seen_trip_ids,
                duplicate_trip_count=duplicate_trip_count,
                overlap_page_count=overlap_page_count,
                transient_retry_count=transient_retry_count,
                missing_trip_id_count=missing_trip_id_count,
                oldest=oldest,
                newest=newest,
                stop_reason="fully_repeated_page",
                stop_detail="todos los trip_id de la pagina ya se habian recibido",
                limit_assessment=(
                    "posible limite o repeticion del backend; el agotamiento no es concluyente"
                ),
            )

        seen_trip_ids.update(page_id_set)

        if _has_explicit_end(response.payload):
            return _result(
                page_size=page_size,
                requests_made=requests_made,
                pages_with_data=pages_with_data,
                seen_trip_ids=seen_trip_ids,
                duplicate_trip_count=duplicate_trip_count,
                overlap_page_count=overlap_page_count,
                transient_retry_count=transient_retry_count,
                missing_trip_id_count=missing_trip_id_count,
                oldest=oldest,
                newest=newest,
                stop_reason="explicit_end",
                stop_detail="la respuesta declaro el final de la paginacion",
                limit_assessment="historico aparentemente agotado",
            )

        if page_size > 0 and len(data) < page_size:
            return _result(
                page_size=page_size,
                requests_made=requests_made,
                pages_with_data=pages_with_data,
                seen_trip_ids=seen_trip_ids,
                duplicate_trip_count=duplicate_trip_count,
                overlap_page_count=overlap_page_count,
                transient_retry_count=transient_retry_count,
                missing_trip_id_count=missing_trip_id_count,
                oldest=oldest,
                newest=newest,
                stop_reason="short_page",
                stop_detail="la ultima pagina tenia menos elementos que la primera",
                limit_assessment="historico aparentemente agotado",
            )

        if request_index + 1 < max_pages and pause_seconds:
            sleeper(pause_seconds)

    return _result(
        page_size=page_size,
        requests_made=requests_made,
        pages_with_data=pages_with_data,
        seen_trip_ids=seen_trip_ids,
        duplicate_trip_count=duplicate_trip_count,
        overlap_page_count=overlap_page_count,
        transient_retry_count=transient_retry_count,
        missing_trip_id_count=missing_trip_id_count,
        oldest=oldest,
        newest=newest,
        stop_reason="safety_limit",
        stop_detail=f"se alcanzo el maximo de seguridad de {max_pages} paginas",
        limit_assessment="indeterminado; se alcanzo el limite local del diagnostico",
    )


def format_safe_report(result: PaginationResult) -> str:
    lines = [
        f"Mecanismo de paginacion: {PAGINATION_MECHANISM}",
        f"Tamano de pagina observado: {result.page_size}",
        f"Peticiones realizadas: {result.requests_made}",
        f"Paginas con datos recuperadas: {result.pages_with_data}",
        f"Viajes unicos totales accesibles: {result.unique_trip_count}",
        f"Duplicados o solapes detectados: {result.duplicate_trip_count}",
        f"Paginas con solape: {result.overlap_page_count}",
        f"Reintentos por cierre TLS transitorio: {result.transient_retry_count}",
        f"Viajes sin trip_id utilizable: {result.missing_trip_id_count}",
        f"Viaje mas antiguo aproximado: {result.oldest_month or 'no disponible'}",
        f"Viaje mas reciente aproximado: {result.newest_month or 'no disponible'}",
        f"Condicion de parada: {result.stop_reason} - {result.stop_detail}",
        f"Evaluacion del limite: {result.limit_assessment}",
    ]
    if result.error_status is not None:
        lines.append(f"HTTP al detenerse: {result.error_status}")
    if result.error_api_code is not None:
        lines.append(f"Codigo API al detenerse: {result.error_api_code}")
    if result.error_type is not None:
        lines.append(f"Tipo de error al detenerse: {result.error_type}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        email = input("Email: ").strip()
        password = getpass.getpass("Contrasena: ")
        technical_config = load_technical_config()
        device_id = get_or_create_generated_device_id()
        if not email or not password:
            raise ValueError("Missing required local input")

        login_result = login_or_reuse(
            email=email,
            password=password,
            pass_key=technical_config.pass_key,
            x_client_id=technical_config.x_client_id,
            device_id=device_id,
            login_device_model=build_login_device_model(
                DEFAULT_DEVICE_MODEL,
                DEFAULT_ANDROID_VERSION,
            ),
        )
        nif = fetch_userdata_dn(
            access_token=login_result.access_token,
            email=email,
            user_id=login_result.user_id,
            device_id=device_id,
            device_model=DEFAULT_DEVICE_MODEL,
        )

        def fetch_page(page: int | None) -> JsonResponse:
            return fetch_trips(
                access_token=login_result.access_token,
                email=email,
                user_id=login_result.user_id,
                nif=nif,
                device_id=device_id,
                device_model=DEFAULT_DEVICE_MODEL,
                page=page,
            )

        result = paginate_trip_history(
            fetch_page,
            max_pages=args.max_pages,
            pause_seconds=args.pause_seconds,
            transient_retries=args.transient_retries,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        print(format_safe_report(result))
        return 1 if result.stop_reason in {"backend_error", "invalid_response"} else 0
    except InvalidLocalDeviceIdError:
        print("El deviceId local tiene un formato invalido")
    except MissingLocalTechnicalConfigError:
        print("Falta la configuracion tecnica local.")
        print("Ejecuta:")
        print("python tools/bicimad_probe/configure_local_probe.py")
    except ProbeRequestError as error:
        print(f"Etapa fallida: {error.stage}")
        print(f"HTTP {error.status if error.status is not None else '-'}")
        if error.api_code is not None:
            print(f"Codigo de API: {error.api_code}")
        print(f"Tipo de excepcion: {error.error_type}")
    except (OSError, ValueError) as error:
        print("Etapa fallida: entrada")
        print(f"Tipo de excepcion: {type(error).__name__}")
    return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnostica la paginacion de viajes BiciMAD sin guardar datos.",
    )
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=DEFAULT_PAUSE_SECONDS,
    )
    parser.add_argument(
        "--transient-retries",
        type=int,
        default=DEFAULT_TRANSIENT_RETRIES,
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=DEFAULT_RETRY_DELAY_SECONDS,
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_pages <= 1000:
        parser.error("--max-pages debe estar entre 1 y 1000")
    if not 0 <= args.pause_seconds <= 5:
        parser.error("--pause-seconds debe estar entre 0 y 5")
    if not 0 <= args.transient_retries <= 3:
        parser.error("--transient-retries debe estar entre 0 y 3")
    if not 0 <= args.retry_delay_seconds <= 10:
        parser.error("--retry-delay-seconds debe estar entre 0 y 10")
    return args


def _extract_trip_date(trip: dict[str, Any]) -> datetime | None:
    undock = trip.get("undock")
    if not isinstance(undock, dict):
        return None
    value = undock.get("undock_ts")
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).replace(tzinfo=None)
    except ValueError:
        return None


def _has_explicit_end(payload: dict[str, Any]) -> bool:
    def inspect(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        for key, child in value.items():
            normalized = "".join(
                character for character in key.lower() if character.isalnum()
            )
            if normalized in {"hasmore", "moreavailable"} and child is False:
                return True
            if normalized in {"end", "islast", "lastpage"} and child is True:
                return True
            if normalized in {"next", "nextpage", "nextcursor"} and child is None:
                return True
            if key != "data" and inspect(child):
                return True
        return False

    return inspect(payload)


def _result(
    *,
    page_size: int,
    requests_made: int,
    pages_with_data: int,
    seen_trip_ids: set[str],
    duplicate_trip_count: int,
    overlap_page_count: int,
    transient_retry_count: int,
    missing_trip_id_count: int,
    oldest: datetime | None,
    newest: datetime | None,
    stop_reason: str,
    stop_detail: str,
    limit_assessment: str,
    error: ProbeRequestError | None = None,
) -> PaginationResult:
    return PaginationResult(
        page_size=page_size,
        requests_made=requests_made,
        pages_with_data=pages_with_data,
        unique_trip_count=len(seen_trip_ids),
        duplicate_trip_count=duplicate_trip_count,
        overlap_page_count=overlap_page_count,
        transient_retry_count=transient_retry_count,
        missing_trip_id_count=missing_trip_id_count,
        oldest_month=_month(oldest),
        newest_month=_month(newest),
        stop_reason=stop_reason,
        stop_detail=stop_detail,
        limit_assessment=limit_assessment,
        error_status=error.status if error else None,
        error_api_code=error.api_code if error else None,
        error_type=error.error_type if error else None,
    )


def _month(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m") if value is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
