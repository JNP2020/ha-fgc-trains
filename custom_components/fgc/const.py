"""Constants for the FGC integration."""
from datetime import timedelta

DOMAIN = "fgc"

CONF_API_KEY = "api_key"
CONF_STATIONS = "stations"
CONF_STATION_CODE = "station_code"
CONF_ENABLE_MAP = "enable_map"

API_BASE_URL = "https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets"
DATASET_SCHEDULE = "viajes-de-hoy"
DATASET_VEHICLE_POSITIONS = "posicionament-dels-trens"
DATASET_STOPS = "gtfs_stops"

# Max rows the Opendatasoft Explore API allows per request.
API_PAGE_SIZE = 100

SCAN_INTERVAL = timedelta(seconds=30)
VEHICLE_SCAN_INTERVAL = timedelta(seconds=30)

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

FRONTEND_URL_BASE = "/fgc_static"
CARD_JS_FILENAME = "fgc-timetable-card.js"
