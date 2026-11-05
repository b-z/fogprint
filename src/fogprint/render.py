"""Render explored area to a PNG, optionally over OpenStreetMap tiles."""

from __future__ import annotations

import io
import json
import math
import time
import urllib.request
from pathlib import Path

import numpy as np

from . import geo
from .fogmap import FogMap
from .regions import UA, cache_dir

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def _fetch_tile(z, x, y, url_tpl):
    p = cache_dir() / "tiles" / str(z) / str(x) / f"{y}.png"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url_tpl.format(z=z, x=x, y=y), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            p.write_bytes(r.read())
        time.sleep(0.05)
    return p.read_bytes()


def _draw_land(canvas, bbox, z, x0, y0):
    """Light land polygons from Natural Earth (no network after first use)."""
    import shapely
    from PIL import ImageDraw
    from shapely.geometry import shape

    from .regions import natural_earth

    try:
        data = json.loads(natural_earth("land").read_text(encoding="utf-8"))
    except OSError:
        return
    box = shapely.box(*bbox)
    d = ImageDraw.Draw(canvas)
    for f in data["features"]:
        g = shape(f["geometry"])
        if not g.intersects(box):
            continue
        g = g.intersection(box.buffer(0.5))
        for poly in getattr(g, "geoms", [g]):
            if poly.geom_type != "Polygon":
                continue
            for k, ring in enumerate([poly.exterior, *poly.interiors]):
                c = np.asarray(ring.coords)
                px, py = geo.lnglat_to_px(c[:, 0], c[:, 1], z)
                d.polygon(list(zip(px - x0, py - y0)), fill=(250, 250, 247) if k == 0 else (214, 228, 238),
                          outline=(170, 170, 170))


def _mask(fog: FogMap, bbox, z, x0, y0, W, H, r) -> np.ndarray:
    zz = min(z, 22)
    f = 1 << (z - zz)  # output pixels per data pixel when zoomed past the data resolution
    gx, gy, _ = fog.crop(bbox).grid(zz)
    mask = np.zeros((H, W), bool)
    for dy in range(f):
        for dx in range(f):
            x, y = gx * f + dx, gy * f + dy
            m = (x >= x0) & (x < x0 + W) & (y >= y0) & (y < y0 + H)
            mask[y[m] - y0, x[m] - x0] = True
    # thicken thin tracks so they stay visible at small scales
    if r > 0:
        m0 = mask.copy()
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                mask[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)] |= \
                    m0[max(0, -dy):H + min(0, -dy), max(0, -dx):W + min(0, -dx)]
    return mask


