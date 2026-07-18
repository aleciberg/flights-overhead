"""
OpenSky Network flight fetcher for Portland / Vancouver, OR area.

Environment:
  SIMULATE=true        Inject fake flights — no network, no hardware required.
  COMMERCIAL_ONLY=true Drop flights without a recognized airline callsign
                        (filters out GA/private/training traffic).
"""

import os
import math
import time
import random
import requests
from dataclasses import dataclass
from typing import Optional, Tuple, List

import enrichment
import opensky_auth

PORTLAND_LAT  = 45.5051
ENRICH_LIMIT  = 12   # only enrich the closest N flights to avoid rate-limiting
PORTLAND_LON = -122.6750

# ~75-mile bounding box around Portland
BBOX = {
    "lamin": 44.40,
    "lomin": -124.30,
    "lamax": 46.60,
    "lomax": -121.00,
}

OPENSKY_URL = "https://opensky-network.org/api/states/all"

SIMULATE: bool = os.getenv("SIMULATE", "false").lower() in ("1", "true", "yes")
COMMERCIAL_ONLY: bool = os.getenv("COMMERCIAL_ONLY", "false").lower() in ("1", "true", "yes")


def _filter_commercial(flights: List["Flight"]) -> List["Flight"]:
    return [f for f in flights if enrichment.get_airline(f.callsign)]


@dataclass
class Flight:
    icao24: str
    callsign: str
    origin_country: str
    latitude: float
    longitude: float
    altitude_ft: Optional[float]
    speed_kts: Optional[float]
    heading: Optional[float]
    vertical_rate_fpm: Optional[float]
    on_ground: bool
    distance_mi: float
    last_contact: int
    # enriched fields — populated after initial parse
    route: Optional[Tuple[str, Optional[str]]] = None  # (dep, arr_or_None)
    aircraft_type: Optional[str] = None
    airline: Optional[str] = None                      # from ICAO callsign prefix, instant


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_state(state: list) -> Optional[Flight]:
    lat, lon = state[6], state[5]
    if lat is None or lon is None:
        return None
    alt_m  = state[7]
    spd_ms = state[9]
    vr_ms  = state[11]
    return Flight(
        icao24=state[0],
        callsign=(state[1] or "").strip() or state[0].upper(),
        origin_country=state[2] or "",
        latitude=lat,
        longitude=lon,
        altitude_ft=alt_m * 3.28084 if alt_m is not None else None,
        speed_kts=spd_ms * 1.94384 if spd_ms is not None else None,
        heading=state[10],
        vertical_rate_fpm=vr_ms * 196.85 if vr_ms is not None else None,
        on_ground=bool(state[8]),
        distance_mi=haversine_mi(PORTLAND_LAT, PORTLAND_LON, lat, lon),
        last_contact=state[4] or 0,
    )


def _enrich(flight: Flight, fr24_routes: dict) -> None:
    flight.airline       = enrichment.get_airline(flight.callsign)
    flight.aircraft_type = enrichment.get_aircraft_type(flight.icao24)
    flight.route         = fr24_routes.get(flight.callsign) or enrichment.get_flight_route(flight.callsign)


def fetch_flights() -> List[Flight]:
    if SIMULATE:
        flights = _fake_flights()
        return _filter_commercial(flights) if COMMERCIAL_ONLY else flights

    headers = opensky_auth.auth_headers()

    resp = requests.get(OPENSKY_URL, params={**BBOX, "time": 0}, headers=headers, timeout=10)
    resp.raise_for_status()
    states = resp.json().get("states") or []

    flights = [f for s in states if (f := _parse_state(s)) and not f.on_ground]
    if COMMERCIAL_ONLY:
        flights = _filter_commercial(flights)
    flights.sort(key=lambda f: f.distance_mi)

    # One bounded FR24 query covers routes for every flight in the box (see
    # enrichment.get_fr24_routes); only flights it misses fall through to the
    # slower per-callsign lookups inside _enrich.
    fr24_routes = enrichment.get_fr24_routes(BBOX)

    # Enrich closest flights only — sequential with a pause to respect rate limits.
    # Each icao24/callsign is only re-fetched once its cache TTL expires, so
    # steady-state load is very low even with many flights in the area.
    for flight in flights[:ENRICH_LIMIT]:
        _enrich(flight, fr24_routes)
        time.sleep(1)

    return flights


# ---------------------------------------------------------------------------
# Fake flight data — realistic Portland-area traffic mix
# ---------------------------------------------------------------------------

