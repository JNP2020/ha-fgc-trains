# Changelog

All notable changes to this integration are documented here. Versions
match `custom_components/fgc/manifest.json`. For the full history before
2.14.0, see `git log`.

## 2.17.0

Reliability fixes plus a few things that were missing. Nothing existing is
renamed or removed: the original sensors keep their entity ids and unique ids.

**Fixes**

- A failed schedule refresh no longer makes every departure sensor
  unavailable. If today's schedule is already cached it keeps being used and
  the refresh is retried after 5 minutes (a warning is logged). The error
  only surfaces when there is nothing usable cached.
- Departure sensors are no longer deleted because a destination is missing
  from *today's* timetable. A weekday-only branch used to lose its sensor
  (and history) on the first weekend reload. Sensors are now only removed when
  their station is removed from the configuration.
- Destinations that first appear while Home Assistant is running now get
  their sensors straight away instead of after the next reload.
- Realtime matching uses the route id from the GTFS-RT feed as a preference,
  so two lines stopping at one platform a minute apart no longer swap
  predictions. Cancelled trips and skipped stops are removed from the board
  instead of being shown as scheduled departures.
- Right after midnight, trains from the previous service day's `24:xx` times
  that haven't left yet are carried over into the new day's schedule.
- Station schedules are refreshed concurrently rather than one by one.

**New**

- "Next departure" timestamp sensor next to each minutes sensor
  (`device_class: timestamp`), for automations and templates.
- "FGC Service Disruption" binary sensor (problem class), on while there is
  at least one active service alert. Only created when service alerts are on.
- `fgc.get_departures` action: returns the next departures from a configured
  station (optionally filtered by destination) as response data. It reads the
  already-fetched data, so it costs no API requests.
- Reconfigure flow (three-dot menu -> Reconfigure) to change the API key.
- Diagnostics download, with the API key redacted.

**Internal**

- Runtime data lives in `entry.runtime_data` instead of `hass.data`.
- Test suite now runs against a real Home Assistant test instance
  (`pytest-homeassistant-custom-component`): setup, stale-entity pruning,
  refresh failure, the new action, diagnostics and reconfigure are covered.

## 2.16.3

- Documentation only — no code changes.
- README now reflects that FGC Trains is listed in the HACS **default
  store** (accepted 2026-10-18, [hacs/default#9047](https://github.com/hacs/default/pull/9047)):
  the install section describes searching for "FGC Trains" in HACS instead
  of adding a custom repository, and the stale "not currently listed in the
  HACS default store" line at the end of the README is gone.
- Released separately rather than as a bare README commit because HACS
  renders a repository's README from the Git ref it is installed from (the
  release tag), so README fixes only become visible in HACS once a new
  release carries them.

## 2.16.2

- Fixed a real bug in the 2.16.1 timezone fix: the timetable card's JS
  file was (and had always been) served at a fixed URL with no
  cache-busting, so browsers (and the frontend's own module cache) kept
  serving the old cached copy even after updating the integration and
  restarting Home Assistant — meaning the station-time fix shipped in
  2.16.1 silently did nothing for anyone who'd already loaded the card
  before updating. The card's URL now includes the integration's own
  version (`?v=2.16.2`), so every release that touches the card
  automatically forces a fresh fetch. If you're still on 2.16.1 and the
  clock is still showing the wrong time, this is why — update to 2.16.2.

## 2.16.1

- Fixed the timetable card's header clock: it now always shows the
  station's real local time (`Europe/Madrid`, every FGC station is in
  this one zone) instead of the dashboard device's own time zone. If
  you're viewing the dashboard from a different time zone, your local
  time is now shown underneath as a second, smaller line — only when it
  actually differs from the station's time, so most users still see a
  single clock.

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
