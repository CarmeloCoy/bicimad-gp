import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_trips
import fetch_trips_with_login
from mpass_client import ProbeRequestError
from safe_output import safe_api_code


class SafeOutputTest(unittest.TestCase):
    def test_api_code_is_allowlisted(self):
        self.assertEqual(safe_api_code("00"), "00")
        for value in (
            None,
            {},
            12345678,
            "fake@example.com",
            "00\nprivate",
            "12345678",
        ):
            self.assertIsNone(safe_api_code(value))

    def test_summaries_do_not_echo_response_fields_or_trips(self):
        private = "fake-private-do-not-log"
        payload = {"code": private, "description": private, "data": [private]}
        trips = [{"started_at": private, "origin_station_name": private}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            fetch_trips._print_success_summary(200, payload, trips)
            fetch_trips._print_error_summary(
                status=400, error_type="HTTPError", payload=payload
            )
            error = ProbeRequestError(
                stage="login",
                status=400,
                api_code=private,
                api_description=private,
                error_type="HTTPError",
            )
            fetch_trips_with_login._print_safe_error(error)
        self.assertNotIn(private, output.getvalue())
        self.assertIn("Viajes normalizados: 1", output.getvalue())
        self.assertIsNone(error.api_description)


if __name__ == "__main__":
    unittest.main()
