# Changelog

All notable changes to this integration are documented here. Versions
match `custom_components/fgc/manifest.json`. For the full history before
2.14.0, see `git log`.

## 2.16.0

- Added `tests/` (pytest) covering the departure-parsing/realtime-
  matching/dedup logic in `coordinator.py` and the request-hardening
  helpers in `api.py`, plus a lint+test CI workflow
  (`.github/workflows/tests.yaml`, `ruff` + `pytest`).
- Added `CONTRIBUTING.md`, issue templates, and a PR template.
- Fixed the one remaining `ruff` lint finding (`SIM102`) and auto-fixed
  import ordering across the codebase.

## 2.15.0

- `__init__.py`: replaced the repeated per-optional-feature setup/sweep
  blocks with a single declarative `_OPTIONAL_FEATURES` table.
- Added a Home Assistant repair issue (Settings -> System -> Repairs)
  when the daily FGC open-data API quota runs low, instead of only a log
  warning.

## 2.14.0

- Hardened all outbound HTTP requests (FGC API, GTFS-RT feed download,
  ski webcam images): explicit timeouts, https-only on URLs the API
  hands back to us, and a size cap on downloaded files so a misbehaving
  upstream can't hang a coordinator or make it buffer an unbounded
  response.
- Truncated upstream error bodies folded into our own exception messages.

## Earlier

- Added overnight quiet-hours handling, auto-registered the timetable
  Lovelace card, added a reauth flow, Catalan/Aranese translations, and
  various hassfest/HACS validation fixes — see `git log` for details.
