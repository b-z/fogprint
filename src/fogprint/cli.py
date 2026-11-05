"""fogprint command line. Every command prints JSON to stdout."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__, geo
from .fogmap import FogMap
from .sources import Source, databases, inspect, locate, pick_default

# ------------------------------------------------------------------ helpers
_NUMLIST = re.compile(r"\[\s*(-?[\d.eE+-]+(?:,\s*-?[\d.eE+-]+)*)\s*\]")


def emit(obj):
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    text = _NUMLIST.sub(lambda m: "[" + ", ".join(v.strip() for v in m.group(1).split(",")) + "]", text)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)


def fail(msg, code=2, **extra):
    emit({"error": msg, **extra})
    sys.exit(code)


def parse_latlng(text: str) -> tuple[float, float]:
    """'LAT,LNG' (Google Maps order) -> (lng, lat)."""
    a, b = (float(v) for v in text.replace(" ", "").split(","))
    return b, a


def resolve_source(spec: str | None, roots) -> Source:
    """A path, a database name (e.g. "Trip 2026"), "snapshot:<YYYY-MM-DD or
    prefix>", or None for the newest data of the main database."""
    if spec:
        p = Path(spec).expanduser()
        if p.exists():
            s = inspect(p)
            if not s:
                fail(f"no Fog of World data found in {spec}")
            return s
    found = locate(roots)
    if not found:
        fail("no Fog of World data found. Pass --src with the path to the Sync folder, a Sync zip or a "
             ".fwss snapshot, or set FOGPRINT_DATA.", hint="run `fogprint locate --root <folder>` to search a folder")
    if not spec:
        return pick_default(found, "main")
    if spec.startswith("snapshot:"):
        key = spec.split(":", 1)[1].replace("-", "")
        snaps = [s for s in found if s.kind == "snapshot" and s.modified.replace("-", "").startswith(key)]
        if not snaps:
            fail(f"no snapshot matches {spec}", snapshots=[s.modified for s in found if s.kind == "snapshot"])
        return snaps[0]
    db = [s for s in found if s.database == spec and s.kind != "snapshot"] or [s for s in found if s.database == spec]
    if not db:
        fail(f"{spec!r} is neither a path nor a database name", databases=sorted({s.database for s in found}))
    return max(db, key=lambda s: s.modified)


def load(args) -> FogMap:
    if args.src == "all":
        found = locate(args.root)
        fog = FogMap.empty()
        used = []
        for db, s in databases(found).items():
            fog = fog.union(FogMap.load(s))
            used.append(s.path)
        fog.source = Source(" + ".join(used), "union", "all", max((s.modified for s in found), default=""))
    else:
        fog = FogMap.load(resolve_source(args.src, args.root))
    if getattr(args, "bbox", None):
        fog = fog.crop(geo.parse_bbox(args.bbox))
    return fog


def src_info(fog: FogMap) -> dict:
    s = fog.source
    return {"path": s.path, "kind": s.kind, "database": s.database, "modified": s.modified} if s else {}


def area_bbox(args):
    if getattr(args, "bbox", None):
        return geo.parse_bbox(args.bbox)
    if getattr(args, "around", None):
        lng, lat = parse_latlng(args.around)
        return geo.bbox_around(lng, lat, args.radius_km)
    return None


# ----------------------------------------------------------------- commands
def cmd_locate(args):
    found = locate(args.root)
    best = pick_default(found, "main")
    emit({"sources": [s.as_dict() for s in found], "default": best.path if best else None,
          "databases": {db: s.path for db, s in databases(found).items()},
          "note": "default = live Sync folder of the main database, else its newest snapshot, else the newest zip. "
                  "Other .fwdb databases (often one per trip) are separate; use --src <name> or --src all.",
          "searched": [str(r) for r in (args.root or [])] or "default iCloud / Dropbox folders"})


def cmd_summary(args):
    fog = load(args)
    km2 = fog.area_km2()
    out = {"source": src_info(fog), "explored_km2": round(km2, 6), "world_pct": float(f"{geo.world_pct(km2):.6g}"),
           "level": geo.level(km2), "explored_pixels": fog.pixel_count(),
           "tiles_z16": len(fog), "bbox": fog.bbox()}
    for z in (10, 12, 14):
        out[f"cells_z{z}"] = int(len(fog.grid(z)[0]))
    out["note"] = ("explored_km2, world_pct and level follow Fog of World's own rules: each revealed pixel is "
                   "(9.5546 m x cos(lat))^2, the earth is 510,072,000 km^2, level = floor(sqrt(250 x km2)); "
                   "countries are assigned by grid cell, so their sum can differ slightly from the app's passports. "
                   "cells_zN is the number of zoom-N map tiles touched (z14 tile ~ 2.4 km x cos(lat))")
    if not args.no_regions and len(fog):
        from .regions import Boundaries, region_stats
        try:
            b = Boundaries.load("country", lang=args.lang)
            rs = region_stats(fog, b, zoom=14, include_unvisited=False)
            out["countries"] = [{k: r[k] for k in ("name", "id", "explored_km2", "level", "explored_pct")} for r in rs]
            b1 = Boundaries.load("admin1", lang=args.lang)
            r1 = region_stats(fog, b1, zoom=14, include_unvisited=False)
            per = {}
            for r in r1:
                per[r["country"]] = per.get(r["country"], 0) + 1
            out["admin1_visited"] = len(r1)
            out["admin1_visited_by_country"] = per
            out["boundaries"] = b.attribution
        except OSError as e:
            out["regions_error"] = str(e)
    emit(out)


