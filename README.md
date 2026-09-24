# gravatar-sync

Keeps a local Linux user account's picture (the one AccountsService
hands to the login manager, GNOME/KDE user menu, etc.) in sync with
that person's [Gravatar](https://gravatar.com).

Runs as a root systemd oneshot service, triggered by a timer shortly
after boot and once a day after that, so:

- the login screen already shows the right picture before anyone logs in
- later Gravatar changes get picked up without a reboot

Nothing user-specific is hardcoded — the target username is read from
an environment file at runtime, and the email address is too, unless
you leave it out, in which case it's read from AccountsService itself.

## How it works

1. Resolves the target user's email: `GRAVATAR_SYNC_EMAIL` if set,
   otherwise whatever `Email` AccountsService already has on record for
   the account (the same field a desktop's System Settings -> Users
   writes to).
2. Hashes it (SHA-256, as Gravatar's current API expects) and requests
   `https://www.gravatar.com/avatar/<hash>.png`.
3. If no Gravatar is set for that address (`404`), it exits quietly.
4. If the image is identical to the last one applied (tracked by hash
   in `GRAVATAR_SYNC_STATE_DIR`), it exits without touching anything.
5. Otherwise it writes the image to
   `/var/lib/AccountsService/icons/<user>` and calls
   `org.freedesktop.Accounts.User.SetIconFile` over the system D-Bus
   bus so AccountsService picks it up.

Setting *another* account's icon this way needs root (or a polkit
authentication AccountsService won't grant unattended), which is why
this runs as a system service rather than a user one.

## Requirements

- `python3` (stdlib only, no extra packages)
- `busctl` (part of systemd)
- `accountsservice` running and owning `org.freedesktop.Accounts` on
  the system bus — standard on most desktop distros (GNOME, KDE, ...)

## Install

```sh
sudo ./install.sh
sudo "$EDITOR" /etc/gravatar-sync/.env   # set your username (+ email if AccountsService doesn't have one)
sudo systemctl enable --now gravatar-sync.timer
```

Run it once by hand to confirm it works, and watch the log:

```sh
sudo systemctl start gravatar-sync.service
journalctl -u gravatar-sync.service -e
```

### Manual install

If you'd rather not run `install.sh`:

```sh
sudo install -Dm755 gravatar_sync.py /usr/local/bin/gravatar-sync
sudo install -Dm644 systemd/gravatar-sync.service /etc/systemd/system/
sudo install -Dm644 systemd/gravatar-sync.timer /etc/systemd/system/
sudo install -Dm600 .env.example /etc/gravatar-sync/.env
# edit /etc/gravatar-sync/.env, then:
sudo systemctl daemon-reload
sudo systemctl enable --now gravatar-sync.timer
```

## Configuration

Set in `/etc/gravatar-sync/.env` (see `.env.example`):

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `GRAVATAR_SYNC_USER` | yes | — | Local username to update |
| `GRAVATAR_SYNC_EMAIL` | no | AccountsService's `Email` for the user | Email address whose Gravatar to fetch |
| `GRAVATAR_SYNC_SIZE` | no | `512` | Requested image size in pixels |
| `GRAVATAR_SYNC_STATE_DIR` | no | `/var/lib/gravatar-sync` | Where the last-applied image hash is stored |

If neither `GRAVATAR_SYNC_EMAIL` nor AccountsService's `Email` field is
set, the service logs an error and exits (nonzero) rather than guessing.

## Uninstall

```sh
sudo systemctl disable --now gravatar-sync.timer
sudo rm /etc/systemd/system/gravatar-sync.{service,timer} /usr/local/bin/gravatar-sync
sudo rm -rf /etc/gravatar-sync /var/lib/gravatar-sync
sudo systemctl daemon-reload
```

Your account's icon file at `/var/lib/AccountsService/icons/<user>`
is left in place; replace or remove it yourself if you want to revert.
