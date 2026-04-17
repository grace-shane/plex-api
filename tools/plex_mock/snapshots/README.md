# Canned GET snapshots

JSON responses captured from real `connect.plex.com` so the mock can
serve realistic GETs without a live-Plex dependency. Refresh via
`python -m tools.plex_mock.capture_snapshots` when Plex shapes change.

Files here are committed. Ad-hoc mock captures (POSTs the sync sent)
live in `tools/plex_mock/captures/` which is gitignored.