def cmd_regions(args):
    from .regions import Boundaries, region_stats
    fog = load(args)
    kind = "geoboundaries" if re.fullmatch(r"ADM\d", args.level.upper()) else args.level.lower()
    b = Boundaries.load(kind, country=args.country, level=args.level, path=args.boundaries,
                        name_field=args.name_field, lang=args.lang)
    if args.bbox:
        b = b.subset(geo.parse_bbox(args.bbox))
    if args.within:
        parent = Boundaries.load("admin1", country=args.country, lang=args.lang)
        b = b.within(parent.geoms[parent.find(args.within)])
    rs = region_stats(fog, b, zoom=args.zoom, include_unvisited=not args.visited_only, min_km2=args.min_km2)
    if args.unvisited_only:
        rs = [r for r in rs if not r["visited"]]
    if args.geojson_out:
        import shapely
        import shapely.geometry
        feats = []
        for r in rs:
            g = shapely.simplify(b.geoms[r["_index"]], 0.0005)
            feats.append({"type": "Feature", "geometry": shapely.geometry.mapping(g), "properties": {
                "name": r["name"], "visited": r["visited"], "explored_km2": r["explored_km2"], "label": r["name"],
                "color": "#2b8cbe" if r["visited"] else "#e41a1c"}})
        Path(args.geojson_out).write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
    for r in rs:
        r.pop("_index", None)
    visited = sum(r["visited"] for r in rs) if not args.unvisited_only else None
    out = {"source": src_info(fog), "boundaries": b.attribution, "regions_total": len(b.features),
           "regions_visited": visited if visited is not None else len(b.features) - len(rs),
           "regions": rs if not args.top else rs[: args.top]}
    if args.out:
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
        out = {k: v for k, v in out.items() if k != "regions"} | {"written": args.out}
    emit(out)


def cmd_places(args):
    from .places import places
    fog = load(args)
    ps = places(fog, zoom=args.zoom, lang=args.lang, top=args.top)
    emit({"source": src_info(fog), "zoom": args.zoom, "places": ps})


def cmd_check(args):
    fog = load(args)
    res = []
    for t in args.points:
        lng, lat = parse_latlng(t)
        px, py = geo.lnglat_to_px(lng, lat)
        hit = bool(fog.explored(int(px), int(py)))
        near = fog.nearest(lng, lat)
        res.append({"point": [lat, lng], "explored": hit,
                    "within_100m": bool(fog.near_explored(lng, lat, 100)[0]),
                    "nearest_explored_m": round(near[0], 1) if near else None,
                    "nearest_explored": [round(near[2], 6), round(near[1], 6)] if near else None})
    emit({"source": src_info(fog), "note": "points are [lat, lng]", "points": res})


def cmd_around(args):
    from .places import unexplored_pockets
    fog = load(args)
    lng, lat = parse_latlng(args.point)
    r = unexplored_pockets(fog, lng, lat, args.radius_km, zoom=args.zoom, top=args.top, land_only=not args.include_water)
    r["center"] = [lat, lng]
    for p in r["pockets"]:
        p["center"] = p["center"][::-1]
        p["nearest_point"] = p["nearest_point"][::-1]
    r["note"] = ("coordinates are [lat, lng]; explored_cells_pct counts grid cells with any explored pixel; "
                 "explored_km2 is the revealed area itself")
    emit({"source": src_info(fog)} | r)


def cmd_lines(args):
    from .lines import coverage, gaps_geojson, read_lines
    fog = load(args)
    lines = read_lines(args.file)
    rs = coverage(fog, lines, group_by=args.group_by or None, step_m=args.step_m,
                  tolerance_m=args.tolerance_m, min_gap_m=args.min_gap_m)
    if args.gaps_out:
        Path(args.gaps_out).write_text(json.dumps(gaps_geojson(rs), ensure_ascii=False))
    if not args.with_coords:
        for r in rs:
            for g in r["gaps"]:
                g.pop("coords", None)
            r["gaps"] = r["gaps"][: args.max_gaps]
    tot = sum(r["length_km"] for r in rs)
    exp = sum(r["explored_km"] for r in rs)
    emit({"source": src_info(fog), "lines": len(rs), "length_km": round(tot, 1), "explored_km": round(exp, 1),
          "explored_pct": round(100 * exp / tot, 1) if tot else None, "tolerance_m": args.tolerance_m,
          "gaps_file": args.gaps_out, "results": rs if not args.top else rs[: args.top]})


