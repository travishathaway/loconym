"""Week-1 spike: build Monaco into two SQLite variants (R*Tree vs cell blobs) and compare sizes.

Not production code. Run: pixi run python builder/spike/spike.py fixtures/monaco/monaco.osm.pbf /tmp/out
"""
import math
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import osmium
import shapely.wkb as wkb
from shapely.geometry import Point
from shapely.strtree import STRtree

E7 = 10_000_000
CELL_Z = 16
wkbf = osmium.geom.WKBFactory()


def norm_tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^0-9a-z]+", s) if t]


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def zz(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def quadkey(lat: float, lon: float, z: int) -> int:
    n = 1 << z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return (y << z) | x  # row-major; fine for the spike


class Collector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.admin = []    # (osm_id, level, name, geom)
        self.streets = []  # (osm_id, name, linestring)
        self.addrs = []    # (osm_id, street, number, lon, lat)

    def way(self, w):
        t = w.tags
        if "highway" in t and "name" in t:
            try:
                g = wkb.loads(wkbf.create_linestring(w), hex=True)
                self.streets.append((w.id, t["name"], g))
            except Exception:
                pass

    def node(self, n):
        t = n.tags
        if "addr:housenumber" in t and "addr:street" in t:
            self.addrs.append((n.id, t["addr:street"], t["addr:housenumber"], n.location.lon, n.location.lat))

    def area(self, a):
        t = a.tags
        if t.get("boundary") == "administrative" and "name" in t and not a.from_way():
            try:
                g = wkb.loads(wkbf.create_multipolygon(a), hex=True)
                self.admin.append((a.orig_id(), int(t.get("admin_level", "99")), t["name"], g))
            except Exception as e:
                print("admin area failed:", a.orig_id(), repr(e))
        elif "addr:housenumber" in t and "addr:street" in t:
            try:
                c = wkb.loads(wkbf.create_multipolygon(a), hex=True).centroid
                self.addrs.append((a.orig_id(), t["addr:street"], t["addr:housenumber"], c.x, c.y))
            except Exception:
                pass


def build(pbf: str, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    c = Collector()
    c.apply_file(pbf, locations=True)
    print(f"admin={len(c.admin)} streets={len(c.streets)} addrs={len(c.addrs)}")

    # --- admin hierarchy: parent = smallest containing area with a lower level
    admin = sorted(c.admin, key=lambda a: a[1])
    tree = STRtree([a[3] for a in admin])

    def parent_of(pt: Point, below_level=99):
        best = None
        for i in tree.query(pt, predicate="within"):
            a = admin[i]
            if a[1] < below_level and (best is None or a[3].area < admin[best][3].area):
                best = i
        return best

    places = []  # (id, kind, rank, name, parent, lat7, lon7, minlat,minlon,maxlat,maxlon, poly)
    pid = 0
    admin_ids = {}
    for i, (oid, lvl, name, g) in enumerate(admin):
        pid += 1
        admin_ids[i] = pid
    for i, (oid, lvl, name, g) in enumerate(admin):
        p = parent_of(g.representative_point(), lvl)
        b = g.bounds
        cpt = g.representative_point()
        places.append((admin_ids[i], 0, lvl * 2, name, admin_ids.get(p, 0), round(cpt.y * E7), round(cpt.x * E7),
                       b[1], b[0], b[3], b[2], None))
    street_groups = {}  # (parent, normname) -> street place id
    for oid, name, g in c.streets:
        mid = g.interpolate(0.5, normalized=True)
        p = parent_of(mid)
        par = admin_ids.get(p, 0)
        key = (par, " ".join(norm_tokens(name)))
        pts = list(g.coords)
        poly = bytearray()
        px = py = 0
        for x, y in pts:
            ix, iy = round(x * 1e6), round(y * 1e6)  # ~0.1 m
            poly += varint(zz(ix - px)) + varint(zz(iy - py))
            px, py = ix, iy
        pid += 1
        street_groups.setdefault(key, pid)
        b = g.bounds
        places.append((pid, 1, 26, name, par, round(mid.y * E7), round(mid.x * E7), b[1], b[0], b[3], b[2], bytes(poly)))

    # housenumbers grouped by street (parent, normname)
    hn = defaultdict(list)
    for oid, street, num, lon, lat in c.addrs:
        p = parent_of(Point(lon, lat))
        key = (admin_ids.get(p, 0), " ".join(norm_tokens(street)))
        hn[key].append((num, round(lat * E7), round(lon * E7)))
    print(f"streets(groups)={len(street_groups)} hn_groups={len(hn)} hn_rows={sum(map(len, hn.values()))}")

    def common(db):
        db.executescript("""
        PRAGMA page_size=4096;
        CREATE TABLE meta(k TEXT PRIMARY KEY, v) WITHOUT ROWID;
        CREATE TABLE place(id INTEGER PRIMARY KEY, kind INT, rank INT, name TEXT, parent INT, lat INT, lon INT);
        CREATE TABLE term(t TEXT PRIMARY KEY, postings BLOB) WITHOUT ROWID;
        CREATE TABLE housenumber(street_id INTEGER PRIMARY KEY, data BLOB);
        """)
        db.executemany("INSERT INTO place VALUES (?,?,?,?,?,?,?)", [p[:7] for p in places])
        postings = defaultdict(list)
        for p in places:
            for t in set(norm_tokens(p[3])):
                postings[t].append(p[0])
        for t, ids in postings.items():
            out, prev = bytearray(), 0
            for i in sorted(ids):
                out += varint(i - prev)
                prev = i
            db.execute("INSERT INTO term VALUES (?,?)", (t, bytes(out)))
        for key, rows in hn.items():
            sid = street_groups.get(key)
            if sid is None:
                continue
            rows.sort()
            out = bytearray()
            plat = plon = 0
            for num, la, lo in rows:
                nb = num.encode()
                out += varint(len(nb)) + nb + varint(zz(la - plat)) + varint(zz(lo - plon))
                plat, plon = la, lo
            db.execute("INSERT OR REPLACE INTO housenumber VALUES (?,?)", (sid, bytes(out)))

    # Variant A: R*Tree over place bboxes + polyline blobs in a side table
    pa = outdir / "a_rtree.sqlite"
    pa.unlink(missing_ok=True)
    db = sqlite3.connect(pa)
    common(db)
    db.executescript("CREATE VIRTUAL TABLE rt USING rtree(id, minlat, maxlat, minlon, maxlon);"
                     "CREATE TABLE geom(id INTEGER PRIMARY KEY, poly BLOB);")
    db.executemany("INSERT INTO rt VALUES (?,?,?,?,?)", [(p[0], p[7], p[9], p[8], p[10]) for p in places if p[1] > 0])
    db.executemany("INSERT INTO geom VALUES (?,?)", [(p[0], p[11]) for p in places if p[11]])
    db.commit(); db.execute("VACUUM"); db.close()

    # Variant B: cell blobs (street polylines inlined, one entry per overlapped cell)
    pb = outdir / "b_cells.sqlite"
    pb.unlink(missing_ok=True)
    db = sqlite3.connect(pb)
    common(db)
    db.execute("CREATE TABLE cell(id INTEGER PRIMARY KEY, data BLOB)")
    cells = defaultdict(bytearray)
    for p in places:
        if p[1] == 0:
            continue
        cs = {quadkey(la, lo, CELL_Z) for la in (p[7], p[9]) for lo in (p[8], p[10])}
        for cid in cs:
            poly = p[11] or b""
            cells[cid] += varint(p[0]) + varint(len(poly)) + poly
    db.executemany("INSERT INTO cell VALUES (?,?)", [(k, bytes(v)) for k, v in cells.items()])
    db.commit(); db.execute("VACUUM"); db.close()

    for f in (pa, pb):
        d = sqlite3.connect(f)
        print(f"\n{f.name}: {f.stat().st_size/1024:.1f} KiB")
        try:
            for name, size, n in d.execute("SELECT name, SUM(pgsize), COUNT(*) FROM dbstat GROUP BY name ORDER BY 2 DESC LIMIT 8"):
                print(f"  {name:28s}{size/1024:8.1f} KiB")
        except sqlite3.OperationalError as e:
            print("  dbstat unavailable:", e)


if __name__ == "__main__":
    build(sys.argv[1], Path(sys.argv[2]))
