from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Self

import configure_local_probe
import fetch_trips_with_login
from local_secrets import (
    PASS_KEY_ENTRY,
    SERVICE_NAME,
    X_CLIENT_ID_ENTRY,
    MissingLocalTechnicalConfigError,
    TechnicalConfig,
    clear_technical_config,
    load_technical_config,
    save_technical_config,
)
from mpass_client import (
    FlowResult,
    ProbeRequestError,
    build_login_device_model,
    fetch_trips,
    fetch_userdata_dn,
    login,
    run_login_trip_flow,
)


class MPassClientTests(unittest.TestCase):
    def test_login_success(self) -> None:
        opener = FakeOpener([FakeResponse(_login_payload())])

        result = login(
            email="person@example.test",
            password="fake-password",
            pass_key="fake-pass-key",
            x_client_id="fake-client-id",
            device_id="fake-device-id",
            login_device_model=build_login_device_model("Model X", "13"),
            opener=opener,
        )

        self.assertEqual(result.access_token, "fake-access-token")
        self.assertEqual(result.user_id, "fake-user-id")
        self.assertEqual(result.token_sec_expiration, 2592000)
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "email": "person@example.test",
                "passKey": "fake-pass-key",
                "password": "fake-password",
                "X-ClientId": "fake-client-id",
            },
        )
        self.assertNotIn("latitude", request.headers)
        self.assertNotIn("longitude", request.headers)

    def test_login_with_non_success_code_fails_safely(self) -> None:
        opener = FakeOpener(
            [FakeResponse({"code": "99", "description": "login rejected", "data": []})]
        )

        with self.assertRaises(ProbeRequestError) as raised:
            _call_login(opener)

        self.assertEqual(raised.exception.stage, "login")
        self.assertEqual(raised.exception.status, 200)
        self.assertEqual(raised.exception.api_code, "99")
        self.assertEqual(raised.exception.error_type, "ApiError")

    def test_login_without_data_fails_safely(self) -> None:
        opener = FakeOpener([FakeResponse({"code": "00", "description": "ok"})])

        with self.assertRaises(ProbeRequestError) as raised:
            _call_login(opener)

        self.assertEqual(raised.exception.stage, "login")
        self.assertEqual(raised.exception.error_type, "InvalidResponse")

    def test_userdata_extracts_ds_dn(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "00",
                        "description": "ok",
                        "data": {"DS_DN": "fake-dn-format", "DS_NIF": "ignored"},
                    }
                )
            ]
        )

        dn = fetch_userdata_dn(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            device_id="fake-device-id",
            device_model="Model X",
            opener=opener,
        )

        self.assertEqual(dn, "fake-dn-format")

    def test_userdata_accepts_code_01_with_ds_dn(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "01",
                        "description": "El usuario tiene contratos",
                        "data": {"DS_DN": "fake-dn-format", "DS_NIF": "ignored"},
                    }
                )
            ]
        )

        dn = fetch_userdata_dn(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            device_id="fake-device-id",
            device_model="Model X",
            opener=opener,
        )

        self.assertEqual(dn, "fake-dn-format")

    def test_userdata_accepts_code_00_with_ds_dn(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "00",
                        "description": "ok",
                        "data": {"DS_DN": "fake-dn-format"},
                    }
                )
            ]
        )

        dn = fetch_userdata_dn(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            device_id="fake-device-id",
            device_model="Model X",
            opener=opener,
        )

        self.assertEqual(dn, "fake-dn-format")

    def test_userdata_rejects_unexpected_code_safely(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "77",
                        "description": "unexpected fake response",
                        "data": {"DS_DN": "fake-dn-format"},
                    }
                )
            ]
        )

        with self.assertRaises(ProbeRequestError) as raised:
            fetch_userdata_dn(
                access_token="fake-access-token",
                email="person@example.test",
                user_id="fake-user-id",
                device_id="fake-device-id",
                device_model="Model X",
                opener=opener,
            )

        self.assertEqual(raised.exception.stage, "userdata")
        self.assertEqual(raised.exception.status, 200)
        self.assertEqual(raised.exception.api_code, "77")
        self.assertEqual(raised.exception.error_type, "ApiError")

    def test_userdata_without_ds_dn_fails_safely(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "01",
                        "description": "El usuario tiene contratos",
                        "data": {},
                    }
                )
            ]
        )

        with self.assertRaises(ProbeRequestError) as raised:
            fetch_userdata_dn(
                access_token="fake-access-token",
                email="person@example.test",
                user_id="fake-user-id",
                device_id="fake-device-id",
                device_model="Model X",
                opener=opener,
            )

        self.assertEqual(raised.exception.stage, "userdata")
        self.assertEqual(raised.exception.error_type, "MissingRequiredField")

    def test_userdata_requires_data_object(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    {
                        "code": "01",
                        "description": "El usuario tiene contratos",
                        "data": [{"DS_DN": "fake-dn-format"}],
                    }
                )
            ]
        )

        with self.assertRaises(ProbeRequestError) as raised:
            fetch_userdata_dn(
                access_token="fake-access-token",
                email="person@example.test",
                user_id="fake-user-id",
                device_id="fake-device-id",
                device_model="Model X",
                opener=opener,
            )

        self.assertEqual(raised.exception.stage, "userdata")
        self.assertEqual(raised.exception.error_type, "InvalidResponse")

    def test_trips_success(self) -> None:
        trips_payload = _trips_payload()
        opener = FakeOpener([FakeResponse(trips_payload)])

        response = fetch_trips(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            nif="fake-dn-format",
            device_id="fake-device-id",
            device_model="Model X",
            opener=opener,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["code"], "00")
        self.assertEqual(len(response.payload["data"]), 2)

    def test_trips_adds_page_header_only_when_requested(self) -> None:
        opener = FakeOpener(
            [FakeResponse(_trips_payload()), FakeResponse(_trips_payload())]
        )

        fetch_trips(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            nif="fake-dn-format",
            device_id="fake-device-id",
            device_model="Model X",
            opener=opener,
        )
        fetch_trips(
            access_token="fake-access-token",
            email="person@example.test",
            user_id="fake-user-id",
            nif="fake-dn-format",
            device_id="fake-device-id",
            device_model="Model X",
            page=2,
            opener=opener,
        )

        self.assertIsNone(opener.requests[0].get_header("Page"))
        self.assertEqual(opener.requests[1].get_header("Page"), "2")

    def test_http_error_in_each_stage_is_safe(self) -> None:
        cases = [
            ("login", lambda opener: _call_login(opener)),
            (
                "userdata",
                lambda opener: fetch_userdata_dn(
                    access_token="fake-access-token",
                    email="person@example.test",
                    user_id="fake-user-id",
                    device_id="fake-device-id",
                    device_model="Model X",
                    opener=opener,
                ),
            ),
            (
                "trips",
                lambda opener: fetch_trips(
                    access_token="fake-access-token",
                    email="person@example.test",
                    user_id="fake-user-id",
                    nif="fake-dn-format",
                    device_id="fake-device-id",
                    device_model="Model X",
                    opener=opener,
                ),
            ),
        ]

        for stage, action in cases:
            with self.subTest(stage=stage):
                opener = FakeOpener([_http_error(403)])
                with self.assertRaises(ProbeRequestError) as raised:
                    action(opener)
                self.assertEqual(raised.exception.stage, stage)
                self.assertEqual(raised.exception.status, 403)
                self.assertEqual(raised.exception.api_code, "41")
                self.assertEqual(raised.exception.error_type, "HTTPError")
                self.assertNotIn("fake-access-token", str(raised.exception))

    def test_full_flow_writes_only_normalized_json(self) -> None:
        trips_payload = _trips_payload()
        original_trips_payload = copy.deepcopy(trips_payload)
        opener = FakeOpener(
            [
                FakeResponse(_login_payload()),
                FakeResponse(_userdata_payload()),
                FakeResponse(trips_payload),
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "private" / "trips_normalized.json"
            result = run_login_trip_flow(
                email="person@example.test",
                password="fake-password",
                pass_key="fake-pass-key",
                x_client_id="fake-client-id",
                device_id="fake-device-id",
                device_model_visible="Model X",
                android_version="13",
                output_path=output_path,
                opener=opener,
            )

            self.assertEqual(result.received_count, 2)
            self.assertEqual(result.normalized_count, 2)
            files = [path for path in Path(directory).rglob("*") if path.is_file()]
            self.assertEqual(files, [output_path])
            normalized = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(normalized[0].keys()),
                {
                    "external_id",
                    "origin_station_number",
                    "origin_station_name",
                    "destination_station_number",
                    "destination_station_name",
                    "started_at",
                    "ended_at",
                    "duration_minutes",
                    "duration_text",
                },
            )
            self.assertNotIn("fake-user-id", json.dumps(normalized))
            self.assertNotIn("fake-device-id", json.dumps(normalized))
            self.assertEqual(trips_payload, original_trips_payload)
            self.assertEqual(len(opener.requests), 3)

    def test_interactive_output_does_not_include_secrets(self) -> None:
        result = FlowResult(
            token_sec_expiration=2592000,
            trips_status=200,
            trips_api_code="00",
            received_count=2,
            normalized_count=2,
            output_path=Path("tools/bicimad_probe/private/trips_normalized.json"),
        )
        secret_values = [
            "person@example.test",
            "fake-password",
            "fake-pass-key",
            "fake-client-id",
            "fake-device-id",
        ]

        stdout = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=["person@example.test"]),
            mock.patch(
                "getpass.getpass",
                side_effect=[
                    "fake-password",
                ],
            ),
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                return_value=TechnicalConfig(
                    pass_key="fake-pass-key",
                    x_client_id="fake-client-id",
                ),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
                return_value="fake-device-id",
            ),
            mock.patch(
                "fetch_trips_with_login.run_login_trip_flow",
                return_value=result,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_trips_with_login.main([])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        for secret in secret_values:
            self.assertNotIn(secret, output)
        self.assertIn("Login MPass: correcto", output)
        self.assertIn("Archivo generado:", output)

    def test_safe_error_output_does_not_include_nif_or_full_response(self) -> None:
        error = ProbeRequestError(
            stage="userdata",
            status=200,
            api_code="01",
            api_description="El usuario tiene contratos",
            error_type="MissingRequiredField",
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            fetch_trips_with_login._print_safe_error(error)

        output = stdout.getvalue()
        self.assertIn("Etapa fallida: userdata", output)
        self.assertIn("Codigo de API: 01", output)
        self.assertNotIn("fake-dn-format", output)
        self.assertNotIn("DS_DN", output)
        self.assertNotIn("DS_NIF", output)
        self.assertNotIn("{", output)
        self.assertNotIn("}", output)

    def test_generated_device_id_has_16_lowercase_hex_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generated_device_id.txt"
            value = fetch_trips_with_login.get_or_create_generated_device_id(path)

            self.assertRegex(value, r"^[0-9a-f]{16}$")
            self.assertEqual(path.read_text(encoding="utf-8"), value)

    def test_auto_device_id_creates_file_first_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "generated_device_id.txt"

            value = fetch_trips_with_login.get_or_create_generated_device_id(path)

            self.assertTrue(path.exists())
            self.assertEqual(len(value), 16)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{16}", value))

    def test_auto_device_id_reuses_existing_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generated_device_id.txt"
            path.write_text("0123456789abcdef", encoding="utf-8")

            first = fetch_trips_with_login.get_or_create_generated_device_id(path)
            second = fetch_trips_with_login.get_or_create_generated_device_id(path)

            self.assertEqual(first, "0123456789abcdef")
            self.assertEqual(second, "0123456789abcdef")

    def test_auto_device_id_rejects_invalid_value_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generated_device_id.txt"
            path.write_text("invalid-device-id", encoding="utf-8")

            with self.assertRaises(fetch_trips_with_login.InvalidLocalDeviceIdError):
                fetch_trips_with_login.get_or_create_generated_device_id(path)

            self.assertEqual(path.read_text(encoding="utf-8"), "invalid-device-id")

    def test_auto_device_id_does_not_prompt_for_device_id_or_print_it(self) -> None:
        result = FlowResult(
            token_sec_expiration=2592000,
            trips_status=200,
            trips_api_code="00",
            received_count=2,
            normalized_count=2,
            output_path=Path("tools/bicimad_probe/private/trips_normalized.json"),
        )
        stdout = io.StringIO()

        with (
            mock.patch("builtins.input", side_effect=["person@example.test"]),
            mock.patch(
                "getpass.getpass",
                side_effect=[
                    "fake-password",
                ],
            ) as getpass_mock,
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                return_value=TechnicalConfig(
                    pass_key="fake-pass-key",
                    x_client_id="fake-client-id",
                ),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
                return_value="0123456789abcdef",
            ),
            mock.patch(
                "fetch_trips_with_login.run_login_trip_flow",
                return_value=result,
            ) as flow_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_trips_with_login.main(["--auto-device-id"])

        self.assertEqual(exit_code, 0)
        prompts = [call.args[0] for call in getpass_mock.call_args_list]
        self.assertNotIn("Device ID: ", prompts)
        self.assertNotIn("0123456789abcdef", stdout.getvalue())
        self.assertEqual(
            flow_mock.call_args.kwargs["device_id"],
            "0123456789abcdef",
        )

    def test_generated_device_id_is_used_in_login_userdata_and_trips(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(_login_payload()),
                FakeResponse(_userdata_payload()),
                FakeResponse(_trips_payload()),
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "trips_normalized.json"
            run_login_trip_flow(
                email="person@example.test",
                password="fake-password",
                pass_key="fake-pass-key",
                x_client_id="fake-client-id",
                device_id="0123456789abcdef",
                device_model_visible="Model X",
                android_version="13",
                output_path=output_path,
                opener=opener,
            )

        self.assertEqual(len(opener.requests), 3)
        for request in opener.requests:
            self.assertEqual(request.headers.get("Deviceid"), "0123456789abcdef")

    def test_normal_script_only_prompts_for_email_and_password(self) -> None:
        result = FlowResult(
            token_sec_expiration=2592000,
            trips_status=200,
            trips_api_code="00",
            received_count=2,
            normalized_count=2,
            output_path=Path("tools/bicimad_probe/private/trips_normalized.json"),
        )

        stdout = io.StringIO()
        with (
            mock.patch(
                "builtins.input", side_effect=["person@example.test"]
            ) as input_mock,
            mock.patch(
                "getpass.getpass", side_effect=["fake-password"]
            ) as getpass_mock,
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                return_value=TechnicalConfig(
                    pass_key="fake-pass-key",
                    x_client_id="fake-client-id",
                ),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
                return_value="0123456789abcdef",
            ),
            mock.patch(
                "fetch_trips_with_login.run_login_trip_flow",
                return_value=result,
            ) as flow_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_trips_with_login.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(input_mock.call_args_list, [mock.call("Email: ")])
        self.assertEqual(getpass_mock.call_args_list, [mock.call("Contraseña: ")])
        self.assertEqual(flow_mock.call_args.kwargs["pass_key"], "fake-pass-key")
        self.assertEqual(flow_mock.call_args.kwargs["x_client_id"], "fake-client-id")
        self.assertEqual(flow_mock.call_args.kwargs["device_id"], "0123456789abcdef")

    def test_invalid_auto_device_id_performs_no_calls(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=["person@example.test"]),
            mock.patch("getpass.getpass", side_effect=["fake-password"]),
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                return_value=TechnicalConfig(
                    pass_key="fake-pass-key",
                    x_client_id="fake-client-id",
                ),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
                side_effect=fetch_trips_with_login.InvalidLocalDeviceIdError(),
            ),
            mock.patch(
                "fetch_trips_with_login.run_login_trip_flow",
            ) as flow_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_trips_with_login.main([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stdout.getvalue().strip(),
            "El deviceId local tiene un formato inválido",
        )
        flow_mock.assert_not_called()

    def test_local_secrets_saves_pass_key_and_x_client_id(self) -> None:
        backend = FakeKeyring()

        save_technical_config(
            pass_key="fake-pass-key",
            x_client_id="fake-client-id",
            keyring_backend=backend,
        )

        self.assertEqual(
            backend.values[(SERVICE_NAME, PASS_KEY_ENTRY)],
            "fake-pass-key",
        )
        self.assertEqual(
            backend.values[(SERVICE_NAME, X_CLIENT_ID_ENTRY)],
            "fake-client-id",
        )
        self.assertEqual(
            {name for _service, name in backend.values},
            {PASS_KEY_ENTRY, X_CLIENT_ID_ENTRY},
        )

    def test_local_secrets_recovers_both_values(self) -> None:
        backend = FakeKeyring()
        backend.values[(SERVICE_NAME, PASS_KEY_ENTRY)] = "fake-pass-key"
        backend.values[(SERVICE_NAME, X_CLIENT_ID_ENTRY)] = "fake-client-id"

        config = load_technical_config(keyring_backend=backend)

        self.assertEqual(config.pass_key, "fake-pass-key")
        self.assertEqual(config.x_client_id, "fake-client-id")

    def test_local_secrets_detects_incomplete_configuration(self) -> None:
        backend = FakeKeyring()
        backend.values[(SERVICE_NAME, PASS_KEY_ENTRY)] = "fake-pass-key"

        with self.assertRaises(MissingLocalTechnicalConfigError):
            load_technical_config(keyring_backend=backend)

    def test_local_secrets_deletes_both_entries(self) -> None:
        backend = FakeKeyring()
        backend.values[(SERVICE_NAME, PASS_KEY_ENTRY)] = "fake-pass-key"
        backend.values[(SERVICE_NAME, X_CLIENT_ID_ENTRY)] = "fake-client-id"

        clear_technical_config(keyring_backend=backend)

        self.assertEqual(backend.values, {})
        self.assertEqual(
            backend.deleted,
            [(SERVICE_NAME, PASS_KEY_ENTRY), (SERVICE_NAME, X_CLIENT_ID_ENTRY)],
        )

    def test_configure_local_probe_stores_without_showing_values(self) -> None:
        backend = FakeKeyring()
        stdout = io.StringIO()

        with (
            mock.patch(
                "configure_local_probe.getpass.getpass",
                side_effect=["fake-pass-key", "fake-client-id"],
            ),
            mock.patch(
                "configure_local_probe.save_technical_config",
                side_effect=lambda *, pass_key, x_client_id: save_technical_config(
                    pass_key=pass_key,
                    x_client_id=x_client_id,
                    keyring_backend=backend,
                ),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = configure_local_probe.main([])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Configuración técnica almacenada correctamente.", output)
        self.assertNotIn("fake-pass-key", output)
        self.assertNotIn("fake-client-id", output)

    def test_configure_local_probe_clears_without_showing_values(self) -> None:
        backend = FakeKeyring()
        backend.values[(SERVICE_NAME, PASS_KEY_ENTRY)] = "fake-pass-key"
        backend.values[(SERVICE_NAME, X_CLIENT_ID_ENTRY)] = "fake-client-id"
        stdout = io.StringIO()

        with (
            mock.patch(
                "configure_local_probe.clear_technical_config",
                side_effect=lambda: clear_technical_config(keyring_backend=backend),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = configure_local_probe.main(["--clear"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "Configuración técnica eliminada.")
        self.assertNotIn("fake-pass-key", output)
        self.assertNotIn("fake-client-id", output)

    def test_local_config_does_not_store_user_session_or_trip_secrets(self) -> None:
        backend = FakeKeyring()

        save_technical_config(
            pass_key="fake-pass-key",
            x_client_id="fake-client-id",
            keyring_backend=backend,
        )

        stored_names = {name for _service, name in backend.values}
        self.assertNotIn("email", stored_names)
        self.assertNotIn("password", stored_names)
        self.assertNotIn("accessToken", stored_names)
        self.assertNotIn("idUser", stored_names)
        self.assertNotIn("nif", stored_names)

    def test_missing_local_config_performs_no_requests(self) -> None:
        stdout = io.StringIO()

        with (
            mock.patch("builtins.input", side_effect=["person@example.test"]),
            mock.patch("getpass.getpass", side_effect=["fake-password"]),
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                side_effect=MissingLocalTechnicalConfigError(),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
            ) as device_mock,
            mock.patch(
                "fetch_trips_with_login.run_login_trip_flow",
            ) as flow_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = fetch_trips_with_login.main([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                "Falta la configuración técnica local.",
                "Ejecuta:",
                "python tools/bicimad_probe/configure_local_probe.py",
            ],
        )
        device_mock.assert_not_called()
        flow_mock.assert_not_called()

    def test_prompt_values_reuses_generated_device_id(self) -> None:
        with (
            mock.patch("builtins.input", side_effect=["person@example.test"]),
            mock.patch("getpass.getpass", side_effect=["fake-password"]),
            mock.patch(
                "fetch_trips_with_login.load_technical_config",
                return_value=TechnicalConfig(
                    pass_key="fake-pass-key",
                    x_client_id="fake-client-id",
                ),
            ),
            mock.patch(
                "fetch_trips_with_login.get_or_create_generated_device_id",
                return_value="0123456789abcdef",
            ),
        ):
            values = fetch_trips_with_login._prompt_values()

        self.assertEqual(values["device_id"], "0123456789abcdef")

    def test_keyring_change_does_not_change_normalized_json(self) -> None:
        trips_payload = _trips_payload()
        original = copy.deepcopy(trips_payload)

        normalized_before = _run_flow_and_read_normalized(trips_payload)
        normalized_after = _run_flow_and_read_normalized(trips_payload)

        self.assertEqual(normalized_before, normalized_after)
        self.assertEqual(trips_payload, original)


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.requests = []

    def __call__(self, request, timeout: int):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}
        self.deleted = []

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.deleted.append((service, username))
        self.values.pop((service, username), None)


def _call_login(opener: FakeOpener) -> None:
    login(
        email="person@example.test",
        password="fake-password",
        pass_key="fake-pass-key",
        x_client_id="fake-client-id",
        device_id="fake-device-id",
        login_device_model=build_login_device_model("Model X", "13"),
        opener=opener,
    )


def _run_flow_and_read_normalized(trips_payload: dict) -> list[dict]:
    opener = FakeOpener(
        [
            FakeResponse(_login_payload()),
            FakeResponse(_userdata_payload()),
            FakeResponse(trips_payload),
        ]
    )
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "trips_normalized.json"
        run_login_trip_flow(
            email="person@example.test",
            password="fake-password",
            pass_key="fake-pass-key",
            x_client_id="fake-client-id",
            device_id="0123456789abcdef",
            device_model_visible="Model X",
            android_version="13",
            output_path=output_path,
            opener=opener,
        )
        return json.loads(output_path.read_text(encoding="utf-8"))


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.test",
        code=status,
        msg="Forbidden",
        hdrs={},
        fp=io.BytesIO(
            json.dumps({"code": "41", "description": "request rejected"}).encode(
                "utf-8"
            )
        ),
    )


def _login_payload() -> dict:
    return {
        "code": "00",
        "description": "ok",
        "data": [
            {
                "accessToken": "fake-access-token",
                "accessTokenCryp": "ignored",
                "idUser": "fake-user-id",
                "tokenSecExpiration": 2592000,
            }
        ],
    }


def _userdata_payload() -> dict:
    return {
        "code": "00",
        "description": "ok",
        "data": {
            "DS_DN": "fake-dn-format",
            "DS_NIF": "ignored",
            "name": "ignored",
        },
    }


def _trips_payload() -> dict:
    return {
        "code": "00",
        "description": "ok",
        "data": [
            {
                "trip_id": "fake-trip-001",
                "userId": "fake-user-id",
                "id_bike": "fake-bike",
                "payment": {"amount": 1.25},
                "undock": {
                    "undock_station_number": "90",
                    "undock_station_name": "Manuel Becerra",
                    "undock_ts": "2026-07-31T08:16:00+02:00",
                },
                "dock": {
                    "dock_station_number": "101",
                    "dock_station_name": "Felipe II",
                    "dock_ts": "2026-07-31T08:22:48+02:00",
                },
                "trip_minutes": 6.8,
                "trip_interval": "00:06:48",
            },
            {
                "trip_id": "fake-trip-002",
                "locator": "fake-locator",
                "undock": {
                    "undock_station_number": "49",
                    "undock_station_name": "",
                    "undock_ts": "2026-07-30T19:03:00+02:00",
                },
                "dock": {
                    "dock_station_number": "52",
                    "dock_station_name": "Puerta del Sol",
                    "dock_ts": "2026-07-30T19:15:34+02:00",
                },
                "trip_minutes": 12.566,
                "trip_interval": "00:12:34",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
