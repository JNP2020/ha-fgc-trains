# FGC Trains for Home Assistant

<img src="custom_components/fgc/logo.png" alt="FGC logo" width="180">

*The FGC logo above is used only to identify the transit network this
integration talks to. This is an independent, community-made project and
is not affiliated with, endorsed by, or supported by Ferrocarrils de la
Generalitat de Catalunya (FGC) — it's built entirely on FGC's public open
data API. Not an official product.*

Custom Home Assistant integration that reports minutes until the next train
departure from any FGC (Ferrocarrils de la Generalitat de Catalunya)
station, using the public
[FGC open-data API](https://dadesobertes.fgc.cat/api-console/explore/v2.1/catalog/datasets/gtfs_stops/)
(today's static timetable, corrected against FGC's live GTFS-Realtime feed
where available).

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

Each station gets one sensor per distinct destination served from it — a
station with only one destination all day (typically a terminus) collapses
down to a single sensor showing time + final destination (arriving/
terminating trains are excluded since they aren't a departure you can
board). A station served by several routes/directions gets one sensor per
destination, e.g. "FGC Sant Cugat Centre → Barcelona - Plaça Catalunya" and
"FGC Sant Cugat Centre → Terrassa Nacions Unides" — a busy hub terminus
like Plaça Catalunya gets one sensor per line it serves (Sabadell, Terrassa,
Sarrià, Av. Tibidabo, ...), regardless of which physical platform each
train happens to use. Each sensor's state is the number of whole minutes
until the next departure to that destination. Attributes include the line
(e.g. `S1`), destination, platform, a stable `direction` label, whether
that time is `realtime` or scheduled, the exact next departure time, and
up to four further upcoming departures.

Departure times are corrected against FGC's live GTFS-Realtime feed
whenever a confident match is available (matched by platform and closest
time, within a 10-minute window, since the realtime feed doesn't expose a
shared trip id to join on directly) — so a delayed train keeps counting
down past its scheduled time instead of vanishing, and a train that's
actually already gone drops off promptly instead of lingering with a
stale scheduled time. When no realtime match exists, the static scheduled
time is used, same as before.

### Live train map

The integration also creates a `device_tracker` entity for every active
train, using FGC's real-time Geotren feed (updated every 30 seconds).
These show up automatically on Home Assistant's built-in Map (which renders
on OpenStreetMap tiles) — just add a Map card/dashboard, no configuration
needed. Each tracker's attributes include its line, direction, origin,
destination, next stops, on-time status, and unit type. Trains that drop
out of service are marked unavailable rather than removed, since the same
physical unit typically reappears later in the day.

This can be switched off from the integration's **Configure -> Settings**
menu ("Show live train positions on the map") if you'd rather not poll the
position feed every 30 seconds — it's on by default. Turning it off removes
the train trackers; turning it back on recreates them.

### Timetable card (Geotren-style departure board)

