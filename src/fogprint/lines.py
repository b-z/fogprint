"""Coverage of lines (roads, railways, planned routes, GPX tracks)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import geo
from .fogmap import FogMap


def read_lines(path: str) -> list[dict]:
    """Read LineStrings from GeoJSON, GPX or KML. Returns
    [{"coords": [(lng, lat), ...], "props": {...}}]."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suf = p.suffix.lower()
    if suf in (".geojson", ".json"):
        return _geojson_lines(json.loads(text))
    if suf == ".gpx":
        return _gpx_lines(text)
    if suf == ".kml":
        return _kml_lines(text)
    raise ValueError("supported formats: .geojson/.json, .gpx, .kml")


def _geojson_lines(data) -> list[dict]:
    feats = data["features"] if data.get("type") == "FeatureCollection" else [data]
    out = []
    for f in feats:
        g = f.get("geometry") if f.get("type") == "Feature" else f
        props = f.get("properties") or {}
        if not g:
            continue
        if g["type"] == "LineString":
            out.append({"coords": g["coordinates"], "props": props})
        elif g["type"] == "MultiLineString":
            for c in g["coordinates"]:
                out.append({"coords": c, "props": props})
        elif g["type"] in ("Polygon", "MultiPolygon"):
            rings = g["coordinates"] if g["type"] == "Polygon" else [r for poly in g["coordinates"] for r in poly]
            for c in rings:
                out.append({"coords": c, "props": props})
    return out


def _strip(tag):
    return tag.rsplit("}", 1)[-1]


def _gpx_lines(text) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for el in root.iter():
        t = _strip(el.tag)
        if t in ("trk", "rte"):
            name = next((c.text for c in el if _strip(c.tag) == "name"), None)
            segs = [s for s in el if _strip(s.tag) == "trkseg"] or [el]
            for s in segs:
                pts = [(float(p.get("lon")), float(p.get("lat"))) for p in s if _strip(p.tag) in ("trkpt", "rtept")]
                if len(pts) >= 2:
                    out.append({"coords": pts, "props": {"name": name or ""}})
    return out


def _kml_lines(text) -> list[dict]:
    root = ET.fromstring(text)
    out = []
    for pm in root.iter():
        if _strip(pm.tag) != "Placemark":
            continue
        name = next((c.text for c in pm.iter() if _strip(c.tag) == "name"), "") or ""
        for el in pm.iter():
            t = _strip(el.tag)
            if t == "coordinates" and el.text:
                pts = []
                for tok in el.text.split():
                    v = tok.split(",")
                    if len(v) >= 2:
                        pts.append((float(v[0]), float(v[1])))
                if len(pts) >= 2:
                    out.append({"coords": pts, "props": {"name": name}})
        track = [c.text for c in pm.iter() if _strip(c.tag) == "coord" and c.text]
        if len(track) >= 2:
            pts = [(float(v.split()[0]), float(v.split()[1])) for v in track]
            out.append({"coords": pts, "props": {"name": name}})
    return out


def densify(coords, step_m: float):
    """Points every `step_m` along a polyline, plus cumulative distance."""
    c = np.asarray(coords, float)[:, :2]
    if len(c) < 2:
        return c, np.zeros(len(c))
    seg = geo.haversine_m(c[:-1, 0], c[:-1, 1], c[1:, 0], c[1:, 1])
    pts, dist = [c[:1]], [np.zeros(1)]
    cum = 0.0
    for i, L in enumerate(seg):
        k = max(1, int(np.ceil(L / step_m)))
        t = np.arange(1, k + 1) / k
        pts.append(c[i] + (c[i + 1] - c[i]) * t[:, None])
        dist.append(cum + L * t)
        cum += L
    return np.concatenate(pts), np.concatenate(dist)


def coverage(fog: FogMap, lines: list[dict], group_by: str | None = "name", step_m: float = 50,
             tolerance_m: float = 60, min_gap_m: float = 300) -> list[dict]:
    """Explored share of each line (or group of lines), with the unexplored
    stretches longer than `min_gap_m`."""
    groups = defaultdict(list)
    for i, ln in enumerate(lines):
        key = str(ln["props"].get(group_by, "")) if group_by else str(i)
        groups[key].append(ln)
    res = []
    for key, lns in groups.items():
        total = explored = 0.0
        gaps = []
        for ln in lns:
            pts, dist = densify(ln["coords"], step_m)
            if len(pts) < 2:
                continue
            ok = fog.near_explored(pts[:, 0], pts[:, 1], tolerance_m)
            seglen = np.diff(dist)
            segok = ok[:-1] & ok[1:]
            total += float(seglen.sum())
            explored += float(seglen[segok].sum())
            # runs of unexplored samples
            bad = ~ok
            i = 0
            n = len(bad)
            while i < n:
                if not bad[i]:
                    i += 1
                    continue
                j = i
                while j + 1 < n and bad[j + 1]:
                    j += 1
                a, b = max(0, i - 1), min(n - 1, j + 1)
                L = float(dist[b] - dist[a])
                if L >= min_gap_m:
                    sub = pts[a:b + 1]
                    if len(sub) > 60:
                        sub = sub[np.linspace(0, len(sub) - 1, 60).astype(int)]
                    gaps.append({"km": round(L / 1000, 2), "from": [round(float(pts[a, 0]), 5), round(float(pts[a, 1]), 5)],
                                 "to": [round(float(pts[b, 0]), 5), round(float(pts[b, 1]), 5)],
                                 "coords": [[round(float(x), 5), round(float(y), 5)] for x, y in sub]})
                i = j + 1
        if total == 0:
            continue
        gaps.sort(key=lambda g: -g["km"])
        props = lns[0]["props"]
        res.append({
            "name": key if group_by else str(props.get("name", key)),
            "ref": props.get("ref", ""),
            "length_km": round(total / 1000, 2), "explored_km": round(explored / 1000, 2),
            "explored_pct": round(100 * explored / total, 1),
            "unexplored_km": round((total - explored) / 1000, 2),
            "gaps": gaps,
        })
    res.sort(key=lambda r: -r["unexplored_km"])
    return res


def gaps_geojson(results: list[dict]) -> dict:
    feats = []
    for r in results:
        for g in r["gaps"]:
            feats.append({"type": "Feature", "properties": {"name": r["name"], "km": g["km"]},
                          "geometry": {"type": "LineString", "coordinates": g["coords"]}})
    return {"type": "FeatureCollection", "features": feats}