def cmd_osm(args):
    from . import osm
    bbox = area_bbox(args)
    if not bbox:
        fail("give --bbox W,S,E,N or --around LAT,LNG --radius-km R")
    fc = osm.query(args.preset if not args.query else None, bbox, custom=args.query)
    Path(args.out).write_text(json.dumps(fc, ensure_ascii=False))
    names = sorted({f["properties"].get("name", "") for f in fc["features"]})
    emit({"written": args.out, "features": len(fc["features"]), "names": names[:200],
          "attribution": "© OpenStreetMap contributors (ODbL)"})


def cmd_diff(args):
    from .places import places
    old = FogMap.load(resolve_source(args.old, args.root))
    new = FogMap.load(resolve_source(args.new, args.root))
    if args.bbox:
        b = geo.parse_bbox(args.bbox)
        old, new = old.crop(b), new.crop(b)
    added, removed = new.minus(old), old.minus(new)
    out = {"old": src_info(old), "new": src_info(new),
           "old_km2": round(old.area_km2(), 2), "new_km2": round(new.area_km2(), 2),
           "added_km2": round(added.area_km2(), 2), "removed_km2": round(removed.area_km2(), 2),
           "added_by_region": places(added, lang=args.lang, top=args.top)}
    if args.out:
        from .export import polygons_geojson
        polygons_geojson(added, 16, args.out)
        out["added_geojson"] = args.out
    emit(out)


def cmd_export(args):
    from .export import cells_csv, polygons_geojson
    fog = load(args)
    if args.format == "csv":
        n = cells_csv(fog, args.zoom, args.out)
    else:
        n = polygons_geojson(fog, args.zoom, args.out, simplify_m=args.simplify_m)
    emit({"written": args.out, "format": args.format, "zoom": args.zoom, "cells": n,
          "explored_km2": round(fog.area_km2(), 2)})


