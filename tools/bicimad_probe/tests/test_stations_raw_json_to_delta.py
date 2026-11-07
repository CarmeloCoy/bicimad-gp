from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stations_raw_json_to_delta as importer


class StationsRawJsonToDeltaTests(unittest.TestCase):
    def test_import_snapshot_normalizes_raw_response_before_delta_write(self) -> None:
        payload = {
            "code": "00",
            "data": [
                {
                    "id": 1409,
                    "number": "5",
                    "name": "5 - Fuencarral",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-3.7021354, 40.4285212],
                    },
                    "dock_bikes": 3,
                    "image": "excluded data",
                }
            ],
        }
        expected_station = {
            "id": "1409",
            "number": "5",
            "name": "5 - Fuencarral",
            "address": None,
            "latitude": 40.4285212,
            "longitude": -3.7021354,
            "activate": None,
            "dock_bikes": 3,
            "free_bases": None,
            "geofenced_capacity": None,
            "light": None,
            "no_available": None,
            "reservations_count": None,
            "tipo_estacionPBSC": None,
            "total_bases": None,
            "virtualDelete": None,
            "lightNoOnTrip": None,
            "overflow": None,
        }

        with tempfile.TemporaryDirectory() as directory:
            json_file = Path(directory) / "stations_raw_20261107_120000.json"
            json_file.write_text(json.dumps(payload), encoding="utf-8")
            delta_path = Path(directory) / "stations_delta"
            with (
                patch.object(importer, "already_imported", return_value=False),
                patch.object(importer.pl, "DataFrame") as dataframe_mock,
            ):
                dataframe = dataframe_mock.return_value
                dataframe.is_empty.return_value = False
                dataframe.height = 1
                dataframe.with_columns.return_value = dataframe

                importer.import_snapshot(json_file, delta_path)

        dataframe_mock.assert_called_once_with(
            [expected_station],
            schema=importer.STATIONS_SCHEMA,
            orient="row",
        )
        dataframe.write_delta.assert_called_once()


if __name__ == "__main__":
    unittest.main()
