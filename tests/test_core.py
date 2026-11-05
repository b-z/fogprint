import json
import zipfile

import numpy as np
import pytest

from fogprint import FogMap, geo, inspect, locate, pick_default
from fogprint.fogformat import block_from_name, decode_block, encode_block, name_for_block
from fogprint.lines import coverage

# A point in central Tokyo and its zoom-22 pixel
LNG, LAT = 139.7671, 35.6812


def pixel(lng, lat):
    x, y = geo.lnglat_to_px(lng, lat)
    return int(x), int(y)


def make_blocks(pixels):
    """{(bx, by): {(tx, ty): bool[64, 64]}} with the given zoom-22 pixels set."""
    blocks = {}
    for x, y in pixels:
        bx, by = x // 8192, y // 8192
        tx, ty = (x % 8192) // 64, (y % 8192) // 64
        tile = blocks.setdefault((bx, by), {}).setdefault((tx, ty), np.zeros((64, 64), bool))
        tile[y % 64, x % 64] = True
    return blocks


def write_sync(folder, pixels):
    folder.mkdir(parents=True, exist_ok=True)
    for (bx, by), tiles in make_blocks(pixels).items():
        (folder / name_for_block(bx, by)).write_bytes(encode_block(tiles))
    return folder


def line_pixels(lng0, lat0, lng1, lat1, n=2000, width=2):
    out = set()
    for t in np.linspace(0, 1, n):
        x, y = pixel(lng0 + (lng1 - lng0) * t, lat0 + (lat1 - lat0) * t)
        for dx in range(-width, width + 1):
            for dy in range(-width, width + 1):
                out.add((x + dx, y + dy))
    return out


def test_filename_roundtrip():
    for bx, by in [(0, 0), (454, 201), (511, 511), (7, 300)]:
        assert block_from_name(name_for_block(bx, by)) == (bx, by)
    assert block_from_name("3fd0lowwkkkk") is not None
    assert block_from_name(".DS_Store") is None
    assert block_from_name("3fd0lowwkkkk 2") == block_from_name("3fd0lowwkkkk")


def test_block_roundtrip():
    bm = np.zeros((64, 64), bool)
    bm[3, 5] = bm[63, 63] = bm[0, 0] = True
    data = encode_block({(10, 20): bm, (0, 0): np.ones((64, 64), bool)})
    tiles, bitmaps = decode_block(data, 2, 3)
    got = {tuple(t): np.unpackbits(b).reshape(64, 64).astype(bool) for t, b in zip(tiles, bitmaps)}
    assert set(got) == {(2 * 128 + 10, 3 * 128 + 20), (256, 384)}
    assert (got[(266, 404)] == bm).all()


def test_fogmap_queries(tmp_path):
    x, y = pixel(LNG, LAT)
    sync = write_sync(tmp_path / "Sync", {(x, y), (x + 1, y), (x + 100, y + 100)})
    fog = FogMap.load(sync)
    assert fog.pixel_count() == 3
    assert fog.explored([x, x + 2], [y, y]).tolist() == [True, False]
    px_km2 = (geo.pixel_size_m(LAT) / 1000) ** 2
    assert fog.area_km2() == pytest.approx(3 * px_km2, rel=0.01)
    gx, gy, gc = fog.grid(16)
    assert gc.sum() == 3
    d, nlng, nlat = fog.nearest(LNG + 0.001, LAT)
    assert 50 < d < 120
    assert fog.near_explored([LNG, LNG + 0.05], [LAT, LAT], 50).tolist() == [True, False]


def test_set_algebra(tmp_path):
    x, y = pixel(LNG, LAT)
    a = FogMap.load(write_sync(tmp_path / "a", {(x, y), (x + 1, y)}))
    b = FogMap.load(write_sync(tmp_path / "b", {(x + 1, y), (x + 5000, y)}))
    assert a.minus(b).pixel_count() == 1
    assert b.minus(a).pixel_count() == 1
    assert a.union(b).pixel_count() == 3
    assert a.intersect(b).pixel_count() == 1


