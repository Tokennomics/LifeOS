"""What it is actually like outside, and what that makes worth doing.

Three places in this app asserted weather nobody had measured. `/weather/radar` returned a
2.2 m swell at a 14 s period, 45 cm of fresh snowfall and a clear 24 °C sky — as constants,
in July, in Lisbon, for every caller. `/synergy/surf-match` and `/synergy/ski-match` carried
the same numbers into a match. `/seeding/weather-tide-triggers` branched on the word
"munich" in the request and returned a hand-written list of Isar river-surf telemetry.

Those were removed rather than fixed, because there was no source. Open-Meteo is the source,
so they can come back as measurements.

Two rules make this different from what it replaces:

- **A missing reading is missing, not zero.** Every field can be `None`, and a trigger that
  depends on a field it does not have simply does not fire. "Wind: 0 km/h" is a specific
  claim about a still day and is exactly the kind of plausible default that made the old
  version believable.
- **A trigger states its threshold.** "Good surf" is an opinion; "wave height 1.4 m, which
  is over the 1.0 m this fires at" is a reading plus a rule the reader can disagree with.
  The old triggers asserted `PRIME CONDITIONS` with nothing behind them.

Readings are cached in the graph per city so a screen that four people open in a minute is
four reads and one fetch — Open-Meteo is free and the way to keep it that way is to not
hammer it.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat, places
from modules.feeds.providers import openmeteo

MODULE = "city.conditions"
SCOPES = {"content:read", "content:write"}
RECORD = "city_conditions"

CACHE_MINUTES = 30

# Every threshold in one place, so a trigger can quote the rule it fired on.
THRESHOLDS = {
    "surf_wave_m": 0.8,
    "clear_sky_max_cloud_pct": 35.0,
    "warm_enough_c": 18.0,
    "dry_max_rain_chance_pct": 30.0,
    "windy_kmh": 30.0,
}


class ConditionsError(ValueError):
    """A city we cannot get conditions for."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _cached(graph: Graph, room: str):
    for row in _sys(graph).find_entities("content", {"type": RECORD, "city": room},
                                         limit=1):
        fetched = _parse(row["attrs"].get("fetched_at", ""))
        if fetched and _now() - fetched < datetime.timedelta(minutes=CACHE_MINUTES):
            return row
    return None


def _store(graph: Graph, room: str, label: str, payload: dict, source: str) -> None:
    session = _sys(graph)
    attrs = {"type": RECORD, "city": room, "city_label": label,
             "fetched_at": now_iso(), **payload}
    existing = session.find_entities("content", {"type": RECORD, "city": room}, limit=1)
    if existing:
        session.update_entity(existing[0]["id"], attrs, source=source)
    else:
        session.create_entity("content", attrs, source=source, owner_id=SYSTEM_OWNER)


def read(graph: Graph, city: str, *, refresh: bool = False, geocode_fetch=None,
         forecast_fetch=None, marine_fetch=None, source: str = MODULE) -> dict:
    """Current conditions for a city, cached for `CACHE_MINUTES`.

    Marine is asked for every coastal-or-not city and `no_data` inland is the expected
    answer, not a failure — it is how "there is no surf in Munich" gets said truthfully
    rather than by a hardcoded city list.
    """
    if not str(city or "").strip():
        raise ConditionsError("which city?")
    room = chat.slug(city)
    label = str(city).strip()[:80]

    if not refresh:
        hit = _cached(graph, room)
        if hit is not None:
            attrs = dict(hit["attrs"])
            attrs["cached"] = True
            return attrs

    where = places.locate(city, fetch=geocode_fetch)
    if where["status"] != "ok":
        return {"city": room, "city_label": label, "status": where["status"],
                "available": False,
                "detail": "could not place this city on the map"}

    weather = openmeteo.forecast(where["lat"], where["lon"], fetch=forecast_fetch)
    sea = openmeteo.marine(where["lat"], where["lon"], fetch=marine_fetch)

    payload = {
        "status": weather.get("status", "unknown"),
        "available": weather.get("status") == "ok",
        "lat": where["lat"], "lon": where["lon"],
        "resolved": where.get("resolved", ""),
        "weather": {k: v for k, v in weather.items() if k != "status"},
        "marine": {k: v for k, v in sea.items() if k != "status"},
        "marine_status": sea.get("status", "unknown"),
        "source": "open-meteo.com",
        "cached": False,
    }
    if payload["available"]:
        _store(graph, room, label, payload, source)
    return {"city": room, "city_label": label, **payload}


def _fires(name: str, ok: bool, reading: str, rule: str) -> dict | None:
    return {"trigger": name, "reading": reading, "rule": rule} if ok else None


def triggers(graph: Graph, city: str, **kw) -> dict:
    """Conditions turned into "tonight is worth doing X".

    Each entry carries the reading and the threshold, so it is checkable rather than
    asserted. A reading the API did not return produces no trigger at all — this is the one
    place where saying nothing is strictly better than guessing.
    """
    current = read(graph, city, **kw)
    if not current.get("available"):
        return {"city": current.get("city", ""), "available": False,
                "triggers": [], "status": current.get("status", "unknown"),
                "detail": current.get("detail", ""),
                "suggestion": "No weather source reachable, so nothing is claimed."}

    weather = current.get("weather") or {}
    marine = current.get("marine") or {}
    fired = []

    wave = marine.get("wave_height_m")
    if wave is not None:
        fired.append(_fires(
            "surf", wave >= THRESHOLDS["surf_wave_m"],
            f"wave height {wave} m", f">= {THRESHOLDS['surf_wave_m']} m"))

    cloud, temp = weather.get("cloud_pct"), weather.get("temp_c")
    if cloud is not None and weather.get("sunset"):
        fired.append(_fires(
            "sunset", cloud <= THRESHOLDS["clear_sky_max_cloud_pct"],
            f"{cloud}% cloud, sunset {weather['sunset'][-5:]}",
            f"<= {THRESHOLDS['clear_sky_max_cloud_pct']}% cloud"))

    rain = weather.get("rain_chance_pct")
    if temp is not None and rain is not None:
        fired.append(_fires(
            "outdoors",
            temp >= THRESHOLDS["warm_enough_c"] and rain <= THRESHOLDS["dry_max_rain_chance_pct"],
            f"{temp} °C, {rain}% chance of rain",
            f">= {THRESHOLDS['warm_enough_c']} °C and <= "
            f"{THRESHOLDS['dry_max_rain_chance_pct']}% rain"))

    wind = weather.get("wind_kmh")
    if wind is not None:
        fired.append(_fires(
            "indoors", wind >= THRESHOLDS["windy_kmh"],
            f"wind {wind} km/h", f">= {THRESHOLDS['windy_kmh']} km/h"))

    live = [f for f in fired if f]
    return {
        "city": current.get("city", ""), "city_label": current.get("city_label", ""),
        "available": True, "triggers": live,
        "weather": weather, "marine": marine, "marine_status": current.get("marine_status"),
        "source": "open-meteo.com",
        "suggestion": "" if live else (
            "Nothing stands out about the conditions right now — which is itself an answer, "
            "and not the same as no data."),
    }
