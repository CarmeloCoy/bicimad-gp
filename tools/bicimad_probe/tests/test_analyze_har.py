from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze_har import analyze_har, main, render_text_report


class AnalyzeHarTests(unittest.TestCase):
    def test_detects_login_history_and_pagination(self) -> None:
        report = analyze_har(_sanitized_har())
        entries = report["relevant_entries"]

        login = entries[0]
        history = entries[1]

        self.assertIn("posible login", login["classification"])
        self.assertIn("posible historial", history["classification"])
        self.assertIn("page", history["pagination_indicators"])
        self.assertIn("limit", history["pagination_indicators"])
        self.assertIn("hasMore", history["pagination_indicators"])
        self.assertIn("trips", history["response_json_fields"])

    def test_report_contains_names_but_no_secret_values(self) -> None:
        report = analyze_har(_sanitized_har())
        text = render_text_report(report)
        serialized = json.dumps(report)

        combined = text + serialized
        self.assertIn("Authorization", combined)
        self.assertIn("access_token", combined)
        self.assertNotIn("raw-secret-token", combined)
        self.assertNotIn("raw-password", combined)
        self.assertNotIn("sid=raw-cookie", combined)
        self.assertNotIn("pablo@example.com", combined)

    def test_cli_accepts_only_sanitized_har_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            input_path = workdir / "capture.sanitized.har"
            input_path.write_text(
                json.dumps(_sanitized_har()),
                encoding="utf-8",
            )

            previous = Path.cwd()
            try:
                import os

                os.chdir(workdir)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = main(["analyze_har.py", str(input_path)])
                self.assertEqual(exit_code, 0)
                self.assertTrue((workdir / "bicimad_probe_report.txt").exists())
                self.assertTrue((workdir / "bicimad_probe_report.json").exists())
                self.assertNotIn("raw-secret-token", stderr.getvalue())
            finally:
                os.chdir(previous)

    def test_cli_refuses_non_sanitized_extension(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["analyze_har.py", "capture.har"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Refusing", stderr.getvalue())

    def test_cli_refuses_obvious_unsanitized_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "capture.sanitized.har"
            raw_har = _sanitized_har()
            raw_har["log"]["entries"][0]["request"]["headers"][0]["value"] = (
                "Bearer raw-secret-token"
            )
            input_path.write_text(json.dumps(raw_har), encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["analyze_har.py", str(input_path)])

            self.assertEqual(exit_code, 1)
            self.assertNotIn("raw-secret-token", stderr.getvalue())


def _sanitized_har() -> dict:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "unit-test", "version": "1"},
            "entries": [
                {
                    "startedDateTime": "2026-08-01T10:00:00.000Z",
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.test/auth/login",
                        "headers": [
                            {"name": "Authorization", "value": "<REDACTED_TOKEN>"},
                            {"name": "Content-Type", "value": "application/json"},
                        ],
                        "queryString": [],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "username": "<REDACTED_PERSONAL_DATA>",
                                    "password": "<REDACTED_PASSWORD>",
                                    "access_token": "<REDACTED_TOKEN>",
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"}
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "access_token": "<REDACTED_TOKEN>",
                                    "user": {"id": "mock-user-id"},
                                }
                            ),
                        },
                    },
                },
                {
                    "startedDateTime": "2026-08-01T10:02:00.000Z",
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.test/user/trips/history?page=1&limit=20",
                        "headers": [
                            {"name": "Authorization", "value": "<REDACTED_TOKEN>"},
                            {"name": "Accept", "value": "application/json"},
                        ],
                        "queryString": [
                            {"name": "page", "value": "1"},
                            {"name": "limit", "value": "20"},
                        ],
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"}
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "trips": [
                                        {
                                            "origin": "A",
                                            "destination": "B",
                                            "duration": 420,
                                        }
                                    ],
                                    "page": 1,
                                    "limit": 20,
                                    "hasMore": False,
                                }
                            ),
                        },
                    },
                },
            ],
        }
    }


if __name__ == "__main__":
    unittest.main()
