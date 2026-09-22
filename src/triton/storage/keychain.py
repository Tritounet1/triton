"""Credential storage: macOS Keychain when available, otherwise a private
JSON file under ROOT_DIR (same trust boundary as settings.json/session
data) - covers Linux/Docker deployments where no OS keychain exists."""

import contextlib
import json
import subprocess
import sys

from triton.paths import ROOT_DIR

SERVICE = "Triton"
FALLBACK_FILE = ROOT_DIR / "secrets.json"


def available() -> bool:
    return sys.platform == "darwin"


def _fallback_load() -> dict[str, str]:
    if not FALLBACK_FILE.exists():
        return {}
    try:
        data = json.loads(FALLBACK_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _fallback_save(data: dict[str, str]) -> None:
    FALLBACK_FILE.write_text(json.dumps(data))
    with contextlib.suppress(OSError):
        FALLBACK_FILE.chmod(0o600)


def get_secret(account: str) -> str | None:
    if not available():
        return _fallback_load().get(account) or None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def set_secret(account: str, value: str | None) -> None:
    if not available():
        data = _fallback_load()
        if value is None:
            data.pop(account, None)
        else:
            data[account] = value
        _fallback_save(data)
        return
    if value is None:
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", account],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", value],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Impossible d'enregistrer la cle dans le trousseau systeme.")
