"""Small macOS Keychain adapter used for credentials, never for settings."""

import subprocess
import sys

SERVICE = "Triton"


def available() -> bool:
    return sys.platform == "darwin"


def get_secret(account: str) -> str | None:
    if not available():
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def set_secret(account: str, value: str | None) -> None:
    if not available():
        raise RuntimeError("Le trousseau systeme n'est pas disponible sur cette plateforme.")
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
