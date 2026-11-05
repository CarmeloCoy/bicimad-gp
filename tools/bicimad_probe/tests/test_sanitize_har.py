from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sanitize_har import main, sanitize_har


class SanitizeHarTests(unittest.TestCase):
    def test_redacts_sensitive_values_and_preserves_structure(self) -> None:
        har = _fake_har()

        sanitized = sanitize_har(har)
        serialized = json.dumps(sanitized)

        self.assertNotIn("Bearer original-access-token", serialized)
        self.assertNotIn("super-secret-password", serialized)
        self.assertNotIn("session-cookie-value", serialized)
        self.assertNotIn("pablo@example.com", serialized)
        self.assertNotIn("PabloUser", serialized)
        self.assertNotIn("600123456", serialized)
        self.assertNotIn("12345678Z", serialized)
        self.assertIn("<REDACTED_TOKEN>", serialized)
        self.assertIn("<REDACTED_PASSWORD>", serialized)
        self.assertIn("<REDACTED_COOKIE>", serialized)
        self.assertIn("<REDACTED_PERSONAL_DATA>", serialized)

        entry = sanitized["log"]["entries"][0]
        self.assertEqual(entry["request"]["method"], "POST")
        self.assertIn("/auth/login", entry["request"]["url"])
        self.assertEqual(entry["response"]["status"], 200)
        self.assertEqual(
            entry["request"]["postData"]["params"][0]["name"],
            "username",
        )

    def test_sanitizes_serialized_json_inside_text_fields(self) -> None:
        sanitized = sanitize_har(_fake_har())
        text = sanitized["log"]["entries"][0]["request"]["postData"]["text"]
        decoded = json.loads(text)

        self.assertEqual(decoded["password"], "<REDACTED_PASSWORD>")
        self.assertEqual(decoded["email"], "<REDACTED_PERSONAL_DATA>")
        self.assertEqual(decoded["token"], "<REDACTED_TOKEN>")
        self.assertEqual(decoded["profile"]["dni"], "<REDACTED_PERSONAL_DATA>")

    def test_cli_fails_clearly_for_invalid_har(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "invalid.har"
            output_path = Path(directory) / "out.sanitized.har"
            input_path.write_text('{"notLog": true}', encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["sanitize_har.py", str(input_path), str(output_path)])

            self.assertEqual(exit_code, 1)
            self.assertFalse(output_path.exists())
            self.assertNotIn("super-secret-password", stderr.getvalue())


def _fake_har() -> dict:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "unit-test", "version": "1"},
            "entries": [
                {
                    "startedDateTime": "2026-08-01T10:00:00.000Z",
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.test/auth/login?access_token=query-token&email=pablo@example.com&page=1",
                        "headers": [
                            {
                                "name": "Authorization",
                                "value": "Bearer original-access-token",
                            },
                            {"name": "Content-Type", "value": "application/json"},
                            {"name": "Cookie", "value": "sid=session-cookie-value"},
                        ],
                        "cookies": [
                            {"name": "sid", "value": "session-cookie-value"},
                        ],
                        "queryString": [
                            {"name": "access_token", "value": "query-token"},
                            {"name": "email", "value": "pablo@example.com"},
                            {"name": "page", "value": "1"},
                        ],
                        "postData": {
                            "mimeType": "application/json",
                            "params": [
                                {"name": "username", "value": "PabloUser"},
                                {
                                    "name": "password",
                                    "value": "super-secret-password",
                                },
                            ],
                            "text": json.dumps(
                                {
                                    "username": "PabloUser",
                                    "password": "super-secret-password",
                                    "email": "pablo@example.com",
                                    "phone": "600123456",
                                    "token": "abc.def.ghi",
                                    "profile": {"dni": "12345678Z"},
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"},
                            {
                                "name": "Set-Cookie",
                                "value": "refresh=server-cookie-value",
                            },
                        ],
                        "cookies": [
                            {"name": "refresh", "value": "server-cookie-value"},
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "access_token": "server-token",
                                    "refresh_token": "server-refresh",
                                    "customer": {"email": "pablo@example.com"},
                                }
                            ),
                        },
                    },
                }
            ],
        }
    }


if __name__ == "__main__":
    unittest.main()
