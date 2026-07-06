"""Constants for the FGC integration."""
from datetime import timedelta

DOMAIN = "fgc"

CONF_API_KEY = "api_key"
CONF_STATIONS = "stations"
CONF_STATION_CODE = "station_code"
CONF_ENABLE_MAP = "enable_map"
CONF_ENABLE_SKI = "enable_ski"

API_BASE_URL = "https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets"
DATASET_SCHEDULE = "viajes-de-hoy"
DATASET_VEHICLE_POSITIONS = "posicionament-dels-trens"
DATASET_STOPS = "gtfs_stops"
DATASET_SKI_FACILITIES = "estat-obertura-equipaments-turistics-fgc"
DATASET_SKI_WEATHER = "meteo-tim"
DATASET_SKI_ALERTS = "avisos-i-alertes-de-tim"
DATASET_SKI_WEBCAMS = "webcams-actives-tim"

# Max rows the Opendatasoft Explore API allows per request.
API_PAGE_SIZE = 100

SCAN_INTERVAL = timedelta(seconds=30)
VEHICLE_SCAN_INTERVAL = timedelta(seconds=30)
SKI_SCAN_INTERVAL = timedelta(minutes=10)

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

ATTR_OPEN_FACILITIES = "open_facilities"
ATTR_TOTAL_FACILITIES = "total_facilities"
ATTR_TEMPERATURE = "temperature"
ATTR_WIND_SPEED = "wind_speed"
ATTR_ALERTS = "alerts"
ATTR_WEBCAM_URL = "webcam_url"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"

FRONTEND_URL_BASE = "/fgc_static"
CARD_JS_FILENAME = "fgc-timetable-card.js"
