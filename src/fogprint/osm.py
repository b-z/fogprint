"""Fetch lines from OpenStreetMap (Overpass API) as GeoJSON."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .regions import UA

ENDPOINTS = [
    os.environ.get("FOGPRINT_OVERPASS", ""),
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

PRESETS = {
    # railway routes as relations keep line names ("JR 中央線") together
    "rail": 'relation["type"="route"]["route"~"^(train|railway)$"]',
    "subway": 'relation["type"="route"]["route"~"^(subway|light_rail|tram|monorail)$"]',
    "railway-tracks": 'way["railway"~"^(rail|light_rail|subway|narrow_gauge|monorail)$"]["service"!~"."]',
    "motorway": 'way["highway"~"^(motorway|trunk)$"]',
    "major-roads": 'way["highway"~"^(motorway|trunk|primary)$"]',
    "roads": 'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]',
    "streets": 'way["highway"~"^(primary|secondary|tertiary|unclassified|residential|living_street|pedestrian)$"]',
    "cycleways": 'way["highway"="cycleway"]',
    "hiking": 'relation["type"="route"]["route"="hiking"]',
    "ferry": 'way["route"="ferry"]',
}


def query(preset: str | None, bbox, custom: str | None = None, timeout: int = 180) -> dict:
    """Run an Overpass query for a (west, south, east, north) box and return
    GeoJSON LineStrings with name / ref / operator properties."""
    w, s, e, n = bbox
    sel = custom or PRESETS[preset]
    q = f"[out:json][timeout:{timeout}];({sel}({s},{w},{n},{e}););out geom;"
    data = None
    errors = []
    for url in [u for u in ENDPOINTS if u]:
        try:
            body = urllib.parse.urlencode({"data": q}).encode()
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout + 30) as r:
                data = json.loads(r.read())
            break
        except OSError as ex:
            errors.append(f"{url}: {ex}")
    if data is None:
        raise OSError("Overpass API unreachable or busy (try again later, a smaller area, or another server via "
                      "FOGPRINT_OVERPASS): " + "; ".join(errors))
    return to_geojson(data)


def _props(tags: dict) -> dict:
    keep = ("name", "name:en", "name:ja", "name:zh", "ref", "operator", "network", "route", "highway", "railway")
    p = {k: tags[k] for k in keep if k in tags}
    p.setdefault("name", tags.get("ref", ""))
    return p


def to_geojson(data: dict) -> dict:
    feats = []
    for el in data.get("elements", []):
        if el["type"] == "way" and "geometry" in el:
            feats.append({"type": "Feature", "properties": _props(el.get("tags", {})),
                          "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in el["geometry"]]}})
        elif el["type"] == "relation":
            roles = ("", "route", "forward", "backward", "main")
            lines = [[[p["lon"], p["lat"]] for p in m["geometry"]] for m in el.get("members", [])
                     if m.get("type") == "way" and m.get("geometry") and m.get("role", "") in roles]
            if lines:
                feats.append({"type": "Feature", "properties": _props(el.get("tags", {})),
                              "geometry": {"type": "MultiLineString", "coordinates": lines}})
    return {"type": "FeatureCollection", "features": feats}
