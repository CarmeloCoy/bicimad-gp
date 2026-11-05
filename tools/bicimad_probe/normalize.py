#!/usr/bin/env python3
"""Normalize BiciMAD trips responses into the MVP trip shape.

Only read-only trip fields needed by the local proof of concept are preserved.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

OUTPUT_FIELDS = {
    "external_id",
    "origin_station_number",
    "origin_station_name",
    "destination_station_number",
    "destination_station_name",
    "started_at",
    "ended_at",
    "duration_minutes",
    "duration_text",
}


def normalize_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized trips without mutating the original response."""
    source = deepcopy(payload)
    trips = source.get("data")
    if trips is None:
        return []
    if not isinstance(trips, list):
        raise TypeError("Invalid trips response: data must be a list")

    normalized = []
    for item in trips:
        if not isinstance(item, dict):
            continue

        undock = item.get("undock")
        dock = item.get("dock")
        undock = undock if isinstance(undock, dict) else {}
        dock = dock if isinstance(dock, dict) else {}

        normalized.append(
            {
                "external_id": item.get("trip_id"),
                "origin_station_number": undock.get("undock_station_number"),
                "origin_station_name": _nullable_station_name(
                    undock.get("undock_station_name")
                ),
                "destination_station_number": dock.get("dock_station_number"),
                "destination_station_name": _nullable_station_name(
                    dock.get("dock_station_name")
                ),
                "started_at": undock.get("undock_ts"),
                "ended_at": dock.get("dock_ts"),
                "duration_minutes": item.get("trip_minutes"),
                "duration_text": item.get("trip_interval"),
            }
        )

    return normalized


def _nullable_station_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
