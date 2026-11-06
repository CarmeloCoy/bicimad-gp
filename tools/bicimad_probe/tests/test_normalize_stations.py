from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalize_stations import OUTPUT_FIELDS, normalize_stations_response


class NormalizeStationsTests(unittest.TestCase):
    def test_normalizes_station_and_geojson_coordinates(self) -> None:
        payload = {
            "code": "00",
            "data": [
                {
                    "id": 1409,
                    "number": "5",
                    "name": "5 - Fuencarral",
                    "address": "Calle Fuencarral, 106 ",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-3.7021354, 40.4285212],
                    },
                    "dock_bikes": 0,
                    "free_bases": 21,
                    "total_bases": 27,
                    "activate": 1,
                    "overflow": False,
                    "image": "ignored image",
                    "bikesGo": ["ignored bike data"],
                }
            ],
        }
        original = copy.deepcopy(payload)

        stations = normalize_stations_response(payload)

        self.assertEqual(len(stations), 1)
        station = stations[0]
        self.assertEqual(set(station), OUTPUT_FIELDS)
        self.assertEqual(station["id"], "1409")
        self.assertEqual(station["number"], "5")
        self.assertEqual(station["name"], "5 - Fuencarral")
        self.assertEqual(station["address"], "Calle Fuencarral, 106")
        self.assertEqual(station["longitude"], -3.7021354)
        self.assertEqual(station["latitude"], 40.4285212)
        self.assertEqual(station["dock_bikes"], 0)
        self.assertFalse(station["overflow"])
        self.assertNotIn("image", station)
        self.assertNotIn("bikesGo", station)
        self.assertEqual(payload, original)

    def test_skips_entries_without_station_identity_or_point_coordinates(self) -> None:
        payload = {
            "data": [
                {"id": 1, "number": "1", "name": "No geometry"},
                {
                    "id": 2,
                    "number": "2",
                    "name": "Invalid coordinates",
                    "geometry": {"type": "Point", "coordinates": ["-3.7", 40.4]},
                },
                {
                    "id": 3,
                    "number": "3",
                    "name": "Valid",
                    "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                },
            ]
        }

        stations = normalize_stations_response(payload)

        self.assertEqual([station["id"] for station in stations], ["3"])

    def test_requires_data_list(self) -> None:
        with self.assertRaisesRegex(TypeError, "data must be a list"):
            normalize_stations_response({"data": {}})


if __name__ == "__main__":
    unittest.main()