def render(fog: FogMap, bbox, out: str, max_px: int = 1600, basemap: str = "osm",
           overlays: list[dict] | None = None, fog_alpha: int = 190, tile_url: str = TILE_URL,
           reveal_px: int | None = None, highlight: FogMap | None = None) -> dict:
    """Write a PNG of the bbox. With basemap="osm" the explored area shows the
    map and the rest is covered by fog; with basemap="none" explored area is
    drawn in a solid color. `overlays`: GeoJSON FeatureCollections of lines,
    drawn with the feature property "color" (default red). `highlight`: a
    second FogMap (e.g. area added by a trip) drawn in blue on top."""
    from PIL import Image, ImageColor, ImageDraw, ImageFont

    w, s, e, n = bbox
    # smallest zoom (<= 22) whose image is at least max_px; scaled down at the end
    for z in range(0, 25):
        x0, y0 = geo.lnglat_to_px(w, n, z)
        x1, y1 = geo.lnglat_to_px(e, s, z)
        if max(x1 - x0, y1 - y0) >= max_px:
            break
    x0, y0, x1, y1 = int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(x1)), int(math.ceil(y1))
    W, H = max(1, x1 - x0), max(1, y1 - y0)

    r = reveal_px if reveal_px is not None else max(2, round(max(W, H) / 500))
    mask = _mask(fog, bbox, z, x0, y0, W, H, r)
    hmask = _mask(highlight, bbox, z, x0, y0, W, H, r) if highlight is not None else None

    attribution = None
    if basemap == "osm":
        tz = max(0, min(19, z - 8))
        scale = 2 ** (z - 8 - tz)  # output px per tile px / 256
        canvas = Image.new("RGB", (W, H), (230, 230, 230))
        size = max(1, int(round(256 * scale)))
        tx0, ty0, tx1, ty1 = x0 // size, y0 // size, (x1 - 1) // size, (y1 - 1) // size
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 400:
            raise ValueError("area too large for a basemap at this size; use --basemap none or a smaller --max-px")
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                if not (0 <= ty < 2 ** tz):
                    continue
                img = Image.open(io.BytesIO(_fetch_tile(tz, tx % (2 ** tz), ty, tile_url))).convert("RGB")
                if size != 256:
                    img = img.resize((size, size), Image.BILINEAR)
                canvas.paste(img, (tx * size - x0, ty * size - y0))
        fog_layer = np.zeros((H, W, 4), np.uint8)
        fog_layer[..., :3] = (40, 44, 52)
        fog_layer[..., 3] = np.where(mask, 0, fog_alpha)
        # bright rim around revealed area
        rim = np.zeros_like(mask)
        rim[1:] |= mask[:-1]
        rim[:-1] |= mask[1:]
        rim[:, 1:] |= mask[:, :-1]
        rim[:, :-1] |= mask[:, 1:]
        rim &= ~mask
        fog_layer[rim] = (255, 196, 0, 255)
        if hmask is not None:
            fog_layer[hmask & mask] = (0, 170, 255, 70)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), Image.fromarray(fog_layer, "RGBA"))
        attribution = "Map data © OpenStreetMap contributors"
    else:
        canvas = Image.new("RGBA", (W, H), (214, 228, 238, 255))  # sea
        _draw_land(canvas, bbox, z, x0, y0)
        arr = np.array(canvas)
        arr[mask] = (217, 95, 2, 255)
        if hmask is not None:
            arr[hmask] = (31, 120, 220, 255)
        canvas = Image.fromarray(arr, "RGBA")
        attribution = "Natural Earth"

    if overlays:
        lw = max(2, round(max(W, H) / 700))
        fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fill_layer)
        d = ImageDraw.Draw(canvas)
        labels = []

        def to_px(coords):
            c = np.asarray(coords, float)
            px, py = geo.lnglat_to_px(c[:, 0], c[:, 1], z)
            return list(zip(px - x0, py - y0))

        for fc in overlays:
            for f in fc.get("features", []):
                g = f.get("geometry") or {}
                props = f.get("properties") or {}
                color = props.get("color", "#e41a1c")
                t = g.get("type")
                if t in ("Polygon", "MultiPolygon"):
                    polys = [g["coordinates"]] if t == "Polygon" else g["coordinates"]
                    rgb = ImageColor.getrgb(color)[:3]
                    for poly in polys:
                        fd.polygon(to_px(poly[0]), fill=rgb + (int(props.get("fill_alpha", 70)),))
                        for ring in poly:
                            fd.line(to_px(ring), fill=rgb + (230,), width=max(1, lw // 2))
                    if props.get("label"):
                        import shapely.geometry
                        p = shapely.geometry.shape(g).representative_point()
                        labels.append((to_px([(p.x, p.y)])[0], str(props["label"]), rgb))
                elif t in ("LineString", "MultiLineString"):
                    for part in ([g["coordinates"]] if t == "LineString" else g["coordinates"]):
                        d.line(to_px(part), fill=color, width=lw * 2)
                elif t == "Point":
                    (px, py), = to_px([g["coordinates"][:2]])
                    r = lw * 4
                    d.ellipse((px - r, py - r, px + r, py + r), fill=color, outline="white", width=max(1, lw // 2))
                    if props.get("label"):
                        labels.append(((px, py - 3 * r), str(props["label"]), ImageColor.getrgb(color)[:3]))
        canvas = Image.alpha_composite(canvas, fill_layer)
        if labels:
            d = ImageDraw.Draw(canvas)
            fs = max(12, round(max(W, H) / 90))
            try:
                font = ImageFont.load_default(size=fs)
            except TypeError:
                font = ImageFont.load_default()
            for (px, py), text, rgb in labels:
                tw = d.textlength(text, font=font)
                d.text((px - tw / 2, py - fs / 2), text, fill=tuple(int(v * 0.6) for v in rgb), font=font,
                       stroke_width=max(2, fs // 6), stroke_fill="white")
    if max(W, H) > max_px:
        f = max_px / max(W, H)
        canvas = canvas.resize((max(1, round(W * f)), max(1, round(H * f))), Image.LANCZOS)
        W, H = canvas.size
    if attribution:
        d = ImageDraw.Draw(canvas)
        fs = max(11, round(max(W, H) / 110))
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
        tw = d.textlength(attribution, font=font)
        pad = fs // 3
        d.rectangle((W - tw - 3 * pad, H - fs - 2 * pad, W, H), fill=(255, 255, 255, 210))
        d.text((W - tw - 2 * pad, H - fs - pad), attribution, fill=(60, 60, 60), font=font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, optimize=True)
    return {"file": str(out), "width": W, "height": H, "zoom": z, "explored_px": int(mask.sum()),
            "attribution": attribution}
