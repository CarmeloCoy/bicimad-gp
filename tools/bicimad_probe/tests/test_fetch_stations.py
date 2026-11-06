from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_stations
from mpass_client import JsonResponse, LoginResult


class FetchStationsTests(unittest.TestCase):
    def test_main_uses_shared_mpass_login_inputs_and_fetches_stations(self) -> None:
        values = {
            "email": "person@example.test",
            "password": "fake-password",
            "pass_key": "fake-pass-key",
            "x_client_id": "fake-client-id",
            "device_id": "0123456789abcdef",
            "device_model_visible": "Samsung SM-A127F",
            "android_version": "13",
        }
        payload = {"code": "00", "data": []}
        stations: list[dict[str, object]] = []
        raw_path = fetch_stations.PRIVATE_OUTPUT_DIR / "stations_raw.json"
        normalized_path = fetch_stations.PRIVATE_OUTPUT_DIR / "stations_normalized.json"
        stdout = io.StringIO()

        with (
            patch("fetch_stations._prompt_values", return_value=values) as prompt_mock,
            patch(
                "fetch_stations.login_or_reuse",
                return_value=LoginResult("private-token", "private-user", 3600),
            ) as login_mock,
            patch(
                "fetch_stations._fetch_stations",
                return_value=JsonResponse(200, payload),
            ) as fetch_mock,
            patch("fetch_stations.normalize_stations_response", return_value=stations),
            patch("fetch_stations._write_raw_response") as write_raw_mock,
            patch("fetch_stations._write_stations") as write_stations_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_stations.main([])

        self.assertEqual(exit_code, 0)
        prompt_mock.assert_called_once_with()
        login_mock.assert_called_once_with(
            email="person@example.test",
            password="fake-password",
            pass_key="fake-pass-key",
            x_client_id="fake-client-id",
            device_id="0123456789abcdef",
            login_device_model='{"name":"Samsung SM-A127F","model":"Android","version":"13"}',
        )
        fetch_mock.assert_called_once_with(
            access_token="private-token",
            email="person@example.test",
            user_id="private-user",
            device_id="0123456789abcdef",
            device_model="Samsung SM-A127F",
        )
        write_raw_mock.assert_called_once_with(payload, raw_path)
        write_stations_mock.assert_called_once_with(stations, normalized_path)
        self.assertNotIn("private-token", stdout.getvalue())
        self.assertNotIn("private-user", stdout.getvalue())

    def test_main_reports_missing_local_technical_config(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "fetch_stations._prompt_values",
                side_effect=fetch_stations.MissingLocalTechnicalConfigError(),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_stations.main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("configure_local_probe.py", stdout.getvalue())

    def test_main_reports_partial_account_environment_configuration(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "fetch_stations._prompt_values",
                side_effect=fetch_stations.MissingAccountCredentialsError(),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_stations.main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("BICIMAD_EMT_EMAIL", stdout.getvalue())
        self.assertIn("BICIMAD_EMT_PASSWORD", stdout.getvalue())

    def test_filename_options_reject_paths_and_duplicate_filenames(self) -> None:
        for args in (
            ["--raw-filename", "../outside.json"],
            ["--raw-filename", "same.json", "--normalized-filename", "same.json"],
        ):
            with (
                self.subTest(args=args),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                fetch_stations._parse_args(args)

    def test_summary_does_not_print_station_values_or_description(self) -> None:
        private = "station detail should not be printed"
        output = []
        with patch("builtins.print", side_effect=lambda line: output.append(str(line))):
            fetch_stations._print_success_summary(
                200,
                {"code": "00", "description": private, "data": [{"name": private}]},
                [{"name": private}],
            )

        self.assertNotIn(private, "\n".join(output))
        self.assertIn("Estaciones recibidas: 1", output)
        self.assertIn("Estaciones normalizadas: 1", output)

    def test_writes_raw_response_separately_from_normalized_stations(self) -> None:
        payload = {"code": "00", "description": "original", "data": []}
        with patch.object(fetch_stations, "RAW_OUTPUT_PATH") as raw_path:
            fetch_stations._write_raw_response(payload)

        raw_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        raw_path.write_text.assert_called_once_with(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
