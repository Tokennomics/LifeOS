"""Open-Meteo — weather, sea state and where a city is. No key, ever.

The repo's oldest rule is "every feature works with no API key and improves with one", and
until now the no-key tier meant *nothing external at all*. That is why `/weather/radar`
listed a 2.2 m swell and 45 cm of fresh powder as constants, and why the ski and surf
matchers had to report conditions as unavailable: there was no source, so the choice was an
invented number or a blank.

Open-Meteo is the source that removes that choice. It is free for non-commercial use, needs
no registration, and covers the three things this app actually asks about:

- **Geocoding** — a city name to a coordinate, so nothing here needs a hardcoded lat/lon
  table. (The old `live-external-api-ingest` had exactly two cities in an if/else.)
- **Forecast** — temperature, wind, cloud, precipitation, sunset. Enough to say whether
  tonight is a rooftop night.
- **Marine** — wave height and period, which is the difference between "surf match" meaning
  something and meaning nothing.

**Not verified against the live API.** Same honest caveat as the Ticketmaster provider:
nothing in this sandbox can reach api.open-meteo.com — the network policy answers 403 to the
CONNECT. The parsing is written from the documented response shapes and exercised against
fixtures of that shape. The failure mode is a recorded status and an empty result, never a
crash and never a number nobody measured.

There is no `configured()` gate because there is nothing to configure. `status` is still
reported per call so a caller can tell "the sea is flat" from "we could not ask".
"""

NAME = "openmeteo"
KIND = "weather"
ENV_VAR = ""                      # deliberately none: no key exists to set

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE = "https://marine-api.open-meteo.com/v1/marine"

MAX_PLACES = 5


def configured() -> bool:
    """Always on. Kept so the provider registry has one interface rather than two."""
    return True


def _num(value):
    """A number or None — never a default. A missing wind speed must not read as 0 km/h,
    which is a specific and plausible-looking claim about a calm day."""
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _fetch(url: str, params: dict) -> dict:
    from substrate import safefetch
    return safefetch.fetch_json(url, params)


def geocode(city: str, *, fetch=None) -> dict:
    """Where a city is. Never raises — an unreachable geocoder is a status."""
    city = str(city or "").strip()
    if not city:
        return {"status": "no_city", "places": []}
    try:
        payload = (fetch or _fetch)(GEOCODE, {"name": city, "count": MAX_PLACES,
                                              "format": "json"})
    except Exception as exc:
        return {"status": f"fetch failed: {type(exc).__name__}", "places": []}

    results = (payload or {}).get("results") or []
    places = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        lat, lon = _num(item.get("latitude")), _num(item.get("longitude"))
        if lat is None or lon is None:
            continue
        places.append({"name": str(item.get("name") or "")[:80],
                       "country": str(item.get("country") or "")[:80],
                       "admin": str(item.get("admin1") or "")[:80],
                       "lat": lat, "lon": lon,
                       "timezone": str(item.get("timezone") or "")[:60]})
    return {"status": "ok" if places else "not_found", "places": places}


_CURRENT = "temperature_2m,apparent_temperature,wind_speed_10m,cloud_cover,precipitation"
_DAILY = "sunrise,sunset,temperature_2m_max,precipitation_probability_max"


def forecast(lat: float, lon: float, *, fetch=None) -> dict:
    """Now and today. Every field is independently optional, because a partial response is
    normal and a partial answer is still useful."""
    try:
        payload = (fetch or _fetch)(FORECAST, {
            "latitude": lat, "longitude": lon, "current": _CURRENT, "daily": _DAILY,
            "timezone": "auto", "forecast_days": 2})
    except Exception as exc:
        return {"status": f"fetch failed: {type(exc).__name__}"}

    current = (payload or {}).get("current") or {}
    daily = (payload or {}).get("daily") or {}

    def first(key):
        values = daily.get(key)
        return values[0] if isinstance(values, list) and values else None

    return {
        "status": "ok",
        "observed_at": str(current.get("time") or "")[:40],
        "temp_c": _num(current.get("temperature_2m")),
        "feels_like_c": _num(current.get("apparent_temperature")),
        "wind_kmh": _num(current.get("wind_speed_10m")),
        "cloud_pct": _num(current.get("cloud_cover")),
        "precipitation_mm": _num(current.get("precipitation")),
        "sunrise": str(first("sunrise") or "")[:40],
        "sunset": str(first("sunset") or "")[:40],
        "high_c": _num(first("temperature_2m_max")),
        "rain_chance_pct": _num(first("precipitation_probability_max")),
    }


def marine(lat: float, lon: float, *, fetch=None) -> dict:
    """Sea state. Inland coordinates legitimately return nothing, which is `no_data` and
    not an error — the honest answer for a surf match in Munich."""
    try:
        payload = (fetch or _fetch)(MARINE, {
            "latitude": lat, "longitude": lon,
            "current": "wave_height,wave_period,wave_direction", "timezone": "auto"})
    except Exception as exc:
        return {"status": f"fetch failed: {type(exc).__name__}"}

    current = (payload or {}).get("current") or {}
    height = _num(current.get("wave_height"))
    if height is None:
        return {"status": "no_data",
                "detail": "no marine forecast for this coordinate (inland, most likely)"}
    return {
        "status": "ok",
        "observed_at": str(current.get("time") or "")[:40],
        "wave_height_m": height,
        "wave_period_s": _num(current.get("wave_period")),
        "wave_direction_deg": _num(current.get("wave_direction")),
    }
