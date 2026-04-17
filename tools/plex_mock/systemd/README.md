# Deploy `datum-plex-mock` on `datum-runtime`

Assumes the Datum repo is at `/opt/datum` and a virtualenv at
`/opt/datum/.venv` with `pip install -e .` having registered
`datum-plex-mock-serve`.

## SSH in via IAP

```bash
gcloud compute ssh datum-runtime --zone=us-central1-a --tunnel-through-iap \
  --project=$PROJECT_ID
```

## On the VM

```bash
sudo mkdir -p /var/lib/datum
sudo chown datum:datum /var/lib/datum
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
- Refresh snapshots from the VM: `cd /opt/datum && /opt/datum/.venv/bin/datum-plex-mock-snapshot`
