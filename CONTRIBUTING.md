# Contributing to ha-fgc-trains

Thanks for considering a contribution! This is a small side-project
integration, so the bar is informal, but a few things make reviewing a PR
much faster:

## Setup

```bash
git clone https://github.com/JNP2020/ha-fgc-trains.git
cd ha-fgc-trains
pip install -r requirements_test.txt
```

## Before opening a PR

```bash
ruff check custom_components tests   # lint
pytest -v                            # unit tests
```

Both run in CI (`.github/workflows/tests.yaml`) and must pass, along with
`hassfest` (`.github/workflows/hassfest.yaml`, validates `manifest.json`
and friends) and HACS validation (`.github/workflows/hacs.yaml`).

## Adding a new optional data source

The pattern for an opt-in secondary coordinator (ski parking, webcams,
air quality, carbon footprint, ...) is a single declarative entry in
`_OPTIONAL_FEATURES` in `custom_components/fgc/__init__.py` — see the
tuple fields there for what's needed (a `DataUpdateCoordinator` subclass,
an options flag, a default enabled/disabled state, and an "empty" value
for when its first refresh fails). You generally shouldn't need to touch
`async_setup_entry` or `_remove_stale_entities` directly.

## Translations

User-facing strings live in `custom_components/fgc/strings.json` (the
source of truth) and are mirrored into
`custom_components/fgc/translations/<lang>.json`. A missing key in a
non-English file falls back to English automatically, so a translation
PR doesn't need to cover every string at once.

## Reporting a bug

Please include your Home Assistant version, whether you're using a
personal FGC API key or anonymous access, and the relevant lines from
Settings -> System -> Logs (search for `fgc`).
