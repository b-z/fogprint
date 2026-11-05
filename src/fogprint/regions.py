"""Explored area per administrative region.

Boundary sources (downloaded once, cached under the cache folder):

* ``country`` / ``admin1``: Natural Earth 1:10m (public domain), whole world.
* ``geoboundaries``: geoBoundaries gbOpen (CC BY 4.0 or as stated per
  country), any country, levels ADM1..ADM5 where available; ADM2 is usually
  counties / municipalities.
* any GeoJSON file of polygons you provide.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import geo
from .fogmap import FogMap

UA = "fogprint (+https://github.com/b-z/fogprint)"
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
NE_FILES = {
    "country": "ne_10m_admin_0_countries.geojson",
    "admin1": "ne_10m_admin_1_states_provinces.geojson",
    "land": "ne_10m_land.geojson",
}


_LAND = None


def land_mask(lng, lat) -> np.ndarray:
    """True where a point is on land (Natural Earth 1:10m, so coarse:
    small islands, lakes and harbours are approximate)."""
    global _LAND
    import shapely

    if _LAND is None:
        from shapely.geometry import shape
        data = json.loads(natural_earth("land").read_text(encoding="utf-8"))
        geoms = []
        for f in data["features"]:
            g = shapely.make_valid(shape(f["geometry"]))
            # split huge continents into parts so the tree stays useful
            geoms += list(getattr(g, "geoms", [g]))
        _LAND = shapely.STRtree(geoms)
    pts = shapely.points(np.c_[np.atleast_1d(lng), np.atleast_1d(lat)])
    out = np.zeros(len(pts), bool)
    pi, _ = _LAND.query(pts, predicate="intersects")
    out[pi] = True
    return out
GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{level}/"


def cache_dir() -> Path:
    d = os.environ.get("FOGPRINT_CACHE")
    if d:
        p = Path(d).expanduser()
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "fogprint" / "cache"
    else:
        p = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fogprint"
    p.mkdir(parents=True, exist_ok=True)
    return p


def download(url: str, dest: Path, alternates: tuple[str, ...] = ()) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for u in (url, *alternates):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if data[:200].lstrip().startswith(b"version https://git-lfs"):
                raise OSError("got a Git LFS pointer instead of the file")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return dest
        except OSError as e:  # urllib errors are OSErrors
            last = e
    raise OSError(f"could not download {url}: {last}")


def _gh_alternates(url: str) -> tuple[str, ...]:
    # github.com/<o>/<r>/raw/<ref>/<path> is an LFS file in geoBoundaries;
    # media.githubusercontent.com serves the real content.
    if url.startswith("https://github.com/") and "/raw/" in url:
        o_r, _, rest = url[len("https://github.com/"):].partition("/raw/")
        return (f"https://media.githubusercontent.com/media/{o_r}/{rest}",)
    return ()


def natural_earth(level: str) -> Path:
    name = NE_FILES[level]
    return download(NE_BASE + name, cache_dir() / "naturalearth" / name)


def geoboundaries(iso3: str, level: str) -> tuple[Path, dict]:
    iso3, level = iso3.upper(), level.upper()
    meta_path = cache_dir() / "geoboundaries" / f"{iso3}-{level}.json"
    download(GB_API.format(iso=iso3, level=level), meta_path)
    meta = json.loads(meta_path.read_text())
    url = meta["simplifiedGeometryGeoJSON"]
    path = download(url, cache_dir() / "geoboundaries" / f"{iso3}-{level}.geojson", _gh_alternates(url))
    return path, meta


# -------------------------------------------------------------- name helpers
NE_NAME_FIELDS = {
    "en": ["NAME_EN", "name_en", "NAME", "name"],
    "zh": ["NAME_ZH", "name_zh", "NAME_ZHT", "name_zht", "NAME_EN", "name_en", "NAME", "name"],
    "ja": ["NAME_JA", "name_ja", "NAME_EN", "name_en", "NAME", "name"],
}


# Short common names where the source data uses a long formal one.
NAME_OVERRIDES = {"TWN": {"en": "Taiwan", "zh": "台湾", "ja": "台湾"}}


def pick_name(props: dict, lang: str, field: str | None = None) -> str:
    if field:
        return str(props.get(field, ""))
    a3 = props.get("ADM0_A3")
    if a3 in NAME_OVERRIDES and props.get("featurecla", "").startswith("Admin-0"):
        return NAME_OVERRIDES[a3].get(lang, NAME_OVERRIDES[a3]["en"])
    for k in NE_NAME_FIELDS.get(lang, []) + NE_NAME_FIELDS["en"] + ["shapeName", "NAME_1", "NAME_2", "nam", "N03_004"]:
        v = props.get(k)
        if v:
            return str(v)
    return ""


class Boundaries:
    def __init__(self, features: list[dict], name_field: str | None, lang: str, kind: str, attribution: str = ""):
        import shapely
        from shapely.geometry import shape

        self.kind = kind
        self.attribution = attribution
        self.features = []
        geoms = []
        for f in features:
            if not f.get("geometry"):
                continue
            g = shapely.make_valid(shape(f["geometry"]))
            if g.is_empty:
                continue
            p = f.get("properties") or {}
            self.features.append(
                {
                    "name": pick_name(p, lang, name_field),
                    "name_en": pick_name(p, "en"),
                    "country": p.get("ADM0_A3") or p.get("adm0_a3") or p.get("shapeGroup") or "",
                    "id": p.get("ISO_A3") if kind == "country" and p.get("ISO_A3") not in (None, "-99") else
                    (p.get("iso_3166_2") or p.get("shapeID") or p.get("ADM0_A3") or ""),
                    "props": p,
                }
            )
            geoms.append(g)
        self.geoms = geoms
        self.tree = shapely.STRtree(geoms)
        self._area = None

    @classmethod
    def load(cls, kind: str, country: str | None = None, level: str = "ADM2", path: str | None = None,
             name_field: str | None = None, lang: str = "en") -> "Boundaries":
        if path:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(data["features"], name_field, lang, "custom", f"user file {Path(path).name}")
        if kind in NE_FILES:
            data = json.loads(natural_earth(kind).read_text(encoding="utf-8"))
            feats = data["features"]
            if country:
                c = country.upper()
                feats = [f for f in feats if c in {
                    str(f["properties"].get(k, "")).upper() for k in
                    ("ADM0_A3", "adm0_a3", "ISO_A3", "iso_a3", "ISO_A2", "iso_a2", "SOV_A3", "sov_a3", "admin", "ADMIN")}]
                if not feats:
                    raise ValueError(f"no {kind} regions for country {country!r} (use an ISO 3166 alpha-3 code such as JPN)")
            return cls(feats, name_field, lang, kind, "Natural Earth (public domain)")
        if kind == "geoboundaries":
            if not country:
                raise ValueError("geoboundaries needs --country (ISO alpha-3, e.g. JPN)")
            p, meta = geoboundaries(country, level)
            data = json.loads(p.read_text(encoding="utf-8"))
            att = f"geoBoundaries {meta.get('boundaryISO')} {meta.get('boundaryType')} ({meta.get('boundaryCanonical')}), " \
                  f"source {meta.get('boundarySource')}, license {meta.get('boundaryLicense')}"
            return cls(data["features"], name_field, lang, f"geoboundaries-{level}", att)
        raise ValueError(f"unknown boundary kind {kind!r}")

    def subset(self, bbox) -> "Boundaries":
        """Only the regions that intersect a (west, south, east, north) box."""
        import shapely

        idx = sorted(int(i) for i in self.tree.query(shapely.box(*bbox), predicate="intersects"))
        b = object.__new__(Boundaries)
        b.kind, b.attribution, b._area = self.kind, self.attribution, None
        b.features = [self.features[i] for i in idx]
        b.geoms = [self.geoms[i] for i in idx]
        b.tree = shapely.STRtree(b.geoms)
        return b

    def assign(self, lng: np.ndarray, lat: np.ndarray, snap_deg: float = 0.03) -> np.ndarray:
        """Index of the region containing each point; -1 if none. Points just
        off the coast are snapped to the nearest region within `snap_deg`."""
        import shapely

        pts = shapely.points(np.c_[lng, lat])
        label = np.full(len(pts), -1, np.int64)
        if not len(pts):
            return label
        pi, gi = self.tree.query(pts, predicate="within")
        label[pi] = gi
        miss = np.nonzero(label < 0)[0]
        if len(miss) and snap_deg > 0:
            ui, gj = self.tree.query_nearest(pts[miss], max_distance=snap_deg, return_distance=False)
            label[miss[ui]] = gj
        return label

    def areas_km2(self) -> np.ndarray:
        if self._area is None:
            self._area = np.array([geo.equal_area(g).area / 1e6 for g in self.geoms])
        return self._area

    def centroid(self, i: int) -> tuple[float, float]:
        c = self.geoms[i].representative_point()
        return float(c.x), float(c.y)


def region_stats(fog: FogMap, b: Boundaries, zoom: int = 16, include_unvisited: bool = True,
                 min_km2: float = 0.0) -> list[dict]:
    """Explored area per region. Each explored cell at `zoom` (default 16,
    about 0.6 km wide at the equator) is assigned to the region containing its
    center."""
    if b.kind != "country" and len(b.geoms):
        # crop to the boundaries' extent to keep it fast
        import shapely
        w, s, e, n = shapely.total_bounds(b.geoms)
        fog = fog.crop((w - 0.1, s - 0.1, e + 0.1, n + 0.1))
    _, _, c, lng, lat, area = fog.grid_lnglat(zoom)
    label = b.assign(lng, lat)
    acc = defaultdict(lambda: [0, 0.0])
    for lab, a in zip(label[label >= 0], area[label >= 0]):
        acc[int(lab)][0] += 1
        acc[int(lab)][1] += float(a)
    total = b.areas_km2()
    out = []
    idx = range(len(b.features)) if include_unvisited else acc.keys()
    for i in idx:
        cells, km2 = acc.get(i, (0, 0.0))
        if km2 < min_km2 and i in acc:
            cells, km2 = 0, 0.0
        f = b.features[i]
        lng0, lat0 = b.centroid(i)
        out.append({
            "name": f["name"], "name_en": f["name_en"], "id": f["id"], "country": f["country"],
            "visited": km2 > 0, "explored_km2": round(km2, 3), "cells": cells,
            "region_km2": round(float(total[i]), 1),
            "explored_pct": round(100 * km2 / total[i], 3) if total[i] > 0 else None,
            "center": [round(lng0, 5), round(lat0, 5)],
        })
    out.sort(key=lambda r: (-r["explored_km2"], r["name"]))
    return out


def label_points(lng, lat, lang: str = "en") -> list[dict]:
    """Country and first-level region of each point (Natural Earth)."""
    b1 = Boundaries.load("admin1", lang=lang)
    b0 = Boundaries.load("country", lang=lang)
    lng, lat = np.atleast_1d(lng), np.atleast_1d(lat)
    l1 = b1.assign(lng, lat, snap_deg=0.2)
    l0 = b0.assign(lng, lat, snap_deg=0.2)
    out = []
    for i0, i1 in zip(l0, l1):
        out.append({
            "country": b0.features[i0]["name"] if i0 >= 0 else "",
            "country_code": b0.features[i0]["id"] if i0 >= 0 else "",
            "region": b1.features[i1]["name"] if i1 >= 0 else "",
        })
    return out
