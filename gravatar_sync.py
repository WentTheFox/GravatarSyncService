#!/usr/bin/env python3
"""Sync a local Linux account's picture from its Gravatar image.

All configuration comes from environment variables (see
config.env.example) so nothing user-specific is hardcoded:

    GRAVATAR_SYNC_EMAIL      Email address whose Gravatar to fetch (required)
    GRAVATAR_SYNC_USER       Local username to update (required)
    GRAVATAR_SYNC_SIZE       Requested image size in pixels (default: 512)
    GRAVATAR_SYNC_STATE_DIR  Where to remember the last-applied image hash,
                              so unchanged Gravatars are a no-op
                              (default: /var/lib/gravatar-sync)

Meant to run as a root systemd oneshot service (see systemd/): setting
*another* account's AccountsService icon over D-Bus needs privileges
the target user doesn't have over their own session, and running it at
boot (before anyone logs in) means the login screen picture is already
correct.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("gravatar-sync")

ICON_DIR = Path("/var/lib/AccountsService/icons")


def env(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        log.error("missing required environment variable %s", name)
        sys.exit(1)
    return value


def gravatar_hash(email: str) -> str:
    normalized = email.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def fetch_gravatar(email: str, size: str) -> bytes | None:
    """Return the raw PNG bytes of the Gravatar for `email`, or None if unset."""
    digest = gravatar_hash(email)
    url = f"https://www.gravatar.com/avatar/{digest}.png?s={size}&d=404"
    request = urllib.request.Request(url, headers={"User-Agent": "gravatar-sync/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            log.info("no Gravatar image set for this email, nothing to do")
            return None
        raise


def dbus_user_object_path(username: str) -> str:
    result = subprocess.run(
        [
            "busctl", "--system", "call",
            "org.freedesktop.Accounts", "/org/freedesktop/Accounts",
            "org.freedesktop.Accounts", "FindUserByName", "s", username,
        ],
        check=True, capture_output=True, text=True,
    )
    # Output looks like: o "/org/freedesktop/Accounts/User1000"
    return result.stdout.strip().split('"')[1]


def set_account_icon(username: str, icon_path: Path) -> None:
    object_path = dbus_user_object_path(username)
    subprocess.run(
        [
            "busctl", "--system", "call",
            "org.freedesktop.Accounts", object_path,
            "org.freedesktop.Accounts.User", "SetIconFile", "s", str(icon_path),
        ],
        check=True,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    email = env("GRAVATAR_SYNC_EMAIL", required=True)
    username = env("GRAVATAR_SYNC_USER", required=True)
    size = env("GRAVATAR_SYNC_SIZE", "512")
    state_dir = Path(env("GRAVATAR_SYNC_STATE_DIR", "/var/lib/gravatar-sync"))

    image = fetch_gravatar(email, size)
    if image is None:
        return 0

    digest = hashlib.sha256(image).hexdigest()
    state_file = state_dir / f"{username}.sha256"
    if state_file.exists() and state_file.read_text().strip() == digest:
        log.info("Gravatar image unchanged, skipping icon update")
        return 0

    icon_path = ICON_DIR / username
    icon_path.write_bytes(image)
    icon_path.chmod(0o644)

    set_account_icon(username, icon_path)

    state_dir.mkdir(parents=True, exist_ok=True)
    state_file.write_text(digest + "\n")
    log.info("updated account picture for %s from Gravatar", username)
    return 0


if __name__ == "__main__":
    sys.exit(main())
