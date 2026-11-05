#!/usr/bin/env python3
"""Normalize EMT OpenAPI BiciMAD station responses."""

from __future__ import annotations

import math
from typing import Any

OUTPUT_FIELDS = {
    "id",
    "number",
    "name",
    "address",
    "latitude",
    "longitude",
    "activate",
    "dock_bikes",
    "free_bases",
    "geofenced_capacity",
    "light",
    "no_available",
    "reservations_count",
    "tipo_estacionPBSC",
    "total_bases",
    "virtualDelete",
    "lightNoOnTrip",
    "overflow",
}

_OPTIONAL_FIELDS = (
    "activate",
    "dock_bikes",
    "free_bases",
    "geofenced_capacity",
    "light",
    "no_available",
    "reservations_count",
    "tipo_estacionPBSC",
    "total_bases",
    "virtualDelete",
    "lightNoOnTrip",
    "overflow",
)


def normalize_stations_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract station catalog and availability fields, excluding raw extras."""
    stations = payload.get("data")
    if not isinstance(stations, list):
        raise TypeError("Invalid stations response: data must be a list")

    normalized = []
    for item in stations:
        if not isinstance(item, dict):
            continue

        station_id = _identifier(item.get("id"))
        number = _identifier(item.get("number"))
        name = _text(item.get("name"))
        coordinates = _point_coordinates(item.get("geometry"))
        if station_id is None or number is None or name is None or coordinates is None:
            continue

        station = {
            "id": station_id,
            "number": number,
            "name": name,
            "address": _text(item.get("address")),
            "latitude": coordinates[1],
            "longitude": coordinates[0],
        }
        station.update({field: item.get(field) for field in _OPTIONAL_FIELDS})
        normalized.append(station)

    return normalized


def _identifier(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value).strip()
    return text or None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _point_coordinates(geometry: Any) -> tuple[int | float, int | float] | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    longitude, latitude = coordinates[:2]
    if (
        isinstance(longitude, bool)
        or not isinstance(longitude, (int, float))
        or not math.isfinite(longitude)
        or isinstance(latitude, bool)
        or not isinstance(latitude, (int, float))
        or not math.isfinite(latitude)
    ):
        return None
    return longitude, latitude
