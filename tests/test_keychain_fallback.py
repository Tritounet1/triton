"""Covers the non-macOS fallback path (a private JSON file under ROOT_DIR),
independent of platform - test_keychain_integration.py covers the real
macOS Keychain adapter and only runs there."""

from triton.storage import keychain


def test_fallback_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(keychain, "available", lambda: False)
    monkeypatch.setattr(keychain, "FALLBACK_FILE", tmp_path / "secrets.json")

    assert keychain.get_secret("mcp:server:token") is None
    keychain.set_secret("mcp:server:token", "s3cr3t")
    assert keychain.get_secret("mcp:server:token") == "s3cr3t"
    keychain.set_secret("mcp:server:token", None)
    assert keychain.get_secret("mcp:server:token") is None


def test_fallback_file_is_only_readable_by_its_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(keychain, "available", lambda: False)
    fallback_file = tmp_path / "secrets.json"
    monkeypatch.setattr(keychain, "FALLBACK_FILE", fallback_file)

    keychain.set_secret("mcp:server:token", "s3cr3t")

    assert fallback_file.stat().st_mode & 0o777 == 0o600
