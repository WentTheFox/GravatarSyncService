#!/usr/bin/env python3
"""Sync a local Linux account's picture from its Gravatar image.

All configuration comes from environment variables (see
.env.example) so nothing user-specific is hardcoded:

    GRAVATAR_SYNC_USER       Local username to update (required)
    GRAVATAR_SYNC_EMAIL      Email address whose Gravatar to fetch. Optional:
                              if unset, falls back to the Email field
                              AccountsService has on record for the user
                              (e.g. set via a desktop's System Settings ->
                              Users), and only fails if neither is available.
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
ACCOUNTS_INTERFACE = "org.freedesktop.Accounts"
USER_INTERFACE = "org.freedesktop.Accounts.User"


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


def _busctl_string(*args: str) -> str:
    """Run a busctl call/get-property and unwrap its `s "value"` output."""
    result = subprocess.run(
        ["busctl", "--system", *args], check=True, capture_output=True, text=True
    ).stdout.strip()
    return result.split('"', 1)[1].rsplit('"', 1)[0]


def dbus_user_object_path(username: str) -> str:
    # Output looks like: o "/org/freedesktop/Accounts/User1000"
    return _busctl_string(
        "call", ACCOUNTS_INTERFACE, "/org/freedesktop/Accounts",
        ACCOUNTS_INTERFACE, "FindUserByName", "s", username,
    )


def account_email(object_path: str) -> str | None:
    """The Email field AccountsService has on record for this user, if any."""
    try:
        email = _busctl_string(
            "get-property", ACCOUNTS_INTERFACE, object_path, USER_INTERFACE, "Email"
        )
    except subprocess.CalledProcessError:
        return None
    return email or None


def set_account_icon(object_path: str, icon_path: Path) -> None:
    subprocess.run(
        [
            "busctl", "--system", "call",
            ACCOUNTS_INTERFACE, object_path,
            USER_INTERFACE, "SetIconFile", "s", str(icon_path),
        ],
        check=True,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    username = env("GRAVATAR_SYNC_USER", required=True)
    size = env("GRAVATAR_SYNC_SIZE", "512")
    state_dir = Path(env("GRAVATAR_SYNC_STATE_DIR", "/var/lib/gravatar-sync"))

    try:
        object_path = dbus_user_object_path(username)
    except subprocess.CalledProcessError:
        log.error("no such AccountsService user: %s", username)
        return 1

    email = env("GRAVATAR_SYNC_EMAIL") or account_email(object_path)
    if not email:
        log.error(
            "no GRAVATAR_SYNC_EMAIL set, and AccountsService has no Email on "
            "record for %s (set one in your desktop's User Settings, or set "
            "GRAVATAR_SYNC_EMAIL in the config)",
            username,
        )
        return 1

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

    set_account_icon(object_path, icon_path)

    state_dir.mkdir(parents=True, exist_ok=True)
    state_file.write_text(digest + "\n")
    log.info("updated account picture for %s from Gravatar", username)
    return 0


if __name__ == "__main__":
    sys.exit(main())