def cmd_render(args):
    from .render import render
    bbox = area_bbox(args)
    args.bbox = None  # crop after choosing the area
    fog = load(args)
    if not bbox:
        bbox = fog.bbox()
        if not bbox:
            fail("nothing explored")
    overlays = []
    for p in args.overlay or []:
        overlays.append(json.loads(Path(p).read_text(encoding="utf-8")))
    if args.mark:
        feats = []
        for t in args.mark:
            lng, lat = parse_latlng(t)
            feats.append({"type": "Feature", "properties": {"color": "#377eb8"},
                          "geometry": {"type": "Point", "coordinates": [lng, lat]}})
        overlays.append({"type": "FeatureCollection", "features": feats})
    highlight = None
    if args.new_since:
        highlight = fog.minus(FogMap.load(resolve_source(args.new_since, args.root)))
    r = render(fog, bbox, args.out, max_px=args.max_px, basemap=args.basemap, overlays=overlays, highlight=highlight,
               reveal_px=args.line_px)
    emit(r | {"bbox": list(bbox)})


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fogprint", description="Read and analyse Fog of World data. Output is JSON.")
    p.add_argument("--version", action="version", version=f"fogprint {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--src", help="data to read: a Sync folder, Sync zip, .fwss snapshot or .fwdb folder; "
                                      "a database name; snapshot:YYYY-MM-DD; or 'all' (every database merged). "
                                      "Default: newest data of the main database")
    common.add_argument("--root", action="append", help="folder to search instead of the default iCloud/Dropbox folders")
    common.add_argument("--lang", default="en", choices=["en", "zh", "ja"], help="language of region names")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("locate", parents=[common], help="list Fog of World data found on this machine")
    s.set_defaults(func=cmd_locate)

    s = sub.add_parser("summary", parents=[common], help="explored area, extent, countries and regions")
    s.add_argument("--bbox", help="limit to W,S,E,N")
    s.add_argument("--no-regions", action="store_true", help="skip the country / region breakdown (no download)")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("regions", parents=[common], help="explored area per country / region")
    s.add_argument("--level", default="country",
                   help="country | admin1 (Natural Earth, worldwide) | ADM1..ADM5 (geoBoundaries, needs --country)")
    s.add_argument("--country", help="ISO 3166 alpha-3 code, e.g. JPN, USA, FRA")
    s.add_argument("--boundaries", help="your own GeoJSON of polygons instead")
    s.add_argument("--name-field", help="property holding the region name in --boundaries")
    s.add_argument("--zoom", type=int, default=16, help="grid used to assign explored area (default 16, ~0.6 km)")
    s.add_argument("--min-km2", type=float, default=0.0, help="count a region as visited only above this area")
    s.add_argument("--visited-only", action="store_true")
    s.add_argument("--unvisited-only", action="store_true")
    s.add_argument("--top", type=int)
    s.add_argument("--bbox", help="limit to W,S,E,N")
    s.add_argument("--out", help="write the full result to this JSON file")
    s.add_argument("--within", metavar="REGION", help="only regions inside this state / province / prefecture "
                                                     "(name in any language or ISO code such as JP-39)")
    s.add_argument("--geojson-out", help="write the listed regions as polygons (for render --overlay; red = unvisited)")
    s.set_defaults(func=cmd_regions)

    s = sub.add_parser("places", parents=[common], help="explored area by state / province / prefecture, with extents")
    s.add_argument("--zoom", type=int, default=14, help="grid zoom used to assign area (default 14, ~2.4 km)")
    s.add_argument("--top", type=int, default=200)
    s.add_argument("--bbox", help="limit to W,S,E,N")
    s.set_defaults(func=cmd_places)

    s = sub.add_parser("check", parents=[common], help="is a point explored, and how far is explored area")
    s.add_argument("points", nargs="+", metavar="LAT,LNG")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("around", parents=[common], help="coverage around a point and the largest unexplored pockets")
    s.add_argument("point", metavar="LAT,LNG")
    s.add_argument("--radius-km", type=float, default=10)
    s.add_argument("--zoom", type=int, default=16, help="grid zoom (default 16, ~600 m x cos(lat); 17-18 for walking)")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--include-water", action="store_true", help="also count sea cells (default: land only)")
    s.set_defaults(func=cmd_around)

    s = sub.add_parser("lines", parents=[common], help="explored share of lines: GeoJSON / GPX / KML routes, roads, railways")
    s.add_argument("file")
    s.add_argument("--group-by", default="name", help="feature property to group by ('' = each line separately)")
    s.add_argument("--tolerance-m", type=float, default=60, help="explored area within this distance counts")
    s.add_argument("--step-m", type=float, default=50)
    s.add_argument("--min-gap-m", type=float, default=300, help="report unexplored stretches at least this long")
    s.add_argument("--max-gaps", type=int, default=10)
    s.add_argument("--top", type=int)
    s.add_argument("--gaps-out", help="write unexplored stretches to this GeoJSON")
    s.add_argument("--with-coords", action="store_true", help="include gap coordinates in the output")
    s.set_defaults(func=cmd_lines)

    s = sub.add_parser("osm", parents=[common], help="download roads / railways / routes from OpenStreetMap")
    s.add_argument("preset", nargs="?", default="rail",
                   help="rail | subway | railway-tracks | motorway | major-roads | roads | streets | cycleways | hiking | ferry")
    s.add_argument("--bbox")
    s.add_argument("--around", metavar="LAT,LNG")
    s.add_argument("--radius-km", type=float, default=20)
    s.add_argument("--query", help="custom Overpass selector, e.g. 'way[\"highway\"=\"footway\"]'")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_osm)

    s = sub.add_parser("diff", parents=[common], help="what changed between two data sources (e.g. snapshots)")
    s.add_argument("old")
    s.add_argument("new")
    s.add_argument("--bbox")
    s.add_argument("--top", type=int, default=50)
    s.add_argument("--out", help="write the added area to this GeoJSON")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("export", parents=[common], help="export explored area as GeoJSON polygons or CSV cells")
    s.add_argument("--format", choices=["geojson", "csv"], default="geojson")
    s.add_argument("--zoom", type=int, default=16)
    s.add_argument("--simplify-m", type=float, default=0)
    s.add_argument("--bbox")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("render", parents=[common], help="PNG map of explored area")
    s.add_argument("--bbox")
    s.add_argument("--around", metavar="LAT,LNG")
    s.add_argument("--radius-km", type=float, default=10)
    s.add_argument("--basemap", choices=["osm", "none"], default="osm")
    s.add_argument("--overlay", action="append", help="GeoJSON lines/points to draw (property 'color')")
    s.add_argument("--mark", action="append", metavar="LAT,LNG", help="draw a marker")
    s.add_argument("--max-px", type=int, default=1600)
    s.add_argument("--new-since", metavar="SRC", help="draw area that is not in SRC (a snapshot, database or path) in blue")
    s.add_argument("--line-px", type=int, help="thicken explored area by this many pixels (default: by image size)")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_render)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (OSError, ValueError) as e:
        fail(f"{type(e).__name__}: {e}", code=1)


if __name__ == "__main__":
    main()
