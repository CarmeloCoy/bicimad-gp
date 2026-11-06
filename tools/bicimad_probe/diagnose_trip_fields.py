#!/usr/bin/env python3
"""Inspect bike and price field shapes without exposing trip data.

The response is kept in memory only. Output contains field paths, aggregate
types, sanitized shape descriptions and coverage percentages.
"""

from __future__ import annotations

import getpass
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fetch_trips_with_login import (
    DEFAULT_ANDROID_VERSION,
    DEFAULT_DEVICE_MODEL,
    InvalidLocalDeviceIdError,
    get_or_create_generated_device_id,
)
from local_secrets import MissingLocalTechnicalConfigError, load_technical_config
from mpass_client import (
    ProbeRequestError,
    build_login_device_model,
    fetch_trips,
    fetch_userdata_dn,
    login_or_reuse,
)

BIKE_TERMS = {"bike", "bicycle", "bicicleta", "vehicle", "vehiculo"}
PRICE_TERMS = {
    "amount",
    "charge",
    "cost",
    "coste",
    "currency",
    "fare",
    "importe",
    "moneda",
    "payment",
    "precio",
    "price",
    "rate",
    "tariff",
    "tarifa",
}
FORBIDDEN_VALUE_FRAGMENTS = (
    "private-trip",
    "private-bike",
    "private station",
)


@dataclass(frozen=True)
class FieldSummary:
    path: str
    category: str
    types: tuple[str, ...]
    examples: tuple[str, ...]
    present_count: int
    non_null_count: int
    total_trips: int
    with_source_trip_id_count: int

    @property
    def present_percent(self) -> float:
        return _percentage(self.present_count, self.total_trips)

    @property
    def non_null_percent(self) -> float:
        return _percentage(self.non_null_count, self.total_trips)

    @property
    def source_trip_percent(self) -> float:
        return _percentage(self.with_source_trip_id_count, self.present_count)


def analyze_trip_fields(
    payload: dict[str, Any],
) -> tuple[list[FieldSummary], tuple[str, ...]]:
    data = payload.get("data")
    trips = (
        [item for item in data if isinstance(item, dict)]
        if isinstance(data, list)
        else []
    )
    observations: dict[str, list[tuple[Any, bool]]] = defaultdict(list)
    categories: dict[str, str] = {}

    for trip in trips:
        has_source_trip_id = "trip_id" in trip and trip.get("trip_id") is not None
        for path, value, category in _relevant_fields(trip):
            observations[path].append((value, has_source_trip_id))
            categories[path] = category

    summaries = []
    for path in sorted(observations):
        values = observations[path]
        non_null = [value for value, _ in values if value is not None]
        summaries.append(
            FieldSummary(
                path=path,
                category=categories[path],
                types=tuple(sorted({_type_name(value) for value, _ in values})),
                examples=tuple(sorted({_sanitized_shape(value) for value in non_null})),
                present_count=len(values),
                non_null_count=len(non_null),
                total_trips=len(trips),
                with_source_trip_id_count=sum(1 for _, has_id in values if has_id),
            )
        )

    currencies = tuple(sorted(_declared_currencies(observations)))
    return summaries, currencies


