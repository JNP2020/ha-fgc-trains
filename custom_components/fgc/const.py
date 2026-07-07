"""Constants for the FGC integration."""
from datetime import timedelta

DOMAIN = "fgc"

CONF_API_KEY = "api_key"
CONF_STATIONS = "stations"
CONF_STATION_CODE = "station_code"
CONF_ENABLE_MAP = "enable_map"
CONF_ENABLE_SKI = "enable_ski"
CONF_ENABLE_ALERTS = "enable_alerts"
CONF_ENABLE_AIR_QUALITY = "enable_air_quality"
CONF_ENABLE_SKI_PARKING = "enable_ski_parking"
CONF_ENABLE_WEBCAMS = "enable_webcams"
CONF_ENABLE_CARBON_FOOTPRINT = "enable_carbon_footprint"

API_BASE_URL = "https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets"
DATASET_SCHEDULE = "viajes-de-hoy"
DATASET_VEHICLE_POSITIONS = "posicionament-dels-trens"
DATASET_STOPS = "gtfs_stops"
DATASET_SKI_FACILITIES = "estat-obertura-equipaments-turistics-fgc"
DATASET_SKI_WEATHER = "meteo-tim"
DATASET_SKI_ALERTS = "avisos-i-alertes-de-tim"
DATASET_SKI_WEBCAMS = "webcams-actives-tim"
DATASET_TRIP_UPDATES = "trip-updates-gtfs_realtime"
DATASET_AIR_QUALITY = "calidad-del-aire-por-paradas0"
DATASET_SKI_PARKING = "informacio-tecnica-aparcaments"
DATASET_CARBON_FOOTPRINT = "petjada-de-carboni-fgc"
DATASET_ALERTS = "avisos"

# Max rows the Opendatasoft Explore API allows per request.
API_PAGE_SIZE = 100

SCAN_INTERVAL = timedelta(seconds=30)
VEHICLE_SCAN_INTERVAL = timedelta(seconds=30)
SKI_SCAN_INTERVAL = timedelta(minutes=10)
# These barely change intraday, so they're polled far less often.
AIR_QUALITY_SCAN_INTERVAL = timedelta(hours=1)
CARBON_FOOTPRINT_SCAN_INTERVAL = timedelta(hours=24)
ALERTS_SCAN_INTERVAL = timedelta(minutes=5)

# How far a live GTFS-RT predicted departure may drift from the static
# schedule and still be considered "the same" departure. The realtime feed
# doesn't share a trip_id with the static schedule (not exposed via this
# API), so departures are matched by (stop_id, closest time) instead; this
# bounds how large a mismatch that heuristic can produce.
REALTIME_MATCH_MAX_DELTA = timedelta(minutes=10)

ATTR_LINE = "line"
ATTR_LINE_COLOR = "line_color"
ATTR_LINE_TEXT_COLOR = "line_text_color"
ATTR_DESTINATION = "destination"
ATTR_DIRECTION = "direction"
ATTR_PLATFORM = "platform"
ATTR_STATION_NAME = "station_name"
ATTR_STATION_CODE = "station_code"
ATTR_NEXT_DEPARTURE = "next_departure"
ATTR_UPCOMING = "upcoming"
ATTR_REALTIME = "realtime"

ATTR_OPEN_FACILITIES = "open_facilities"
ATTR_TOTAL_FACILITIES = "total_facilities"
ATTR_TEMPERATURE = "temperature"
ATTR_WIND_SPEED = "wind_speed"
ATTR_ALERTS = "alerts"
ATTR_WEBCAM_URL = "webcam_url"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"

ATTR_NO2 = "no2"
ATTR_O3 = "o3"
ATTR_PM10 = "pm10"
ATTR_MONITORING_STATION = "monitoring_station"

ATTR_PARKING_FACILITIES = "parking_facilities"

ATTR_YEAR = "year"
ATTR_MOBILITY_EMISSIONS = "mobility_emissions_tco2e"
ATTR_TOURISM_EMISSIONS = "tourism_emissions_tco2e"
ATTR_EMISSIONS_BY_SCOPE = "emissions_by_scope"

FRONTEND_URL_BASE = "/fgc_static"
CARD_JS_FILENAME = "fgc-timetable-card.js"

# How long before a station's next scheduled departure to resume live
# realtime-feed/vehicle-position polling after a quiet (no-service) period.
QUIET_HOURS_RESUME_BUFFER = timedelta(minutes=5)
