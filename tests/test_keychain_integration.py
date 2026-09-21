"""Runs only on macOS: verifies the real `security` Keychain adapter."""

import sys
import uuid

import pytest

from triton.storage import keychain


@pytest.mark.skipif(sys.platform != "darwin", reason="requires the macOS Keychain")
def test_keychain_round_trip() -> None:
    account = f"triton-ci-{uuid.uuid4()}"
    try:
        assert keychain.get_secret(account) is None
        keychain.set_secret(account, "integration-secret")
        assert keychain.get_secret(account) == "integration-secret"
        keychain.set_secret(account, None)
        assert keychain.get_secret(account) is None
    finally:
        keychain.set_secret(account, None)