def format_safe_report(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    trip_count = (
        sum(1 for item in data if isinstance(item, dict))
        if isinstance(data, list)
        else 0
    )
    summaries, currencies = analyze_trip_fields(payload)
    lines = [f"Viajes analizados: {trip_count}"]
    if not summaries:
        lines.append("Campos candidatos de bicicleta o precio: ninguno")
    else:
        lines.append("Campos candidatos de bicicleta o precio:")
        for summary in summaries:
            examples = (
                ", ".join(summary.examples)
                if summary.examples
                else "<SIN_EJEMPLO_NO_NULO>"
            )
            lines.append(
                f"- {summary.path} | categoria={summary.category} "
                f"| tipos={','.join(summary.types)} | formato={examples} "
                f"| presente={summary.present_percent:.1f}% "
                f"| no_nulo={summary.non_null_percent:.1f}% "
                f"| junto_a_trip_id={summary.source_trip_percent:.1f}%"
            )
    lines.append(
        "Unidad monetaria declarada: "
        + (", ".join(currencies) if currencies else "no declarada")
    )
    report = "\n".join(lines)
    _assert_safe_report(report)
    return report


def main() -> int:
    try:
        email = input("Email: ").strip()
        password = getpass.getpass("Contraseña: ")
        technical_config = load_technical_config()
        device_id = get_or_create_generated_device_id()
        if not email or not password:
            raise ValueError("Missing input")

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
        response = fetch_trips(
            access_token=login_result.access_token,
            email=email,
            user_id=login_result.user_id,
            nif=nif,
            device_id=device_id,
            device_model=DEFAULT_DEVICE_MODEL,
        )
        print(format_safe_report(response.payload))
        return 0
    except InvalidLocalDeviceIdError:
        print("El deviceId local tiene un formato inválido")
    except MissingLocalTechnicalConfigError:
        print("Falta la configuración técnica local.")
        print("Ejecuta:")
        print("python tools/bicimad_probe/configure_local_probe.py")
    except ProbeRequestError as error:
        print(f"Etapa fallida: {error.stage}")
        print(f"HTTP {error.status if error.status is not None else '-'}")
        if error.api_code is not None:
            print(f"Código de API: {error.api_code}")
        print(f"Tipo de excepción: {error.error_type}")
    except (OSError, ValueError) as error:
        print("Etapa fallida: entrada")
        print(f"Tipo de excepción: {type(error).__name__}")
    return 1


def _relevant_fields(value: dict[str, Any]) -> list[tuple[str, Any, str]]:
    found: list[tuple[str, Any, str]] = []

    def visit(
        current: Any,
        path: tuple[str, ...],
        inherited: str | None = None,
    ) -> None:
        if not isinstance(current, dict):
            return
        for key, child in current.items():
            next_path = (*path, key)
            key_lower = key.lower()
            key_terms = set(re.findall(r"[a-z]+", key_lower))
            category = inherited
            if key_terms & BIKE_TERMS or any(term in key_lower for term in BIKE_TERMS):
                category = "bike"
            elif key_terms & PRICE_TERMS or any(
                term in key_lower for term in PRICE_TERMS
            ):
                category = "price"
            if category is not None:
                found.append((".".join(next_path), child, category))
            if isinstance(child, dict):
                visit(child, next_path, category)

    visit(value, ())
    return found


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "other"


def _sanitized_shape(value: Any) -> str:
    if isinstance(value, bool):
        return "<BOOLEAN>"
    if isinstance(value, int):
        return "<INTEGER>"
    if isinstance(value, float):
        decimals = len(str(value).partition(".")[2])
        return f"<DECIMAL_{decimals}_PLACES>"
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", stripped):
            return "<UUID>"
        if re.fullmatch(r"\d+", stripped):
            return f"<NUMERIC_STRING_LENGTH_{len(stripped)}>"
        if re.fullmatch(r"[A-Za-z0-9_-]+", stripped):
            return f"<ALPHANUMERIC_STRING_LENGTH_{len(stripped)}>"
        if "€" in stripped or re.search(r"\bEUR\b", stripped, re.IGNORECASE):
            return "<MONEY_STRING_EUR>"
        return f"<STRING_LENGTH_{len(stripped)}>"
    if isinstance(value, dict):
        return "<OBJECT>"
    if isinstance(value, list):
        return "<ARRAY>"
    return "<OTHER>"


def _declared_currencies(
    observations: dict[str, list[tuple[Any, bool]]],
) -> set[str]:
    result = set()
    for path, values in observations.items():
        if not any(term in path.lower() for term in ("currency", "moneda")):
            continue
        for value, _ in values:
            if isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value.strip()):
                result.add(value.strip())
    return result


def _percentage(value: int, total: int) -> float:
    return 0.0 if total == 0 else value / total * 100


def _assert_safe_report(report: str) -> None:
    lowered = report.lower()
    if any(fragment in lowered for fragment in FORBIDDEN_VALUE_FRAGMENTS):
        raise ValueError("Unsafe diagnostic output")


if __name__ == "__main__":
    raise SystemExit(main())
