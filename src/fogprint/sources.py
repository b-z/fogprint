"""Finding and reading Fog of World data.

Fog of World keeps its data in a cloud-synced folder (iCloud Drive or
Dropbox, chosen in the app's settings). Inside it, things this module reads:

* ``Sync/`` - the live data of the main database, one file per block;
* ``Sync*.zip`` - exports or backups of such a folder;
* ``Databases/<name>.fwdb/Sync/`` - extra databases created in the app
  (often one per trip);
* ``Databases/<name>.fwdb/Snapshots/**/Snapshot-<time>.fwss`` - dated
  snapshots; a zip whose ``Model/*/`` holds the same block files.
"""

from __future__ import annotations

import os
import platform
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .fogformat import block_from_name

APP_FOLDER = "iCloud~com~ollix~FogOfWorld"
SNAPSHOT_RE = re.compile(r"Snapshot-(\d{8}T\d{6})([+-]\d{4}|Z)?")


def default_roots() -> list[Path]:
    """Folders where Fog of World data usually lives on this machine."""
    home = Path.home()
    roots = []
    env = os.environ.get("FOGPRINT_DATA")
    if env:
        roots.append(Path(env).expanduser())
    roots += [
        home / "Library/Mobile Documents" / APP_FOLDER / "Documents",  # macOS
        home / "iCloudDrive" / APP_FOLDER / "Documents",  # Windows iCloud
        home / "iCloudDrive" / APP_FOLDER,
        home / "Dropbox/Apps/Fog of World",  # Dropbox sync
        home / "Dropbox/Apps/FogOfWorld",
        home / "Dropbox/Fog of World",
    ]
    if platform.system() == "Windows":
        prof = os.environ.get("USERPROFILE")
        if prof:
            roots.append(Path(prof) / "iCloudDrive" / APP_FOLDER)
    seen, out = set(), []
    for r in roots:
        if r not in seen and r.exists():
            seen.add(r)
            out.append(r)
    return out


@dataclass
class Source:
    path: str  # file or folder on disk
    kind: str  # "sync-folder" | "zip" | "snapshot"
    database: str  # "main" or the .fwdb name
    modified: str  # ISO time: snapshot time, else file/folder mtime
    blocks: int = 0
    prefix: str = ""  # folder inside the zip that holds the blocks
    note: str = field(default="")

    def as_dict(self):
        return asdict(self)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _block_files(folder: Path) -> list[Path]:
    try:
        return [p for p in folder.iterdir() if p.is_file() and block_from_name(p.name)]
    except OSError:
        return []


def _zip_prefix(path: Path) -> tuple[str, int]:
    """Find the folder inside a zip that holds block files."""
    try:
        with zipfile.ZipFile(path) as z:
            counts: dict[str, int] = {}
            for n in z.namelist():
                if n.endswith("/") or "__MACOSX" in n:
                    continue
                folder, _, base = n.rpartition("/")
                if block_from_name(base):
                    counts[folder] = counts.get(folder, 0) + 1
    except (zipfile.BadZipFile, OSError):
        return "", 0
    if not counts:
        return "", 0
    # Snapshots hold several layers; the explored-area layer is "Model/*".
    if "Model/*" in counts:
        return "Model/*", counts["Model/*"]
    best = max(counts, key=counts.get)
    return best, counts[best]


def _snapshot_time(path: Path) -> str | None:
    m = SNAPSHOT_RE.search(path.name)
    if not m:
        return None
    t = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
    tz = m.group(2)
    if tz and tz != "Z":
        return t.isoformat() + tz[:3] + ":" + tz[3:]
    return t.isoformat() + ("Z" if tz == "Z" else "")


def inspect(path: str | Path, database: str = "main") -> Source | None:
    """Describe a single path (folder, zip or snapshot) as a Source."""
    p = Path(path).expanduser()
    if p.is_dir():
        if p.suffix == ".fwdb" and (p / "Sync").is_dir():
            return inspect(p / "Sync", p.stem)
        files = _block_files(p)
        if not files and (p / "Sync").is_dir():
            return inspect(p / "Sync", database)
        if not files:
            return None
        mtime = max(f.stat().st_mtime for f in files)
        return Source(str(p), "sync-folder", database, _iso(mtime), len(files))
    if p.is_file() and zipfile.is_zipfile(p):
        prefix, n = _zip_prefix(p)
        if not n:
            return None
        snap = _snapshot_time(p)
        kind = "snapshot" if snap else "zip"
        return Source(str(p), kind, database, snap or _iso(p.stat().st_mtime), n, prefix)
    return None


def locate(roots: list[Path] | None = None) -> list[Source]:
    """Find every readable data source under the given (or default) roots."""
    roots = default_roots() if roots is None else [Path(r).expanduser() for r in roots]
    found: list[Source] = []
    seen: set[str] = set()

    def add(s: Source | None):
        if s and s.path not in seen:
            seen.add(s.path)
            found.append(s)

    for root in roots:
        if not root.exists():
            continue
        s = inspect(root)
        if s and root.is_file():
            add(s)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x != "__MACOSX"]
            db = next((part[:-5] for part in reversed(d.parts) if part.endswith(".fwdb")), "main")
            if db == "Primary":
                db = "main"
            if d.name == "Sync" or _block_files(d):
                add(inspect(d, db))
                dirnames[:] = []
                continue
            for f in filenames:
                if f.endswith((".zip", ".fwss")):
                    add(inspect(d / f, db))
    found.sort(key=lambda s: s.modified, reverse=True)
    return found


KIND_RANK = {"sync-folder": 0, "snapshot": 1, "zip": 2}


def pick_default(sources: list[Source], database: str = "main") -> Source | None:
    """Best source of a database: its live Sync folder, else its newest
    snapshot, else the newest zip. Zips are exports whose content date is
    unknown, so they come last."""
    pool = [s for s in sources if s.database == database] or sources
    if not pool:
        return None
    return min(pool, key=lambda s: (KIND_RANK.get(s.kind, 9), _neg_time(s.modified)))


def _neg_time(iso: str) -> float:
    try:
        return -datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def databases(sources: list[Source]) -> dict[str, Source]:
    """The best source of every database."""
    return {db: pick_default(sources, db) for db in sorted({s.database for s in sources})}


def iter_blocks(src: Source) -> Iterator[tuple[int, int, bytes]]:
    """Yield (block_x, block_y, compressed_bytes) for every block of a source.
    If a block appears twice (iCloud "name 2" copies), the first one wins."""
    seen: set[tuple[int, int]] = set()
    if src.kind == "sync-folder":
        for f in sorted(_block_files(Path(src.path)), key=lambda p: (" " in p.name, p.name)):
            xy = block_from_name(f.name)
            if xy and xy not in seen:
                seen.add(xy)
                yield xy[0], xy[1], f.read_bytes()
        return
    with zipfile.ZipFile(src.path) as z:
        names = [n for n in z.namelist() if n.rpartition("/")[0] == src.prefix]
        for n in sorted(names, key=lambda n: (" " in n, n)):
            xy = block_from_name(n.rpartition("/")[2])
            if xy and xy not in seen:
                seen.add(xy)
                yield xy[0], xy[1], z.read(n)
