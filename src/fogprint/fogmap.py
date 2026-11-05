"""In-memory explored-area map: the set of explored zoom-22 pixels, stored as
packed 64 x 64 bitmaps per zoom-16 tile."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import geo
from .fogformat import BITMAP_BYTES, TILE_PX, decode_block
from .sources import Source, inspect, iter_blocks

_POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.int64)


def _key(x, y, zoom):
    return (np.asarray(y, np.int64) << zoom) | np.asarray(x, np.int64)


class FogMap:
    def __init__(self, tiles: np.ndarray, bitmaps: np.ndarray, source: Source | None = None):
        tiles = np.asarray(tiles, np.int32).reshape(-1, 2)
        bitmaps = np.asarray(bitmaps, np.uint8).reshape(-1, BITMAP_BYTES)
        keys = _key(tiles[:, 0], tiles[:, 1], 16)
        order = np.argsort(keys, kind="stable")
        keys, tiles, bitmaps = keys[order], tiles[order], bitmaps[order]
        if len(keys) > 1 and (np.diff(keys) == 0).any():  # merge duplicates
            uniq, start = np.unique(keys, return_index=True)
            merged = np.bitwise_or.reduceat(bitmaps, start, axis=0)
            tiles, bitmaps, keys = tiles[start], merged, uniq
        self.tiles, self.bitmaps, self.keys = tiles, bitmaps, keys
        self.source = source

    # ---------------------------------------------------------------- loading
    @classmethod
    def load(cls, src: Source | str | Path) -> "FogMap":
        if not isinstance(src, Source):
            s = inspect(src)
            if s is None:
                raise FileNotFoundError(f"no Fog of World data found at {src}")
            src = s
        tiles, bitmaps = [], []
        for bx, by, data in iter_blocks(src):
            t, b = decode_block(data, bx, by)
            tiles.append(t)
            bitmaps.append(b)
        if not tiles:
            return cls(np.zeros((0, 2)), np.zeros((0, BITMAP_BYTES)), src)
        return cls(np.concatenate(tiles), np.concatenate(bitmaps), src)

    @classmethod
    def empty(cls) -> "FogMap":
        return cls(np.zeros((0, 2)), np.zeros((0, BITMAP_BYTES)))

    def __len__(self):
        return len(self.keys)

    # ------------------------------------------------------------ statistics
    def tile_pixels(self) -> np.ndarray:
        """Explored pixels per tile."""
        return _POP[self.bitmaps].sum(axis=1)

    def pixel_count(self) -> int:
        return int(self.tile_pixels().sum())

    def tile_area_km2(self) -> np.ndarray:
        return self.tile_pixels() * geo.cell_area_km2(self.tiles[:, 1].astype(float) * TILE_PX + TILE_PX / 2 - 0.5, 22)

    def area_km2(self) -> float:
        return float(self.tile_area_km2().sum())

    def bbox(self) -> tuple[float, float, float, float] | None:
        if not len(self):
            return None
        w, n = geo.px_to_lnglat(self.tiles[:, 0].min(), self.tiles[:, 1].min(), 16)
        e, s = geo.px_to_lnglat(self.tiles[:, 0].max() + 1, self.tiles[:, 1].max() + 1, 16)
        return float(w), float(s), float(e), float(n)

    # ------------------------------------------------------------------ grids
    def grid(self, zoom: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Explored pixel count per XYZ cell at `zoom` (0..22).
        Returns (x, y, count) arrays of the non-empty cells."""
        if zoom > 22 or zoom < 0:
            raise ValueError("zoom must be 0..22")
        if not len(self):
            z = np.zeros(0, np.int64)
            return z, z, z
        if zoom <= 16:
            sh = 16 - zoom
            k = _key(self.tiles[:, 0] >> sh, self.tiles[:, 1] >> sh, zoom)
            uk, inv = np.unique(k, return_inverse=True)
            cnt = np.bincount(inv, weights=self.tile_pixels()).astype(np.int64)
            return uk & ((1 << zoom) - 1), uk >> zoom, cnt
        f = 1 << (22 - zoom)  # pixels per cell side
        per = TILE_PX // f  # cells per tile side
        xs, ys, cs = [], [], []
        for i in range(0, len(self), 20000):
            bm = np.unpackbits(self.bitmaps[i:i + 20000], axis=1).reshape(-1, per, f, per, f)
            c = bm.sum(axis=(2, 4), dtype=np.int64)  # (n, per, per)
            t, cy, cx = np.nonzero(c)
            xs.append(self.tiles[i + t, 0].astype(np.int64) * per + cx)
            ys.append(self.tiles[i + t, 1].astype(np.int64) * per + cy)
            cs.append(c[t, cy, cx])
        return np.concatenate(xs), np.concatenate(ys), np.concatenate(cs)

    def grid_lnglat(self, zoom: int):
        """Like grid(), plus cell-center lng/lat and explored area in km^2."""
        x, y, c = self.grid(zoom)
        lng, lat = geo.px_to_lnglat(x + 0.5, y + 0.5, zoom)
        area = c * geo.cell_area_km2(y.astype(float) * (1 << (22 - zoom)) + (1 << (22 - zoom)) / 2 - 0.5, 22)
        return x, y, c, lng, lat, area

    # ---------------------------------------------------------------- queries
    def explored(self, px, py) -> np.ndarray:
        """Is each zoom-22 pixel explored?"""
        px = np.asarray(px, np.int64)
        py = np.asarray(py, np.int64)
        k = _key(px >> 6, py >> 6, 16)
        i = np.searchsorted(self.keys, k)
        i = np.minimum(i, max(0, len(self.keys) - 1))
        hit = (len(self.keys) > 0) & (self.keys[i] == k) if len(self.keys) else np.zeros(px.shape, bool)
        out = np.zeros(px.shape, bool)
        if not np.any(hit):
            return out
        lx, ly = px[hit] & 63, py[hit] & 63
        byte = self.bitmaps[i[hit], ly * 8 + (lx >> 3)]
        out[hit] = (byte >> (7 - (lx & 7))) & 1 == 1
        return out

    def near_explored(self, lng, lat, tolerance_m: float) -> np.ndarray:
        """Is there explored area within about `tolerance_m` of each point?
        Uses a grid whose cells are at least `tolerance_m` wide and checks the
        point's cell and its 8 neighbours, so the effective radius is between
        1x and 2x the tolerance."""
        lng = np.atleast_1d(np.asarray(lng, float))
        lat = np.atleast_1d(np.asarray(lat, float))
        if not len(self) or not len(lng):
            return np.zeros(lng.shape, bool)
        z = geo.zoom_for_size(tolerance_m, float(np.median(lat)))
        z = min(z, 22)
        gx, gy, _ = self.grid(z)
        cells = np.sort(_key(gx, gy, z))
        x, y = geo.lnglat_to_px(lng, lat, z)
        x, y = x.astype(np.int64), y.astype(np.int64)
        hit = np.zeros(lng.shape, bool)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k = _key(x + dx, y + dy, z)
                j = np.minimum(np.searchsorted(cells, k), len(cells) - 1)
                hit |= cells[j] == k
        return hit

    def nearest(self, lng: float, lat: float, k: int = 16):
        """Distance in meters and position of the nearest explored pixel."""
        if not len(self):
            return None
        clng, clat = geo.px_to_lnglat(self.tiles[:, 0] + 0.5, self.tiles[:, 1] + 0.5, 16)
        d = geo.haversine_m(lng, lat, clng, clat)
        cand = np.argsort(d)[:k]
        best = None
        for i in cand:
            bm = np.unpackbits(self.bitmaps[i]).reshape(64, 64)
            yy, xx = np.nonzero(bm)
            plng, plat = geo.px_to_lnglat(self.tiles[i, 0] * 64 + xx + 0.5, self.tiles[i, 1] * 64 + yy + 0.5)
            dd = geo.haversine_m(lng, lat, plng, plat)
            j = int(np.argmin(dd))
            if best is None or dd[j] < best[0]:
                best = (float(dd[j]), float(plng[j]), float(plat[j]))
        return best

    # ------------------------------------------------------------ set algebra
    def crop(self, bbox) -> "FogMap":
        """Tiles that intersect a (west, south, east, north) box."""
        w, s, e, n = bbox
        x0, y0 = geo.lnglat_to_px(w, n, 16)
        x1, y1 = geo.lnglat_to_px(e, s, 16)
        t = self.tiles
        m = (t[:, 0] >= int(x0)) & (t[:, 0] <= int(x1)) & (t[:, 1] >= int(y0)) & (t[:, 1] <= int(y1))
        return FogMap(t[m], self.bitmaps[m], self.source)

    def _align(self, other: "FogMap"):
        i = np.searchsorted(other.keys, self.keys)
        i = np.minimum(i, max(0, len(other.keys) - 1))
        hit = other.keys[i] == self.keys if len(other.keys) else np.zeros(len(self.keys), bool)
        ob = np.zeros_like(self.bitmaps)
        ob[hit] = other.bitmaps[i[hit]]
        return ob

    def minus(self, other: "FogMap") -> "FogMap":
        """Pixels explored here but not in `other` (e.g. what a trip added)."""
        b = self.bitmaps & ~self._align(other)
        keep = b.any(axis=1)
        return FogMap(self.tiles[keep], b[keep], self.source)

    def union(self, other: "FogMap") -> "FogMap":
        return FogMap(np.concatenate([self.tiles, other.tiles]), np.concatenate([self.bitmaps, other.bitmaps]), self.source)

    def intersect(self, other: "FogMap") -> "FogMap":
        b = self.bitmaps & self._align(other)
        keep = b.any(axis=1)
        return FogMap(self.tiles[keep], b[keep], self.source)
