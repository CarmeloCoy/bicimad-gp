from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_stations


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status = status
        self.payload = payload or {"code": "00", "data": []}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FetchStationsTests(unittest.TestCase):
    def test_main_prompts_only_for_account_email_and_password(self) -> None:
        stdout = io.StringIO()
        with (
            patch("builtins.input", side_effect=["person@example.test"]) as input_mock,
            patch("getpass.getpass", side_effect=["fake-password"]) as password_mock,
            patch("fetch_stations._login", return_value="private-token") as login_mock,
            patch(
                "fetch_stations._fetch_stations",
                return_value=(200, {"code": "00", "data": []}),
            ) as fetch_mock,
            patch("fetch_stations._write_raw_response"),
            patch("fetch_stations._write_stations"),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_stations.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            input_mock.call_args_list,
            [call("Usuario/email EMT OpenAPI: ")],
        )
        self.assertEqual(
            password_mock.call_args_list,
            [call("Contraseña: ")],
        )
        self.assertEqual(
            login_mock.call_args.args,
            ("person@example.test", "fake-password"),
        )
        self.assertEqual(fetch_mock.call_args.args, ("private-token",))
        self.assertNotIn("private-token", stdout.getvalue())

    def test_openapi_login_sends_credentials_as_headers_and_extracts_token(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "code": "00",
                    "description": "contains private account data",
                    "data": [{"accessToken": "private-token"}],
                }
            )

        token = fetch_stations._login(
            "person@example.test",
            "private-password",
            opener=opener,
        )

        request = captured["request"]
        self.assertEqual(token, "private-token")
        self.assertEqual(request.full_url, fetch_stations.LOGIN_ENDPOINT)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Email"), "person@example.test")
        self.assertEqual(request.get_header("Password"), "private-password")
        self.assertEqual(captured["timeout"], fetch_stations.TIMEOUT_SECONDS)

    def test_fetch_uses_endpoint_access_token_and_read_only_get(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        status, payload = fetch_stations._fetch_stations(
            "local-token-do-not-print", opener=opener
        )

        request = captured["request"]
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"code": "00", "data": []})
        self.assertEqual(request.full_url, fetch_stations.ENDPOINT)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Accesstoken"), "local-token-do-not-print")
        self.assertEqual(captured["timeout"], fetch_stations.TIMEOUT_SECONDS)

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
