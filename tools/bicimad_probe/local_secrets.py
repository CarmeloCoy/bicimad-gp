#!/usr/bin/env python3
"""Local technical secrets stored in the OS credential vault."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

SERVICE_NAME = "bicimad_social_probe"
PASS_KEY_ENTRY = "passKey"
X_CLIENT_ID_ENTRY = "xClientId"
PASS_KEY_ENV = "BICIMAD_PASS_KEY"
X_CLIENT_ID_ENV = "BICIMAD_X_CLIENT_ID"


@dataclass(frozen=True, repr=False)
class TechnicalConfig:
    pass_key: str
    x_client_id: str


class MissingLocalTechnicalConfigError(RuntimeError):
    pass


def save_technical_config(
    *,
    pass_key: str,
    x_client_id: str,
    keyring_backend: Any | None = None,
) -> None:
    backend = keyring_backend or _load_keyring()
    backend.set_password(SERVICE_NAME, PASS_KEY_ENTRY, pass_key)
    backend.set_password(SERVICE_NAME, X_CLIENT_ID_ENTRY, x_client_id)


def load_technical_config(
    *,
    keyring_backend: Any | None = None,
) -> TechnicalConfig:
    pass_key = os.environ.get(PASS_KEY_ENV, "").strip()
    x_client_id = os.environ.get(X_CLIENT_ID_ENV, "").strip()
    if pass_key and x_client_id:
        return TechnicalConfig(pass_key=pass_key, x_client_id=x_client_id)
    if pass_key or x_client_id:
        raise MissingLocalTechnicalConfigError()

    backend = keyring_backend or _load_keyring()
    pass_key = backend.get_password(SERVICE_NAME, PASS_KEY_ENTRY)
    x_client_id = backend.get_password(SERVICE_NAME, X_CLIENT_ID_ENTRY)
    if not pass_key or not x_client_id:
        raise MissingLocalTechnicalConfigError()
    return TechnicalConfig(pass_key=pass_key, x_client_id=x_client_id)


def clear_technical_config(*, keyring_backend: Any | None = None) -> None:
    backend = keyring_backend or _load_keyring()
    for entry in (PASS_KEY_ENTRY, X_CLIENT_ID_ENTRY):
        try:
            backend.delete_password(SERVICE_NAME, entry)
        except Exception:
            pass


def _load_keyring() -> Any:
    try:
        import keyring
    except ImportError as error:
        raise MissingLocalTechnicalConfigError() from error
    return keyring
