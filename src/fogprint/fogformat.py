"""Decoding of Fog of World "Sync" block files.

The world is a Web Mercator square of 2**22 x 2**22 pixels (about 9.5 m per
pixel at the equator), split into 512 x 512 blocks of 8192 x 8192 pixels.
Each block is one file. A block file is zlib-compressed; once inflated it is

    [0, 32768)   a 128 x 128 little-endian uint16 index; each cell holds the
                 1-based number N of a 64 x 64 pixel tile record, 0 = empty
    32768 + 515 * (N - 1)
                 the record: 512 bytes of bitmap (64 rows of 8 bytes, most
                 significant bit first, 1 = explored) and 3 trailing bytes
                 that are not needed here.

A 64 x 64 tile is exactly an XYZ map tile at zoom 16, and a block is an XYZ
tile at zoom 9. The coordinates are WGS 84 (real GPS, no China offset).

The file name encodes the block number ``512 * y + x``: four hex characters,
then the decimal digits of the number written with the alphabet
``olhwjsktri`` (o = 0, l = 1, ...), then two check characters.
"""

from __future__ import annotations

import re
import zlib

import numpy as np

WORLD_PX = 1 << 22
BLOCKS_PER_SIDE = 512
BLOCK_PX = 8192
TILES_PER_BLOCK_SIDE = 128
TILE_PX = 64
TILE_ZOOM = 16  # a 64 px tile is an XYZ tile at this zoom
PIXEL_ZOOM = 22  # one bitmap pixel is an XYZ "tile" at this zoom
INDEX_BYTES = TILES_PER_BLOCK_SIDE * TILES_PER_BLOCK_SIDE * 2
BITMAP_BYTES = TILE_PX * TILE_PX // 8
RECORD_BYTES = BITMAP_BYTES + 3

DIGITS = "olhwjsktri"
CHECK = "eizxdwknmo"
NAME_RE = re.compile(r"^[0-9a-f]{4}[%s]+[%s]{2}$" % (DIGITS, CHECK))


def block_from_name(name: str) -> tuple[int, int] | None:
    """Return the block (x, y) encoded in a file name, or None."""
    core = name.split(" ")[0]  # "abcd... 2" copies made by iCloud
    if not NAME_RE.match(core):
        return None
    num = int("".join(str(DIGITS.index(c)) for c in core[4:-2]))
    x, y = num % BLOCKS_PER_SIDE, num // BLOCKS_PER_SIDE
    if y >= BLOCKS_PER_SIDE:
        return None
    return x, y


def name_for_block(x: int, y: int) -> str:
    """Build a file name for block (x, y). Only the decoded part is meaningful;
    the hash prefix and check characters are placeholders. Used by tests."""
    num = y * BLOCKS_PER_SIDE + x
    return "0000" + "".join(DIGITS[int(c)] for c in str(num)) + "ee"


def decode_block(data: bytes, bx: int, by: int) -> tuple[np.ndarray, np.ndarray]:
    """Decode one compressed block file.

    Returns ``(tiles, bitmaps)``: ``tiles`` is an (n, 2) int32 array of global
    zoom-16 tile coordinates (x, y); ``bitmaps`` is an (n, 512) uint8 array of
    packed 64 x 64 bitmaps (row-major, most significant bit first).
    Empty tiles are dropped.
    """
    raw = zlib.decompress(data)
    index = np.frombuffer(raw, dtype="<u2", count=TILES_PER_BLOCK_SIDE ** 2)
    cells = np.nonzero(index)[0]
    if len(cells) == 0:
        return np.zeros((0, 2), np.int32), np.zeros((0, BITMAP_BYTES), np.uint8)
    body = np.frombuffer(raw, dtype=np.uint8, offset=INDEX_BYTES)
    n_rec = len(body) // RECORD_BYTES
    records = body[: n_rec * RECORD_BYTES].reshape(n_rec, RECORD_BYTES)
    numbers = index[cells].astype(np.int64) - 1
    ok = numbers < n_rec
    cells, numbers = cells[ok], numbers[ok]
    bitmaps = records[numbers, :BITMAP_BYTES].copy()
    keep = bitmaps.any(axis=1)
    cells, bitmaps = cells[keep], bitmaps[keep]
    tx = bx * TILES_PER_BLOCK_SIDE + cells % TILES_PER_BLOCK_SIDE
    ty = by * TILES_PER_BLOCK_SIDE + cells // TILES_PER_BLOCK_SIDE
    return np.stack([tx, ty], axis=1).astype(np.int32), bitmaps


def encode_block(tiles: dict[tuple[int, int], np.ndarray]) -> bytes:
    """Encode local tiles {(tx, ty): bool[64, 64]} into a block file.
    Used by tests to build synthetic archives."""
    index = np.zeros(TILES_PER_BLOCK_SIDE ** 2, dtype="<u2")
    body = bytearray()
    for n, ((tx, ty), bm) in enumerate(sorted(tiles.items()), start=1):
        index[ty * TILES_PER_BLOCK_SIDE + tx] = n
        body += np.packbits(np.asarray(bm, bool).reshape(-1)).tobytes() + b"\0\0\0"
    return zlib.compress(index.tobytes() + bytes(body))
