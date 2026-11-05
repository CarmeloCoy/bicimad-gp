from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalize import OUTPUT_FIELDS, normalize_response

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "trips_response_fake.json"


class NormalizeTripsTests(unittest.TestCase):
    def test_normalizes_only_allowed_fields(self) -> None:
        payload = _load_fixture()

        normalized = normalize_response(payload)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(set(normalized[0].keys()), OUTPUT_FIELDS)
        self.assertEqual(normalized[0]["external_id"], "fake-trip-001")
        self.assertEqual(normalized[0]["origin_station_number"], "90")
        self.assertEqual(normalized[0]["origin_station_name"], "Manuel Becerra")
        self.assertEqual(normalized[0]["destination_station_number"], "101")
        self.assertEqual(normalized[0]["destination_station_name"], "Felipe II")
        self.assertEqual(normalized[0]["started_at"], "2026-07-31T08:16:00+02:00")
        self.assertEqual(normalized[0]["ended_at"], "2026-07-31T08:22:48+02:00")
        self.assertEqual(normalized[0]["duration_minutes"], 6.8)
        self.assertEqual(normalized[0]["duration_text"], "00:06:48")

    def test_ignores_sensitive_and_financial_fields(self) -> None:
        payload = _load_fixture()

        normalized = normalize_response(payload)
        serialized = json.dumps(normalized)

        self.assertNotIn("userId", serialized)
        self.assertNotIn("payment", serialized)
        self.assertNotIn("locator", serialized)
        self.assertNotIn("id_bike", serialized)
        self.assertNotIn("contractCode", serialized)
        self.assertNotIn("serialNumber", serialized)
        self.assertNotIn("penalty", serialized)
        self.assertNotIn("latitude", serialized)
        self.assertNotIn("longitude", serialized)
        self.assertNotIn("fake-user-should-not-leak", serialized)
        self.assertNotIn("4111111111111111", serialized)
        self.assertNotIn("fake-bike-001", serialized)
        self.assertNotIn("fake-locator-001", serialized)

    def test_empty_station_names_become_null_without_dropping_trip(self) -> None:
        payload = _load_fixture()

        normalized = normalize_response(payload)

        self.assertEqual(normalized[1]["origin_station_number"], "49")
        self.assertIsNone(normalized[1]["origin_station_name"])
        self.assertEqual(normalized[1]["destination_station_name"], "Puerta del Sol")

    def test_does_not_modify_original_response(self) -> None:
        payload = _load_fixture()
        original = copy.deepcopy(payload)

        normalize_response(payload)

        self.assertEqual(payload, original)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
