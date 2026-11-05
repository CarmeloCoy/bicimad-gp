from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnose_trip_fields import analyze_trip_fields, format_safe_report


class DiagnoseTripFieldsTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "code": "00",
            "data": [
                {
                    "trip_id": "private-trip-one",
                    "id_bike": "private-bike-123",
                    "payment": {"amount": 1.25, "currency": "EUR"},
                    "undock": {
                        "undock_station_name": "Private station",
                        "undock_ts": "2026-08-01T10:00:00",
                    },
                },
                {
                    "trip_id": "private-trip-two",
                    "id_bike": None,
                    "payment": {"amount": 0},
                },
                {"trip_id": "private-trip-three"},
            ],
        }

    def test_reports_types_shapes_and_coverage_without_values(self):
        summaries, currencies = analyze_trip_fields(self.payload)
        by_path = {summary.path: summary for summary in summaries}

        self.assertEqual(by_path["id_bike"].category, "bike")
        self.assertAlmostEqual(by_path["id_bike"].present_percent, 200 / 3)
        self.assertAlmostEqual(by_path["id_bike"].non_null_percent, 100 / 3)
        self.assertIn("string", by_path["id_bike"].types)
        self.assertEqual(by_path["payment.amount"].category, "price")
        self.assertIn("decimal", by_path["payment.amount"].types)
        self.assertEqual(currencies, ("EUR",))

        report = format_safe_report(self.payload)
        self.assertNotIn("private-trip", report)
        self.assertNotIn("private-bike", report)
        self.assertNotIn("Private station", report)
        self.assertIn("id_bike", report)
        self.assertIn("payment.amount", report)
        self.assertIn("Unidad monetaria declarada: EUR", report)

    def test_printed_report_never_contains_private_values(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print(format_safe_report(self.payload))
        rendered = output.getvalue()
        for secret in (
            "private-trip-one",
            "private-bike-123",
            "Private station",
            "2026-08-01",
        ):
            self.assertNotIn(secret, rendered)

    def test_empty_response_is_safe(self):
        report = format_safe_report({"code": "00", "data": []})
        self.assertIn("Viajes analizados: 0", report)
        self.assertIn("campos candidatos", report.lower())


if __name__ == "__main__":
    unittest.main()
