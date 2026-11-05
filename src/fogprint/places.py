"""Group explored (or unexplored) cells into connected places."""

from __future__ import annotations

import numpy as np

from . import geo
from .fogmap import FogMap, _key


def components(x: np.ndarray, y: np.ndarray, zoom: int, gap: int = 1) -> np.ndarray:
    """Label 8-connected components of grid cells (cells up to `gap` cells
    apart are joined). Returns one label per input cell."""
    n = len(x)
    parent = np.arange(n)
    if n == 0:
        return parent
    keys = _key(x, y, zoom)
    order = np.argsort(keys)
    sk = keys[order]

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    offs = [(dx, dy) for dx in range(-gap, gap + 1) for dy in range(0, gap + 1) if (dy > 0 or dx > 0)]
    for dx, dy in offs:
        k = _key(x + dx, y + dy, zoom)
        j = np.searchsorted(sk, k)
        j = np.minimum(j, n - 1)
        hit = np.nonzero(sk[j] == k)[0]
        for a, b in zip(hit, order[j[hit]]):
            ra, rb = find(int(a)), find(int(b))
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return np.array([find(i) for i in range(n)])


def places(fog: FogMap, zoom: int = 14, lang: str = "en", top: int | None = None) -> list[dict]:
    """Explored area grouped by first-level region (state, province,
    prefecture), largest first, with the area-weighted center and extent of
    the explored part. Long journeys (trains, flights with GPS on) connect
    everything, so regions are a better unit than connected blobs."""
    from .regions import Boundaries

    x, y, c, lng, lat, area = fog.grid_lnglat(zoom)
    if not len(x):
        return []
    b1 = Boundaries.load("admin1", lang=lang)
    b0 = Boundaries.load("country", lang=lang)
    l1 = b1.assign(lng, lat, snap_deg=0.2)
    out = []
    for g in np.unique(l1):
        m = l1 == g
        a = area[m]
        cx = float(np.average(lng[m], weights=a))
        cy = float(np.average(lat[m], weights=a))
        if g >= 0:
            f = b1.features[g]
            i0 = b0.assign(np.array([cx]), np.array([cy]), snap_deg=0.5)[0]
            country = b0.features[i0]["name"] if i0 >= 0 else f["props"].get("admin", "")
            code = f["country"]
            region = f["name"]
        else:
            country, code, region = "", "", "(sea / unmatched)"
        out.append({
            "country": country, "country_code": code, "region": region,
            "explored_km2": round(float(a.sum()), 3),
            "center": [round(cx, 5), round(cy, 5)],
            "bbox": [round(float(lng[m].min()), 4), round(float(lat[m].min()), 4),
                     round(float(lng[m].max()), 4), round(float(lat[m].max()), 4)],
            "cells": int(m.sum()),
        })
    out.sort(key=lambda p: -p["explored_km2"])
    return out[:top] if top else out


def unexplored_pockets(fog: FogMap, lng: float, lat: float, radius_km: float, zoom: int = 16,
                       top: int = 15, land_only: bool = True) -> dict:
    """Coverage around a point, and the biggest unexplored pockets in reach.
    A grid cell counts as explored if any pixel in it is explored."""
    bbox = geo.bbox_around(lng, lat, radius_km)
    x0, y0 = geo.lnglat_to_px(bbox[0], bbox[3], zoom)
    x1, y1 = geo.lnglat_to_px(bbox[2], bbox[1], zoom)
    if (x1 - x0) * (y1 - y0) > 4_000_000:
        raise ValueError("too many cells; use a smaller --radius-km or a lower --zoom")
    xs, ys = np.meshgrid(np.arange(int(x0), int(x1) + 1), np.arange(int(y0), int(y1) + 1))
    xs, ys = xs.ravel(), ys.ravel()
    clng, clat = geo.px_to_lnglat(xs + 0.5, ys + 0.5, zoom)
    d = geo.haversine_m(lng, lat, clng, clat)
    keep = d <= radius_km * 1000
    sub = fog.crop(bbox)
    gx, gy, _ = sub.grid(zoom)
    explored_all = np.isin(_key(xs, ys, zoom), _key(gx, gy, zoom))
    if land_only:
        from .regions import land_mask
        keep &= land_mask(clng, clat) | explored_all
    xs, ys, clng, clat, d, explored = xs[keep], ys[keep], clng[keep], clat[keep], d[keep], explored_all[keep]
    cell_km2 = geo.cell_area_km2(ys, zoom)
    # explored pixel area inside the circle
    px, py, pc, plng, plat, parea = sub.grid_lnglat(min(22, zoom + 3))
    inside = geo.haversine_m(lng, lat, plng, plat) <= radius_km * 1000
    res = {
        "center": [lng, lat], "radius_km": radius_km, "zoom": zoom,
        "cell_km": round(float(np.sqrt(cell_km2.mean())), 3) if len(xs) else None,
        "land_only": land_only,
        "area_km2": round(float(cell_km2.sum()), 2),
        "explored_km2": round(float(parea[inside].sum()), 3),
        "cells": int(len(xs)), "explored_cells": int(explored.sum()),
        "explored_cells_pct": round(100 * explored.mean(), 2) if len(xs) else 0,
        "by_direction": {}, "pockets": [],
    }
    bearings = np.degrees(np.arctan2((clng - lng) * np.cos(np.radians(lat)), clat - lat)) % 360
    sector = ((bearings + 22.5) // 45).astype(int) % 8
    for i, name in enumerate(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]):
        m = sector == i
        res["by_direction"][name] = round(100 * explored[m].mean(), 1) if m.any() else None
    u = ~explored
    lab = components(xs[u], ys[u], zoom, 1)
    ulng, ulat, ud, uarea = clng[u], clat[u], d[u], cell_km2[u]
    edge = ud > radius_km * 1000 - 2 * (res["cell_km"] or 0) * 1000
    pockets = []
    for g in np.unique(lab):
        m = lab == g
        j = np.argmin(ud[m])
        c = [float(ulng[m].mean()), float(ulat[m].mean())]
        pockets.append({
            "km2": round(float(uarea[m].sum()), 2),
            "center": [round(c[0], 5), round(c[1], 5)],
            "nearest_point": [round(float(ulng[m][j]), 5), round(float(ulat[m][j]), 5)],
            "distance_km": round(float(ud[m][j]) / 1000, 2),
            "direction": geo.compass(geo.bearing_deg(lng, lat, c[0], c[1])),
            "touches_edge": bool(edge[m].any()),
        })
    pockets.sort(key=lambda p: -p["km2"])
    res["pockets"] = pockets[:top]
    return res