The integration ships a custom Lovelace card, styled after FGC's own
[Geotren departure boards](https://geotren.fgc.cat/), that shows a live,
scrolling-style timetable for one station: a colored line badge, the
destination, minutes remaining, and platform, refreshed every second from
the station's sensors.

**One-time setup:** Settings -> Dashboards -> ⋮ (top right) -> Resources ->
Add Resource -> URL `/fgc_static/fgc-timetable-card.js`, type
**JavaScript Module**. (The integration serves this file itself — no extra
files to copy anywhere.)

Then add a card to any dashboard:

```yaml
type: custom:fgc-timetable-card
station: Sant Cugat Centre   # must match the sensors' station_name attribute exactly
title: Sant Cugat            # optional, defaults to the station name — shown in the header,
                              # handy when you have several of these cards on one dashboard
rows: 4                      # optional, default 4
```

A small green dot next to a destination means that row's time is a live
GTFS-Realtime prediction rather than the static schedule.

### Home screen widget (companion app)

The Android/iOS Home Assistant app's native home-screen widgets can't run
the Lovelace card above (widgets don't execute custom card JavaScript) —
so instead, the integration creates a `camera` entity per configured
station, **"FGC \<station\> Board"**, that renders the exact same
departure-board style as a plain image, redrawn fresh every time
something asks for a snapshot. Point a **Camera**/**Picture** widget at
it from the companion app's widget picker and you get the departure
board on your home screen, no separate setup needed — it's created
automatically alongside the regular sensors.

Note native widgets refresh on the OS's schedule (typically every 15–30+
minutes in the background, more often if you open the app), so unlike
the live Lovelace card this won't count down second-by-second — it's a
snapshot that's accurate as of whenever it was last refreshed.

### Service alerts

A single **"FGC Service Alerts"** sensor, state = number of currently
active network/line-wide service alerts (delays, disruptions, planned
works, etc.), with the full text of each as an attribute. Distinct from
the noisy GTFS-Realtime "alerts" feed (which is mostly routine per-trip
annotations, not real disruptions) — this uses FGC's own small, clean
feed of actual published alerts. On by default; switch off from
**Configure -> Settings** ("Service alerts sensor").

### Ski/mountain resort sensors

The integration also creates one sensor per FGC-operated mountain resort
(La Molina, Vall de Núria, Vallter, Espot, Port Ainé, Boí Taüll), state
`open`/`closed`, using FGC's tourism-facilities open-data feeds (this
covers the resorts' general lift/facility network, so a resort reads
`open` in the summer hiking/bike season too, not just during ski season).
Attributes include how many facilities are currently open out of the
total, temperature and wind speed from the resort's weather station,
any active service alerts, and a live webcam image URL where available.

This can also be switched off from **Configure -> Settings** ("Show FGC
mountain resort status sensors") — on by default.

### Optional extras (all off by default)

A few more FGC open-data feeds are available as opt-in sensors from
**Configure -> Settings** — off by default since most users won't want the
extra API calls/entities:

- **Air quality near your stations** — one sensor per *configured* station
  that has a nearby air-quality reading, state = the official Catalan air
  quality index (e.g. `MODERAT`), with NO2/O3/PM10 and the source
  monitoring station as attributes.
- **Ski resort parking** — one sensor per resort, state = total parking
  spaces across its facilities, with each facility's name/spaces as an
  attribute.
- **Ski resort webcams** — a `camera` entity per currently-active resort
  webcam, fetching the live still image on demand (not on a schedule).
- **FGC's yearly carbon footprint** — one sensor, state = total tCO2e for
  the most recently reported year, with mobility/tourism split and a
  breakdown by emissions scope as attributes.

## How it works

The `viajes-de-hoy` dataset returns the entire day's static timetable per
station rather than supporting a live "what's next" query, so the
integration fetches each station's full remaining schedule once (on
startup, and again whenever the calendar day rolls over) and caches it.
Every 30 seconds it re-filters that cached list against the current time —
no extra API calls — to recompute "minutes remaining." This keeps API
usage low regardless of how many stations you add.

Departure times blend the static schedule with FGC's live GTFS-Realtime
Trip Updates feed (fetched fleet-wide once per tick, then matched to each
station's candidate departures), so they reflect real delays/early
departures where a confident match exists, not just the timetable. Since
that feed has no shared trip id to join on, matches are chosen globally by
best-fit (closest time first across every candidate pair, not just
earliest-scheduled-first) and deduplicated by line + destination + time,
so two close-together departures can't end up both matched to the same
prediction or shown as if the same train appeared twice.

If you see a log warning about the FGC API quota running low, either add
your own API key in the integration's settings for a higher limit, or turn
off the live map / ski sensors to reduce daily request usage.

The board-image camera (used for the home screen widget) is rendered with
[Pillow](https://python-pillow.org/) using the bundled
[Roboto](https://github.com/googlefonts/roboto-2) font (Apache License 2.0,
see `custom_components/fgc/fonts/LICENSE.txt`).
