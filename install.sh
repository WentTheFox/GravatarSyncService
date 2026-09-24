#!/usr/bin/env bash
# Convenience installer. Reads what it needs to know, then wires the
# script up as a root systemd oneshot service + timer. Safe to re-run.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "run this as root (sudo ./install.sh)" >&2
    exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

install -Dm755 "$script_dir/gravatar_sync.py" /usr/local/bin/gravatar-sync
install -Dm644 "$script_dir/systemd/gravatar-sync.service" /etc/systemd/system/gravatar-sync.service
install -Dm644 "$script_dir/systemd/gravatar-sync.timer" /etc/systemd/system/gravatar-sync.timer

if [[ ! -f /etc/gravatar-sync/config.env ]]; then
    install -Dm600 "$script_dir/config.env.example" /etc/gravatar-sync/config.env
    echo "wrote /etc/gravatar-sync/config.env - edit it before starting the timer"
else
    echo "/etc/gravatar-sync/config.env already exists, leaving it alone"
fi

systemctl daemon-reload
echo
echo "installed. next steps:"
echo "  1. edit /etc/gravatar-sync/config.env"
echo "  2. systemctl enable --now gravatar-sync.timer"
echo "  3. systemctl start gravatar-sync.service   # to run it immediately and check journalctl -u gravatar-sync"
