# FGC Trains for Home Assistant

![FGC logo](custom_components/fgc/logo.png)

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
until the next scheduled departure to that destination. Attributes include
the line (e.g. `S1`), destination, platform, a stable `direction` label,
the exact next departure time, and up to four further upcoming departures.

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
rows: 4                      # optional, default 4
```

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

## How it works

The `viajes-de-hoy` dataset returns the entire day's static timetable per
station rather than supporting a live "what's next" query, so the
integration fetches each station's full remaining schedule once (on
startup, and again whenever the calendar day rolls over) and caches it.
Every 30 seconds it re-filters that cached list against the current time —
no extra API calls — to recompute "minutes remaining." This keeps API
usage low regardless of how many stations you add.

Note the departure-time sensors reflect the *scheduled* timetable, not
delay/real-time data, so they won't reflect delays or cancellations — the
live map, on the other hand, is genuinely real-time vehicle positioning.

If you see a log warning about the FGC API quota running low, either add
your own API key in the integration's settings for a higher limit, or turn
off the live map / ski sensors to reduce daily request usage.
