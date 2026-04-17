# Deploy `datum-plex-mock` on `datum-runtime`

The unit expects a `datum` system user, the repo at `/opt/datum`, a
virtualenv at `/opt/datum/.venv` with `pip install -e .` completed, and
snapshots captured into `/opt/datum/tools/plex_mock/snapshots/`. None
of those exist on a fresh `datum-runtime` VM — do the one-time prereq
block below first.

## SSH in via IAP

```bash
gcloud compute ssh datum-runtime --zone=us-central1-a --tunnel-through-iap \
  --project=$PROJECT_ID
```

## One-time prereqs (skip if already set up)

```bash
# datum system user, owns the repo checkout + capture dir
sudo useradd --system --home /opt/datum --shell /usr/sbin/nologin datum

sudo mkdir -p /opt/datum /var/lib/datum
sudo chown datum:datum /opt/datum /var/lib/datum

# Clone + install (console script datum-plex-mock-serve lands in .venv)
sudo -u datum git clone https://github.com/grace-shane/Datum.git /opt/datum
sudo -u datum python3 -m venv /opt/datum/.venv
sudo -u datum /opt/datum/.venv/bin/pip install -e /opt/datum

# Snapshots — needs real Plex creds, so this step runs on the creds-having
# host (e.g. datum-runtime with secret-manager access, or captured locally
# and scp'd in). Skip if snapshots are already committed in the repo.
sudo -u datum PLEX_API_KEY=... PLEX_TENANT_ID=... \
  /opt/datum/.venv/bin/datum-plex-mock-snapshot
```

The mock binary has no Plex env var dependencies — it serves local
snapshots and writes to its own SQLite. The unit therefore does *not*
load `.env.local`. Only `capture_snapshots` needs Plex credentials.

## Install + start the unit

```bash
sudo cp /opt/datum/tools/plex_mock/systemd/datum-plex-mock.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now datum-plex-mock
sudo systemctl status datum-plex-mock
curl -sf http://127.0.0.1:8080/healthz
```

## Troubleshooting

- Logs: `journalctl -u datum-plex-mock -f`
- Stop: `sudo systemctl stop datum-plex-mock`
- Refresh snapshots from the VM: `cd /opt/datum && sudo -u datum /opt/datum/.venv/bin/datum-plex-mock-snapshot`