_FAKE: list = [
    {
        "callsign": "UAL412",  "country": "United States",
        "lat": 45.62, "lon": -122.80, "alt_ft": 35000, "spd_kts": 480,
        "hdg": 270, "vr_fpm": -200,
        "route": ("Portland", "San Francisco"),
        "type": "Boeing 737-900", "airline": "United Airlines",
    },
    {
        "callsign": "DAL891",  "country": "United States",
        "lat": 45.30, "lon": -122.45, "alt_ft": 28000, "spd_kts": 420,
        "hdg": 135, "vr_fpm": -800,
        "route": ("Seattle", "Los Angeles"),
        "type": "Boeing 757-200",
    },
    {
        "callsign": "AAL123",  "country": "United States",
        "lat": 45.70, "lon": -122.20, "alt_ft": 31000, "spd_kts": 510,
        "hdg": 195, "vr_fpm": 0,
        "route": ("Portland", "Dallas/FW"),
        "type": "Airbus A321",
    },
    {
        "callsign": "SWA667",  "country": "United States",
        "lat": 45.45, "lon": -123.10, "alt_ft": 18000, "spd_kts": 380,
        "hdg": 300, "vr_fpm": -1200,
        "route": ("Oakland", "Seattle"),
        "type": "Boeing 737-800",
    },
    {
        "callsign": "ASA244",  "country": "United States",
        "lat": 45.55, "lon": -121.90, "alt_ft": 22000, "spd_kts": 350,
        "hdg": 90, "vr_fpm": 400,
        "route": ("Portland", "Denver"),
        "type": "Boeing 737 MAX 9",
    },
    {
        "callsign": "WN2341",  "country": "United States",
        "lat": 45.80, "lon": -122.50, "alt_ft": 9500,  "spd_kts": 280,
        "hdg": 220, "vr_fpm": -2200,
        "route": ("Seattle", "Oakland"),
        "type": "Boeing 737-700",
    },
    {
        "callsign": "AFR876",  "country": "France",
        "lat": 45.20, "lon": -123.50, "alt_ft": 39000, "spd_kts": 540,
        "hdg": 55, "vr_fpm": 100,
        "route": ("Los Angeles", "Paris CDG"),
        "type": "Boeing 777-300ER",
    },
    {
        "callsign": "BAW291",  "country": "United Kingdom",
        "lat": 46.10, "lon": -122.30, "alt_ft": 37000, "spd_kts": 530,
        "hdg": 75, "vr_fpm": 0,
        "route": ("Seattle", "London Heathrow"),
        "type": "Boeing 787-9",
    },
    {
        "callsign": "QXE3491", "country": "United States",
        "lat": 45.50, "lon": -122.90, "alt_ft": 8200,  "spd_kts": 245,
        "hdg": 180, "vr_fpm": -1500,
        "route": ("Seattle", "Medford"),
        "type": "Embraer 175",
    },
    {
        "callsign": "SKW5512", "country": "United States",
        "lat": 45.35, "lon": -121.70, "alt_ft": 14000, "spd_kts": 310,
        "hdg": 320, "vr_fpm": 600,
        "route": ("San Francisco", "Portland"),
        "type": "Embraer 175",
    },
    {
        "callsign": "FDX1234", "country": "United States",
        "lat": 45.65, "lon": -123.30, "alt_ft": 7800,  "spd_kts": 290,
        "hdg": 10, "vr_fpm": -800,
        "route": ("Oakland", "Portland"),
        "type": "Boeing 767-300F",
    },
    {
        "callsign": "UPS445",  "country": "United States",
        "lat": 45.42, "lon": -122.60, "alt_ft": 12500, "spd_kts": 330,
        "hdg": 240, "vr_fpm": -600,
        "route": ("Portland", "Oakland"),
        "type": "Boeing 757-200F",
    },
]


def _fake_flights() -> List[Flight]:
    now = int(time.time())
    flights = []
    for d in _FAKE:
        lat = d["lat"] + random.uniform(-0.02, 0.02)
        lon = d["lon"] + random.uniform(-0.02, 0.02)
        flights.append(Flight(
            icao24=d["callsign"][:6].lower(),
            callsign=d["callsign"],
            origin_country=d["country"],
            latitude=lat,
            longitude=lon,
            altitude_ft=d["alt_ft"] + random.uniform(-80, 80),
            speed_kts=d["spd_kts"] + random.uniform(-8, 8),
            heading=d["hdg"],
            vertical_rate_fpm=d["vr_fpm"] + random.uniform(-50, 50),
            on_ground=False,
            distance_mi=haversine_mi(PORTLAND_LAT, PORTLAND_LON, lat, lon),
            last_contact=now,
            route=d["route"],
            aircraft_type=d["type"],
            airline=enrichment.get_airline(d["callsign"]),
        ))
    flights.sort(key=lambda f: f.distance_mi)
    return flights
