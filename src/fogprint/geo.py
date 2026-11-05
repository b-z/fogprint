"""Web Mercator helpers. Pixel coordinates are at zoom 22 (the bitmap
resolution) unless a zoom is given: x, y in [0, 2**zoom)."""

from __future__ import annotations

import math

import numpy as np

EARTH_RADIUS_M = 6371008.8
# Values used by Fog of World itself (reverse-engineered by the "迷雾资料库" articles):
# pixel width = 40075.017 km / 2**22 * cos(latitude); the earth's surface = 510,072,000 km^2;
# level = sqrt(250 * explored km^2).
EQUATOR_M = 40075017.0
EARTH_AREA_KM2 = 510_072_000.0
MAX_LAT = 85.05112878


def lnglat_to_px(lng, lat, zoom: int = 22):
    n = float(1 << zoom)
    lng = np.asarray(lng, float)
    lat = np.clip(np.asarray(lat, float), -MAX_LAT, MAX_LAT)
    x = (lng + 180.0) / 360.0 * n
    s = np.sin(np.radians(lat))
    y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * n
    return x, y


def px_to_lnglat(x, y, zoom: int = 22):
    n = float(1 << zoom)
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    lng = x / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
    return lng, lat


def cell_area_km2(y, zoom: int):
    """Area in km^2 of one zoom-`zoom` cell whose row (center) is y."""
    _, lat = px_to_lnglat(0, np.asarray(y, float) + 0.5, zoom)
    side_km = EQUATOR_M / 1000.0 * np.cos(np.radians(lat)) / (1 << zoom)
    return side_km * side_km


def level(km2: float) -> int:
    """Fog of World's level for an explored area (the same rule applies to
    the whole world and to each country's passport)."""
    return int(math.floor(math.sqrt(250.0 * max(0.0, km2)) + 1e-9))


def world_pct(km2: float) -> float:
    return 100.0 * km2 / EARTH_AREA_KM2


def pixel_size_m(lat: float, zoom: int = 22) -> float:
    return EQUATOR_M * math.cos(math.radians(lat)) / (1 << zoom)


def haversine_m(lng1, lat1, lng2, lat2):
    lng1, lat1, lng2, lat2 = (np.radians(np.asarray(v, float)) for v in (lng1, lat1, lng2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.minimum(1.0, a)))


def bearing_deg(lng1, lat1, lng2, lat2):
    lng1, lat1, lng2, lat2 = (math.radians(v) for v in (lng1, lat1, lng2, lat2))
    y = math.sin(lng2 - lng1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lng2 - lng1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(deg: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) // 45) % 8]


def zoom_for_size(meters: float, lat: float = 0.0) -> int:
    """The largest zoom whose cells are at least `meters` wide at `lat`."""
    for z in range(22, -1, -1):
        if pixel_size_m(lat, z) >= meters:
            return z
    return 0


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    """'west,south,east,north' in degrees."""
    w, s, e, n = (float(v) for v in text.split(","))
    if s > n:
        s, n = n, s
    return w, s, e, n


def bbox_around(lng: float, lat: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.32
    dlng = radius_km / (111.32 * max(0.01, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def equal_area(geom):
    """Project a lon/lat shapely geometry to Lambert cylindrical equal-area
    (meters), so that `.area` is a true area."""
    import shapely

    def f(coords):
        lng = np.radians(coords[:, 0])
        lat = np.radians(coords[:, 1])
        return np.c_[EARTH_RADIUS_M * lng, EARTH_RADIUS_M * np.sin(lat)]

    return shapely.transform(geom, f)