def test_zip_and_snapshot_sources(tmp_path):
    x, y = pixel(LNG, LAT)
    blocks = make_blocks({(x, y)})
    (bx, by), tiles = next(iter(blocks.items()))
    name = name_for_block(bx, by)
    snap = tmp_path / "Data" / "Databases" / "Primary.fwdb" / "Snapshots" / "2026" / "Snapshot-20260101T120000+0900.fwss"
    snap.parent.mkdir(parents=True)
    with zipfile.ZipFile(snap, "w") as z:
        z.writestr(f"Model/*/{name}", encode_block(tiles))
        z.writestr(f"Model/~/{name}", b"other layer")
    zp = tmp_path / "Data" / "Sync.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(f"Sync/{name}", encode_block(tiles))
        z.writestr(f"__MACOSX/Sync/._{name}", b"junk")
    trip = write_sync(tmp_path / "Data" / "Databases" / "Trip.fwdb" / "Sync", {(x + 9, y)})

    s = inspect(snap)
    assert s.kind == "snapshot" and s.prefix == "Model/*" and s.modified.startswith("2026-01-01T12:00:00+09")
    assert FogMap.load(s).pixel_count() == 1
    assert FogMap.load(zp).pixel_count() == 1

    found = locate([tmp_path / "Data"])
    assert {f.database for f in found} == {"main", "Trip"}
    best = pick_default(found, "main")
    assert best.kind == "snapshot"  # a snapshot beats a zip of unknown date
    assert FogMap.load(pick_default(found, "Trip")).pixel_count() == 1
    assert trip.exists()


def test_line_coverage(tmp_path):
    # explored: the western half of a 2 km east-west line
    lng1 = LNG + 0.022
    mid = (LNG + lng1) / 2
    fog = FogMap.load(write_sync(tmp_path / "Sync", line_pixels(LNG, LAT, mid, LAT)))
    lines = [{"coords": [(LNG, LAT), (lng1, LAT)], "props": {"name": "test line"}}]
    (r,) = coverage(fog, lines, tolerance_m=40, min_gap_m=200)
    assert r["length_km"] == pytest.approx(2.0, rel=0.05)
    assert 40 < r["explored_pct"] < 60
    assert len(r["gaps"]) == 1 and r["gaps"][0]["km"] == pytest.approx(1.0, abs=0.15)


def test_cli_summary(tmp_path, capsys):
    from fogprint.cli import main

    x, y = pixel(LNG, LAT)
    write_sync(tmp_path / "Sync", {(x, y)})
    main(["summary", "--src", str(tmp_path / "Sync"), "--no-regions"])
    out = json.loads(capsys.readouterr().out)
    assert out["explored_pixels"] == 1
    assert out["source"]["kind"] == "sync-folder"


def test_overpass_to_geojson():
    from fogprint.osm import to_geojson

    data = {"elements": [
        {"type": "way", "tags": {"highway": "primary", "name": "A1"},
         "geometry": [{"lat": 1, "lon": 2}, {"lat": 1.1, "lon": 2.1}]},
        {"type": "relation", "tags": {"route": "train", "name": "Line X"}, "members": [
            {"type": "way", "role": "", "geometry": [{"lat": 3, "lon": 4}, {"lat": 3.1, "lon": 4.1}]},
            {"type": "node", "role": "stop"}]},
    ]}
    fc = to_geojson(data)
    assert [f["properties"]["name"] for f in fc["features"]] == ["A1", "Line X"]
    assert fc["features"][1]["geometry"]["type"] == "MultiLineString"


def test_read_gpx_kml(tmp_path):
    from fogprint.lines import read_lines

    gpx = tmp_path / "t.gpx"
    gpx.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><name>a</name><trkseg>'
                   '<trkpt lat="35" lon="139"/><trkpt lat="35.1" lon="139.1"/></trkseg></trk></gpx>')
    kml = tmp_path / "t.kml"
    kml.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>b</name>'
                   '<LineString><coordinates>139,35,0 139.1,35.1,0</coordinates></LineString></Placemark></Document></kml>')
    assert read_lines(str(gpx))[0]["props"]["name"] == "a"
    assert read_lines(str(kml))[0]["coords"] == [(139.0, 35.0), (139.1, 35.1)]
