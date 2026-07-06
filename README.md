# FGC Trains for Home Assistant

Custom Home Assistant integration that reports minutes until the next train
departure from any FGC (Ferrocarrils de la Generalitat de Catalunya)
station, using the public
[FGC open-data API](https://dadesobertes.fgc.cat/api-console/explore/v2.1/catalog/datasets/gtfs_stops/)
(`viajes-de-hoy` dataset, today's full timetable).

## Install

### HACS (recommended)

1. HACS -> the three-dot menu (top right) -> **Custom repositories**.
2. Add this repository's URL, category **Integration**.
3. Install "FGC Trains" from HACS, then restart Home Assistant.

### Manual

Copy `custom_components/fgc` into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

## Setup

1. **Settings -> Devices & Services -> Add Integration -> FGC Trains.**
2. Optionally paste your own FGC open-data API key for a higher request
   quota. Leave it blank to use anonymous access (5000 requests/day, shared
   per IP by the FGC portal).
3. Pick the first station to monitor.
4. To monitor more stations, or drop one, open the integration's
   **Configure** menu and choose "Add a station" / "Remove a station" — no
   need to re-run the setup wizard.

Each station gets one sensor, `sensor.fgc_<station>`, whose state is the
number of whole minutes until the next scheduled departure from that
station (across all its platforms/lines). Attributes include the line,
destination, platform, the exact next departure time, and up to four
further upcoming departures.

## How it works

The `viajes-de-hoy` dataset returns the entire day's static timetable per
station rather than supporting a live "what's next" query, so the
integration fetches each station's full remaining schedule once (on
startup, and again whenever the calendar day rolls over) and caches it.
Every 30 seconds it re-filters that cached list against the current time —
no extra API calls — to recompute "minutes remaining." This keeps API
usage low regardless of how many stations you add.

Note this is the *scheduled* timetable, not live delay/real-time data, so
it won't reflect delays or cancellations.
