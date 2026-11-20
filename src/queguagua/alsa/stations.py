"""ALSA stops: the shipped list, matched by name (accents and case ignored) or id.

ALSA's search box offers ~5,800 places. A city served by several stops also has a group entry, e.g.
"Madrid (Todas las paradas)" (id 90155), whose `stops` are the individual ones (Madrid Estación Sur 155,
Aeropuerto Madrid - Barajas T4 5555...). Both a group and a single stop can be searched.

The list ships with the CLI (src/alsa/data/stations.json). Only a name that matches nothing makes the CLI
ask ALSA for its current list (kept for a day in the cache dir); `alsa stations --refresh` asks directly.
"""

import difflib
import json
import re
import time
import unicodedata
from functools import lru_cache
from importlib import resources
from typing import Any

from . import cachefile, config
from .errors import UsageError

_CACHE_TTL = 86400


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("(todas las paradas)", " ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@lru_cache(maxsize=1)
def _shipped() -> list[dict]:
    data = json.loads(resources.files("queguagua.alsa").joinpath("data/stations.json").read_text(encoding="utf-8"))
    return data["stations"]


def _cached() -> list[dict] | None:
    data = cachefile.read_json(config.cache_dir() / "stations.json")
    if isinstance(data, dict) and time.time() - data.get("fetched_at", 0) < _CACHE_TTL:
        return data.get("stations")
    return None


def normalize_remote(items: list[dict]) -> list[dict]:
    out = []
    for x in items:
        pc = x.get("provincecountryName") or ""
        prov, sep, country = pc.rpartition(", ")
        if not sep:
            prov, country = pc, ""
        item: dict[str, Any] = {"id": str(x["id"]), "name": (x.get("name") or "").strip(),
                                "province": prov or None, "country": country or None}
        if x.get("stopsList"):
            item["stops"] = [{"id": str(s["id"]), "name": (s.get("name") or "").strip()} for s in x["stopsList"]]
        if "airport" in (x.get("icon") or ""):
            item["airport"] = True
        out.append(item)
    return out


def fetch_remote(client) -> list[dict]:
    payload = client.resource_json("/home", config.JOURNEY_SEARCH_PORTLET, "GetOriginsResourceCommand",
                                   params={"usualStations": "false"})
    if not isinstance(payload, list) or not payload:
        from .errors import ApiShapeError
        raise ApiShapeError("ALSA's stop list came back empty or in a new shape")
    stations = normalize_remote(payload)
    cachefile.write_json(config.cache_dir() / "stations.json", {"fetched_at": time.time(), "stations": stations})
    return stations


def destinations(client, origin_id: str) -> list[dict]:
    """Places reachable from `origin_id` (ALSA's own list for the destination box)."""
    payload = client.resource_json("/home", config.JOURNEY_SEARCH_PORTLET, "GetDestinationsResourceCommand",
                                   params={"usualStations": "false", "originStationId": origin_id})
    return normalize_remote(payload if isinstance(payload, list) else [])


def _entries(stations: list[dict]) -> list[dict]:
    """Groups and their child stops, flattened (a child keeps a pointer to its group)."""
    out = []
    seen = set()
    for s in stations:
        group = bool(s.get("stops"))
        out.append({**s, "group": group})
        seen.add(s["id"])
    for s in stations:
        for child in s.get("stops") or []:
            if child["id"] in seen:
                continue
            seen.add(child["id"])
            out.append({"id": child["id"], "name": child["name"], "province": s.get("province"),
                        "country": s.get("country"), "group": False, "in_group": s["id"]})
    return out


def public(entry: dict) -> dict:
    out = {"id": entry["id"], "name": entry["name"], "province": entry.get("province"),
           "country": entry.get("country"), "group": entry.get("group", False)}
    if entry.get("stops"):
        out["stops"] = entry["stops"]
    if entry.get("in_group"):
        out["in_group"] = entry["in_group"]
    if entry.get("airport"):
        out["airport"] = True
    return out


def _score(q: str, entry: dict) -> float:
    name = fold(entry["name"])
    if not q:
        return 0.0
    if name == q:
        return 100.0 + (5 if entry.get("group") else 0)
    if name.startswith(q + " ") or name.startswith(q):
        return 80.0 + (5 if entry.get("group") else 0) - len(name) / 100
    words = q.split()
    if all(w in name.split() or any(t.startswith(w) for t in name.split()) for w in words):
        return 60.0 + (3 if entry.get("group") else 0) - len(name) / 100
    if q in name:
        return 40.0 - len(name) / 100
    return 0.0


def search(query: str, stations: list[dict] | None = None, limit: int = 10) -> list[dict]:
    entries = _entries(stations or _cached() or _shipped())
    q = query.strip()
    if q.isdigit():
        return [public(e) for e in entries if e["id"] == q][:1]
    fq = fold(q)
    scored = [(s, e) for e in entries if (s := _score(fq, e)) > 0]
    scored.sort(key=lambda t: (-t[0], t[1]["name"]))
    return [public(e) for _, e in scored[:limit]]


def suggestions(query: str, limit: int = 5) -> list[str]:
    names = sorted({e["name"] for e in _entries(_cached() or _shipped())})
    folded = {fold(n): n for n in names}
    return [folded[m] for m in difflib.get_close_matches(fold(query), list(folded), n=limit, cutoff=0.6)]


def resolve(query: str, client=None) -> dict:
    """The best stop or group for `query`; asks ALSA's live list only if the shipped one has no match."""
    found = search(query, limit=1)
    if not found and client is not None and not query.strip().isdigit():
        try:
            found = search(query, fetch_remote(client), limit=1)
        except Exception:
            found = []
    if not found:
        raise UsageError(f"unknown stop {query!r}", details={"suggestions": suggestions(query)})
    return found[0]
