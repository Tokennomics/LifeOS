"""OpenStreetMap via Overpass — the third places, from a map the world maintains.

`/seeding/third-places-directory` reported "160 Verified Third Places Ingested" with a
breakdown down to 42 specialty coffee workspaces and 24 sunset viewpoints, and a
`live_status` claiming opening hours and wi-fi speeds were verified. Nothing was ingested,
nothing was verified, and the same numbers came back for every city on earth.

The real version is OpenStreetMap. It is the only source of this data that needs no key, no
contract and no per-request billing, and it already contains exactly the categories the app
cares about — cafés, climbing walls, viewpoints, parks, libraries, dog parks, trailheads —
because those are the things people map.

Two things this module takes seriously, because Overpass is a volunteer-run service:

- **It asks for one bounded area at a time**, with a timeout in the query itself and a hard
  element cap. An unbounded Overpass query is how a public instance ends up rate-limiting
  everybody, and the etiquette here is the same as the `min_interval_minutes` on feed sync.
- **It never invents an attribute.** A place with no opening hours comes back with no
  opening hours. The old endpoint's "Live Opening Hours & Wi-Fi Speeds Verified" is exactly
  the claim OSM cannot support, so it is not made: what is tagged is reported, and what is
  not tagged is absent rather than defaulted.

**Not verified against the live API** — this sandbox's network policy answers 403 to the
CONNECT, same as for Ticketmaster and Open-Meteo. Parsing is written against the documented
Overpass JSON shape and exercised on fixtures. A failure is a status, never a crash.
"""

NAME = "overpass"
KIND = "places"
ENV_VAR = ""                      # no key exists for Overpass

BASE = "https://overpass-api.de/api/interpreter"
TIMEOUT_S = 25
MAX_ELEMENTS = 200
DEFAULT_RADIUS_M = 4000

# What the app actually recommends, mapped to how OSM tags it. Kept small and specific on
# purpose: a query for every amenity in a city is both rude to the server and useless to a
# person deciding where to spend an afternoon.
CATEGORIES = {
    "coffee": [('amenity', 'cafe')],
    "climbing": [('leisure', 'sports_centre'), ('sport', 'climbing')],
    "viewpoint": [('tourism', 'viewpoint')],
    "park": [('leisure', 'park')],
    "library": [('amenity', 'library')],
    "gallery": [('tourism', 'gallery')],
    "market": [('amenity', 'marketplace')],
    "trail": [('route', 'hiking')],
    "swim": [('leisure', 'swimming_area')],
    "sauna": [('leisure', 'sauna')],
}


def configured() -> bool:
    return True


def categories() -> list[str]:
    return sorted(CATEGORIES)


def build_query(lat: float, lon: float, category: str,
                radius_m: int = DEFAULT_RADIUS_M) -> str:
    """The Overpass QL for one category around one point.

    `nwr` rather than `node` because a park is a way and a market is often a relation;
    asking only for nodes is how a query for parks returns almost nothing and looks like the
    city has none. `out center` collapses each to a single coordinate so the caller does not
    have to reason about geometry.
    """
    clauses = CATEGORIES.get(str(category or "").strip().lower())
    if not clauses:
        raise ValueError(f"unknown category {category!r} (known: {categories()})")
    radius = max(100, min(int(radius_m), 20000))
    parts = "".join(
        f'nwr(around:{radius},{float(lat)},{float(lon)})["{key}"="{value}"];'
        for key, value in clauses)
    return f"[out:json][timeout:{TIMEOUT_S}];({parts});out center {MAX_ELEMENTS};"


def _tag(tags: dict, key: str, cap: int = 120) -> str:
    return str((tags or {}).get(key) or "").strip()[:cap]


def normalise(payload: dict, category: str = "") -> list[dict]:
    """Overpass JSON -> places.

    An element with no name is skipped rather than labelled "Unnamed cafe": a directory of
    unnamed dots is not a directory, and inventing a label is the failure this replaces.
    """
    elements = (payload or {}).get("elements") or []
    if not isinstance(elements, list):
        return []

    out = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        name = _tag(tags, "name", 120)
        if not name:
            continue
        centre = element.get("center") or {}
        lat = element.get("lat", centre.get("lat"))
        lon = element.get("lon", centre.get("lon"))
        if lat is None or lon is None:
            continue
        place = {
            "osm_id": f"{element.get('type', 'node')}/{element.get('id', '')}",
            "name": name,
            "category": str(category or "")[:40],
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
        }
        # Present only when OSM actually has it. No defaults, no "verified" claims.
        for field, key in (("opening_hours", "opening_hours"), ("website", "website"),
                           ("street", "addr:street"), ("wheelchair", "wheelchair")):
            value = _tag(tags, key, 200)
            if value:
                place[field] = value
        out.append(place)
    return out


def search(lat: float, lon: float, category: str, radius_m: int = DEFAULT_RADIUS_M,
           *, fetch=None) -> dict:
    """One category around one point. Never raises."""
    try:
        query = build_query(lat, lon, category, radius_m)
    except ValueError as exc:
        return {"status": "bad_category", "items": [], "detail": str(exc)}
    try:
        payload = (fetch or _fetch)(BASE, query)
    except Exception as exc:
        return {"status": f"fetch failed: {type(exc).__name__}", "items": []}
    return {"status": "ok", "items": normalise(payload, category)}


def _fetch(url: str, query: str) -> dict:
    import json
    import urllib.parse
    import urllib.request

    from substrate import safefetch

    safefetch.check_url(url)
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": "LifeOS/1.0 (+https://github.com/Tokennomics/LifeOS)",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_S + 10) as response:
        return json.loads(response.read(safefetch.MAX_BYTES).decode("utf-8", "replace"))
