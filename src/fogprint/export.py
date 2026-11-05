"""Export explored area as grid cells (CSV) or polygons (GeoJSON)."""

from __future__ import annotations

import csv
import json

from . import geo
from .fogmap import FogMap


def cells_csv(fog: FogMap, zoom: int, out: str) -> int:
    x, y, c, lng, lat, area = fog.grid_lnglat(zoom)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zoom", "x", "y", "lng", "lat", "explored_px", "explored_km2"])
        for row in zip(x, y, lng, lat, c, area):
            w.writerow([zoom, int(row[0]), int(row[1]), f"{row[2]:.6f}", f"{row[3]:.6f}", int(row[4]), f"{row[5]:.6f}"])
    return len(x)


def polygons_geojson(fog: FogMap, zoom: int, out: str, simplify_m: float = 0) -> int:
    """Explored area as merged polygons, built from zoom-`zoom` cells."""
    import shapely
    import shapely.geometry

    x, y, _ = fog.grid(zoom)
    if not len(x):
        geom = shapely.GeometryCollection()
    else:
        w, n = geo.px_to_lnglat(x, y, zoom)
        e, s = geo.px_to_lnglat(x + 1, y + 1, zoom)
        boxes = shapely.box(w, s, e, n)
        geom = shapely.union_all(boxes, grid_size=1e-7)
        if simplify_m:
            geom = shapely.simplify(geom, simplify_m / 111320)
    feat = {"type": "Feature", "properties": {"zoom": zoom, "cells": int(len(x)),
                                             "explored_km2": round(fog.area_km2(), 3)},
            "geometry": shapely.geometry.mapping(geom)}
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": [feat]}, f)
    return int(len(x))
