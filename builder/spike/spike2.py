"""Spike 2 (Bremen): adaptive cell tree with admin polygons, addresses, interpolation, grouped search postings.

Throwaway research code. Run:
  pixi run python builder/spike/spike2.py fixtures/bremen/bremen.osm.pbf OUTDIR [configs...]
configs: fixedZ (e.g. fixed16) or adaptiveLIMIT (e.g. adaptive4000)
"""
import math
import pickle
import random
import re
import sqlite3
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import apsw
import numpy as np
import osmium
import shapely
import shapely.wkb as wkb
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.strtree import STRtree

Q = 1e-6          # coordinate quantum in degrees (~0.1 m)
E7 = 10_000_000
PAGE = 4096
MINZ, MAXZ = 11, 19
wkbf = osmium.geom.WKBFactory()


# ---------------------------------------------------------------- helpers
def norm_tokens(s: str) -> list[str]:
    s = s.replace("ß", "ss").replace("ẞ", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    out = []
    for t in re.split(r"[^0-9a-z]+", s):
        if not t:
            continue
        if t.endswith("str") and len(t) > 3:  # Hauptstr -> hauptstrasse
            t += "asse"
        out.append(t)
    return out


def put_varint(out: bytearray, n: int):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def zz(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def unzz(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


class Reader:
    def __init__(self, b):
        self.b, self.i = b, 0

    def v(self):
        n = s = 0
        while True:
            x = self.b[self.i]
            self.i += 1
            n |= (x & 0x7F) << s
            s += 7
            if not x & 0x80:
                return n

    def sv(self):
        return unzz(self.v())

    def bytes(self, n):
        r = self.b[self.i:self.i + n]
        self.i += n
        return r

    def more(self):
        return self.i < len(self.b)


def tile_bounds(x, y, z):
    n = 1 << z
    lon0 = x / n * 360 - 180
    lon1 = (x + 1) / n * 360 - 180
    lat = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))
    return lon0, lat(y + 1), lon1, lat(y)  # minx, miny, maxx, maxy


def lonlat_tile(lon, lat, z):
    n = 1 << z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def cell_key(x, y, z):
    k = 0
    for i in range(z):
        k |= ((x >> i) & 1) << (2 * i) | ((y >> i) & 1) << (2 * i + 1)
    return (1 << (2 * z)) | k


def meters(dlon, dlat, lat):
    return dlon * 111320 * math.cos(math.radians(lat)), dlat * 110540


# ---------------------------------------------------------------- extraction
class Collector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.admin, self.streets, self.addrs, self.interps = [], [], [], []
        self.addr_nodes = {}

    def node(self, n):
        t = n.tags
        hn = t.get("addr:housenumber")
        if hn:
            st = t.get("addr:street")
            self.addr_nodes[n.id] = (hn, st)
            if st:
                self.addrs.append((st, hn, n.location.lon, n.location.lat))

    def way(self, w):
        t = w.tags
        try:
            if "highway" in t and "name" in t:
                self.streets.append((t["name"], wkb.loads(wkbf.create_linestring(w), hex=True)))
            elif "addr:interpolation" in t:
                ids = [nd.ref for nd in w.nodes]
                self.interps.append((t["addr:interpolation"], t.get("addr:street"), ids[0], ids[-1],
                                     wkb.loads(wkbf.create_linestring(w), hex=True)))
        except Exception:
            pass

    def area(self, a):
        t = a.tags
        try:
            if t.get("boundary") == "administrative" and "name" in t and not a.from_way():
                self.admin.append((int(t.get("admin_level", "99")), t["name"],
                                   wkb.loads(wkbf.create_multipolygon(a), hex=True)))
            elif "addr:housenumber" in t and "addr:street" in t:
                c = wkb.loads(wkbf.create_multipolygon(a), hex=True).representative_point()
                self.addrs.append((t["addr:street"], t["addr:housenumber"], c.x, c.y))
        except Exception:
            pass


def prepare(pbf: str, cache: Path):
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    t0 = time.time()
    c = Collector()
    c.apply_file(pbf, locations=True)
    print(f"extract {time.time()-t0:.0f}s: admin={len(c.admin)} streets={len(c.streets)} addrs={len(c.addrs)} interps={len(c.interps)}")

    admin = sorted(c.admin, key=lambda a: (a[0], -a[2].area))
    for i, (lvl, name, g) in enumerate(admin):
        tol = 5e-5 if lvl <= 4 else 2e-5
        admin[i] = (lvl, name, shapely.make_valid(g.simplify(tol)))
    tree = STRtree([a[2] for a in admin])
    shapely.prepare([a[2] for a in admin])
    A = [dict(id=i + 1, level=l, name=n, geom=g) for i, (l, n, g) in enumerate(admin)]

    def deepest_containing(points, max_level):
        """vectorised: for each point the deepest admin (index) with level<=max_level, -1 if none"""
        res = np.full(len(points), -1)
        pi, ai = tree.query(np.array(points, dtype=object), predicate="within")
        best_level = np.full(len(points), -1)
        for p, a in zip(pi, ai):
            lv = A[a]["level"]
            if lv <= max_level and (lv > best_level[p] or (lv == best_level[p] and A[a]["geom"].area < A[res[p]]["geom"].area)):
                best_level[p] = lv
                res[p] = a
        return res

    # admin parents (smallest containing with lower level)
    reps = [a["geom"].representative_point() for a in A]
    pi, ai = tree.query(np.array(reps, dtype=object), predicate="within")
    par = {}
    for p, a in zip(pi, ai):
        if A[a]["level"] < A[p]["level"] and (p not in par or A[a]["geom"].area < A[par[p]]["geom"].area):
            par[p] = a
    for i, a in enumerate(A):
        a["parent"] = A[par[i]]["id"] if i in par else 0
    # 'city' = deepest ancestor-or-self with level <= 8
    for a in A:
        cur = a
        while cur and cur["level"] > 8:
            cur = A[cur["parent"] - 1] if cur["parent"] else None
        a["city"] = cur["id"] if cur else 0

    # street groups keyed by (city admin, normalized name)
    mids = [g.interpolate(0.5, normalized=True) for _, g in c.streets]
    sidx = deepest_containing(mids, 8)
    groups, glist = {}, []

    def gid_for(name, city):
        k = (city, " ".join(norm_tokens(name)))
        if k not in groups:
            groups[k] = len(glist) + 1
            glist.append(dict(id=groups[k], name=name, parent=city))
        return groups[k]

    street_geoms = []
    for (name, g), ai_ in zip(c.streets, sidx):
        city = A[ai_]["id"] if ai_ >= 0 else 0
        street_geoms.append((gid_for(name, city), g))

    pts = [Point(lon, lat) for _, _, lon, lat in c.addrs]
    aidx = deepest_containing(pts, 8)
    addrs = []
    for (st, hn, lon, lat), ai_ in zip(c.addrs, aidx):
        city = A[ai_]["id"] if ai_ >= 0 else 0
        addrs.append((gid_for(st, city), hn, lon, lat))

    interps = []
    for mode, st, n0, n1, g in c.interps:
        e0, e1 = c.addr_nodes.get(n0), c.addr_nodes.get(n1)
        if not (e0 and e1 and e0[0].isdigit() and e1[0].isdigit()):
            continue
        h0, h1 = e0[0], e1[0]
        st = st or e0[1] or e1[1]  # real data: street is on the endpoint nodes, not the way
        mp = g.interpolate(0.5, normalized=True)
        ai_ = deepest_containing([mp], 8)[0]
        city = A[ai_]["id"] if ai_ >= 0 else 0
        # street: from tag, else nearest street group in same city
        if st:
            gid = gid_for(st, city)
        else:
            continue
        step = {"all": 1, "even": 2, "odd": 2}.get(mode)
        if step:
            interps.append((gid, step, int(h0), int(h1), g))
    data = dict(admin=A, streets=street_geoms, groups=glist, addrs=addrs, interps=interps)
    cache.write_bytes(pickle.dumps(data))
    print(f"prepared {time.time()-t0:.0f}s: street groups={len(glist)} interps={len(interps)}")
    return data


# ---------------------------------------------------------------- cell encoding
def lines_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g] if len(g.coords) >= 2 else []
    if hasattr(g, "geoms"):
        return [l for part in g.geoms for l in lines_of(part)]
    return []


def polys_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        return [p for part in g.geoms for p in polys_of(part)]
    return []


def enc_coords(out, coords, ox, oy):
    px = py = 0
    put_varint(out, len(coords))
    for x, y in coords:
        ix, iy = round((x - ox) / Q), round((y - oy) / Q)
        put_varint(out, zz(ix - px))
        put_varint(out, zz(iy - py))
        px, py = ix, iy


def dec_coords(r, ox, oy):
    n = r.v()
    pts, px, py = [], 0, 0
    for _ in range(n):
        px += r.sv()
        py += r.sv()
        pts.append((ox + px * Q, oy + py * Q))
    return pts


def encode_node(box, adm, streets, addrs, interps):
    """adm: [(admin_id, None|geom)], streets: [(gid, geom)], addrs: [(gid,hn,lon,lat)], interps:[(gid,step,h0,h1,geom)]"""
    ox, oy = box[0], box[1]
    out = bytearray()
    put_varint(out, len(adm))
    for aid, g in adm:
        put_varint(out, aid)
        if g is None:
            put_varint(out, 0)
        else:
            polys = polys_of(g)
            put_varint(out, len(polys) + 1)
            for p in polys:
                put_varint(out, len(p.interiors) + 1)
                enc_coords(out, list(p.exterior.coords), ox, oy)
                for ring in p.interiors:
                    enc_coords(out, list(ring.coords), ox, oy)
    sl = [(gid, ls) for gid, g in streets for ls in lines_of(g)]
    put_varint(out, len(sl))
    for gid, ls in sl:
        put_varint(out, gid)
        enc_coords(out, list(ls.coords), ox, oy)
    put_varint(out, len(addrs))
    px = py = 0
    for gid, hn, lon, lat in sorted(addrs, key=lambda a: (a[0], a[1])):
        put_varint(out, gid)
        b = hn.encode()
        put_varint(out, len(b))
        out += b
        ix, iy = round((lon - ox) / Q), round((lat - oy) / Q)
        put_varint(out, zz(ix - px))
        put_varint(out, zz(iy - py))
        px, py = ix, iy
    il = [(gid, step, h0, h1, ls) for gid, step, h0, h1, g in interps for ls in lines_of(g)]
    put_varint(out, len(il))
    for gid, step, h0, h1, ls in il:
        put_varint(out, gid)
        put_varint(out, step)
        put_varint(out, h0)
        put_varint(out, h1)
        enc_coords(out, list(ls.coords), ox, oy)
    return bytes(out)


def decode_node(b, box):
    ox, oy = box[0], box[1]
    r = Reader(b)
    adm = []
    for _ in range(r.v()):
        aid, flag = r.v(), r.v()
        if flag == 0:
            adm.append((aid, None))
        else:
            polys = []
            for _ in range(flag - 1):
                rings = [dec_coords(r, ox, oy) for _ in range(r.v() - 1 + 1)]
                polys.append(rings)
            adm.append((aid, polys))
    streets = [(r.v(), dec_coords(r, ox, oy)) for _ in range(r.v())]
    addrs, px, py = [], 0, 0
    for _ in range(r.v()):
        gid = r.v()
        hn = r.bytes(r.v()).decode()
        px += r.sv()
        py += r.sv()
        addrs.append((gid, hn, ox + px * Q, oy + py * Q))
    interps = []
    for _ in range(r.v()):
        gid, step, h0, h1 = r.v(), r.v(), r.v(), r.v()
        interps.append((gid, step, h0, h1, dec_coords(r, ox, oy)))
    return dict(admin=adm, streets=streets, addrs=addrs, interps=interps)


# ---------------------------------------------------------------- tree build
def build_cells(data, minz, maxz, limit):
    A = data["admin"]
    allx = [a[2] for a in data["addrs"]] + [p for _, g in data["streets"] for p in (g.bounds[0], g.bounds[2])]
    ally = [a[3] for a in data["addrs"]] + [p for _, g in data["streets"] for p in (g.bounds[1], g.bounds[3])]
    x0, y0 = lonlat_tile(min(allx), max(ally), minz)
    x1, y1 = lonlat_tile(max(allx), min(ally), minz)
    cells = {}
    stats = defaultdict(int)

    st_tree = STRtree([g for _, g in data["streets"]])
    in_tree = STRtree([g for *_, g in data["interps"]]) if data["interps"] else None
    ad_pts = shapely.points([(a[2], a[3]) for a in data["addrs"]])
    ad_tree = STRtree(ad_pts)
    adm_tree = STRtree([a["geom"] for a in A])

    def rec(x, y, z, adm, streets, addrs, interps):
        box = tile_bounds(x, y, z)
        if not (adm or streets or addrs or interps):
            return
        too_big = len(addrs) > 3000 or sum(len(l.coords) for _, g in streets for l in lines_of(g)) > 8000
        blob = None
        if not too_big or z >= maxz:
            blob = encode_node(box, adm, streets, addrs, interps)
        if z < maxz and (blob is None or len(blob) > limit):
            mx, my = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            for i in (0, 1):
                for j in (0, 1):
                    cb = tile_bounds(2 * x + i, 2 * y + j, z + 1)
                    cadm = []
                    for aid, g in adm:
                        if g is None:
                            cadm.append((aid, None))
                            continue
                        piece = shapely.clip_by_rect(g, *cb)
                        if piece.is_empty or piece.area == 0:
                            continue
                        cbox = shapely.box(*cb)
                        cadm.append((aid, None if piece.contains(cbox) or piece.area >= cbox.area * (1 - 1e-9) else piece))
                    cst = []
                    for gid, g in streets:
                        pc = shapely.clip_by_rect(g, *cb)
                        if not pc.is_empty and lines_of(pc):
                            cst.append((gid, pc))
                    cad = [a for a in addrs if cb[0] <= a[2] < cb[2] and cb[1] <= a[3] < cb[3]]
                    cin = []
                    for t in interps:
                        pc = shapely.clip_by_rect(t[4], *cb)
                        if not pc.is_empty and lines_of(pc):
                            cin.append((*t[:4], pc))
                    rec(2 * x + i, 2 * y + j, z + 1, cadm, cst, cad, cin)
        else:
            cells[cell_key(x, y, z)] = blob
            stats[z] += 1

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            box = tile_bounds(x, y, minz)
            bx = shapely.box(*box)
            adm = []
            for ai in adm_tree.query(bx, predicate="intersects"):
                g = A[ai]["geom"]
                piece = shapely.clip_by_rect(g, *box)
                if piece.is_empty or piece.area == 0:
                    continue
                adm.append((A[ai]["id"], None if piece.area >= bx.area * (1 - 1e-9) else piece))
            st = []
            for si in st_tree.query(bx, predicate="intersects"):
                gid, g = data["streets"][si]
                pc = shapely.clip_by_rect(g, *box)
                if not pc.is_empty and lines_of(pc):
                    st.append((gid, pc))
            ad = [data["addrs"][i] for i in ad_tree.query(bx, predicate="contains")]
            inn = []
            if in_tree is not None:
                for ii in in_tree.query(bx, predicate="intersects"):
                    t = data["interps"][ii]
                    pc = shapely.clip_by_rect(t[4], *box)
                    if not pc.is_empty and lines_of(pc):
                        inn.append((*t[:4], pc))
            rec(x, y, minz, adm, st, ad, inn)
    return cells, dict(stats)


# ---------------------------------------------------------------- DB writing
def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def write_db(path: Path, data, cells):
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript(f"""
    PRAGMA page_size={PAGE};
    CREATE TABLE cell(id INTEGER PRIMARY KEY, data BLOB);
    CREATE TABLE admin(id INTEGER PRIMARY KEY, level INT, name TEXT, parent INT, city INT);
    CREATE TABLE street(id INTEGER PRIMARY KEY, name TEXT, parent INT);
    CREATE TABLE term(t TEXT, parent INT, postings BLOB, PRIMARY KEY(t, parent)) WITHOUT ROWID;
    CREATE TABLE housenumber(street_id INTEGER PRIMARY KEY, data BLOB);
    """)
    db.executemany("INSERT INTO cell VALUES (?,?)", cells.items())
    db.executemany("INSERT INTO admin VALUES (?,?,?,?,?)", [(a["id"], a["level"], a["name"], a["parent"], a["city"]) for a in data["admin"]])
    db.executemany("INSERT INTO street VALUES (?,?,?)", [(g["id"], g["name"], g["parent"]) for g in data["groups"]])
    post = defaultdict(list)
    for a in data["admin"]:
        for t in set(norm_tokens(a["name"])):
            post[(t, -1)].append(a["id"])
    for g in data["groups"]:
        for t in set(norm_tokens(g["name"])):
            post[(t, g["parent"])].append(g["id"])
    rows = []
    for (t, par), ids in post.items():
        out, prev = bytearray(), 0
        for i in sorted(ids):
            put_varint(out, i - prev)
            prev = i
        rows.append((t, par, bytes(out)))
    db.executemany("INSERT INTO term VALUES (?,?,?)", rows)
    byst = defaultdict(list)
    for gid, hn, lon, lat in data["addrs"]:
        byst[gid].append(("a", hn, lon, lat))
    ints = defaultdict(list)
    for gid, step, h0, h1, g in data["interps"]:
        ints[gid].append((step, h0, h1, g))
    for gid in set(byst) | set(ints):
        out = bytearray()
        items = sorted(byst[gid], key=lambda a: natural(a[1]))
        put_varint(out, len(items))
        plat = plon = 0
        for _, hn, lon, lat in items:
            b = hn.encode()
            put_varint(out, len(b))
            out += b
            la, lo = round(lat * E7), round(lon * E7)
            put_varint(out, zz(la - plat))
            put_varint(out, zz(lo - plon))
            plat, plon = la, lo
        put_varint(out, len(ints[gid]))
        for step, h0, h1, g in ints[gid]:
            put_varint(out, step)
            put_varint(out, h0)
            put_varint(out, h1)
            enc_coords(out, list(g.coords), 0.0, 0.0)
        db.execute("INSERT INTO housenumber VALUES (?,?)", (gid, bytes(out)))
    db.commit()
    db.execute("VACUUM")
    db.close()


# ---------------------------------------------------------------- measurement VFS
reads: set[int] = set()


class LogFile(apsw.VFSFile):
    def __init__(self, inherit, name, flags):
        super().__init__(inherit, name, flags)

    def xRead(self, amount, offset):
        for p in range(offset // PAGE, (offset + amount - 1) // PAGE + 1):
            reads.add(p)
        return super().xRead(amount, offset)


class LogVFS(apsw.VFS):
    def __init__(self):
        super().__init__("logvfs2", "")

    def xOpen(self, name, flags):
        return LogFile("", name, flags)


_vfs = LogVFS()


class Cold:
    def __init__(self, path):
        reads.clear()
        self.db = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY, vfs="logvfs2")
        self.db.pragma("cache_size", 0)

    def pages(self):
        return len(reads)


# ---------------------------------------------------------------- reverse query
def pip(rings_list, x, y):
    for rings in rings_list:
        inside = False
        for ring in rings:
            n = len(ring)
            j = n - 1
            for i in range(n):
                xi, yi = ring[i]
                xj, yj = ring[j]
                if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
        if inside:
            return True
    return False


def seg_dist(px, py, ax, ay, bx, by, lat):
    cx = math.cos(math.radians(lat)) * 111320
    cy = 110540
    px, ax, bx = px * cx, ax * cx, bx * cx
    py, ay, by = py * cy, ay * cy, by * cy
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def find_cell(db, lon, lat, maxz=MAXZ):
    for z in range(maxz, MINZ - 1, -1):
        x, y = lonlat_tile(lon, lat, z)
        row = db.execute("SELECT data FROM cell WHERE id=?", (cell_key(x, y, z),)).fetchone()
        if row:
            box = tile_bounds(x, y, z)
            return decode_node(row[0], box), box
    return None, None


def reverse(db, lon, lat, addr_radius=40.0):
    node, box = find_cell(db, lon, lat)
    if node is None:
        return None
    chain = []
    for aid, polys in node["admin"]:
        if polys is None or pip(polys, lon, lat):
            chain.append(aid)
    best = (1e9, None)

    def scan(nd):
        nonlocal best
        for gid, hn, x, y in nd["addrs"]:
            d = math.hypot(*meters(x - lon, y - lat, lat))
            if d < addr_radius and d < best[0]:
                best = (d, ("addr", gid, hn))
        if best[1] is None or best[1][0] != "addr":
            for gid, pts in nd["streets"]:
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    d = seg_dist(lon, lat, ax, ay, bx, by, lat)
                    if d < best[0] and (best[1] is None or best[1][0] != "addr"):
                        best = (d, ("street", gid, None))

    scan(node)
    # neighbour check: if nearest street is farther than the edge, look across the edge
    if best[1] is None or best[1][0] != "addr":
        r = best[0] if best[1] else 500.0
        edge = [(lon - box[0]) * 111320 * math.cos(math.radians(lat)), (box[2] - lon) * 111320 * math.cos(math.radians(lat)),
                (lat - box[1]) * 110540, (box[3] - lat) * 110540]
        offs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        for e, (ox, oy) in zip(edge, offs):
            if e < r:
                dlon = ox * (e + 0.5) / (111320 * math.cos(math.radians(lat)))
                dlat = oy * (e + 0.5) / 110540
                nn, _ = find_cell(db, lon + dlon, lat + dlat)
                if nn:
                    scan(nn)
    road = None
    if best[1]:
        road = db.execute("SELECT name,parent FROM street WHERE id=?", (best[1][1],)).fetchone()
    names = {}
    for aid in chain:
        names[aid] = db.execute("SELECT name,level FROM admin WHERE id=?", (aid,)).fetchone()
    return dict(kind=best[1][0] if best[1] else None, gid=best[1][1] if best[1] else None,
                hn=best[1][2] if best[1] else None, road=road[0] if road else None, admin=chain)


# ---------------------------------------------------------------- search query
def search(db, q, limit=5):
    parts = [p.strip() for p in q.split(",")]
    city_ids = None
    if len(parts) > 1:
        ctoks = norm_tokens(parts[-1])
        sets = []
        for i, t in enumerate(ctoks):
            hi = t[:-1] + chr(ord(t[-1]) + 1)
            ids = set()
            q_ = ("SELECT postings FROM term WHERE t>=? AND t<? AND parent=-1" if i == len(ctoks) - 1
                  else "SELECT postings FROM term WHERE t=? AND parent=-1")
            args = (t, hi) if i == len(ctoks) - 1 else (t,)
            for (blob,) in db.execute(q_, args):
                r, acc = Reader(blob), 0
                while r.more():
                    acc += r.v()
                    ids.add(acc)
            sets.append(ids)
        ids = set.intersection(*sets) if sets else set()
        city_ids = {db.execute("SELECT city FROM admin WHERE id=?", (i,)).fetchone()[0] for i in ids}
        city_ids.discard(0)
    head = parts[0]
    toks = head.split()
    number = None
    if toks and re.fullmatch(r"\d+[a-zA-Z]?", toks[-1]):
        number = toks.pop()
    elif toks and re.fullmatch(r"\d+[a-zA-Z]?", toks[0]):
        number = toks.pop(0)
    stoks = norm_tokens(" ".join(toks))
    cand = None
    for i, t in enumerate(stoks):
        ids = set()
        last = i == len(stoks) - 1
        hi = t[:-1] + chr(ord(t[-1]) + 1)
        for city in (city_ids if city_ids is not None else [None]):
            if city is None:
                rows = db.execute("SELECT postings FROM term WHERE t>=? AND t<? AND parent>=0" if last else
                                  "SELECT postings FROM term WHERE t=? AND parent>=0", (t, hi) if last else (t,))
            else:
                rows = db.execute("SELECT postings FROM term WHERE t>=? AND t<? AND parent=?" if last else
                                  "SELECT postings FROM term WHERE t=? AND parent=?", (t, hi, city) if last else (t, city))
            for (blob,) in rows:
                r, acc = Reader(blob), 0
                while r.more():
                    acc += r.v()
                    ids.add(acc)
        cand = ids if cand is None else cand & ids
    cand = sorted(cand or [])[:limit]
    res = []
    for gid in cand:
        name = db.execute("SELECT name,parent FROM street WHERE id=?", (gid,)).fetchone()
        hit = dict(gid=gid, name=name[0], lat=None, lon=None)
        if number:
            row = db.execute("SELECT data FROM housenumber WHERE street_id=?", (gid,)).fetchone()
            if row:
                r = Reader(row[0])
                plat = plon = 0
                items = {}
                for _ in range(r.v()):
                    hn = r.bytes(r.v()).decode()
                    plat += r.sv()
                    plon += r.sv()
                    items.setdefault(hn.lower(), (plat / E7, plon / E7))
                if number.lower() in items:
                    hit["lat"], hit["lon"] = items[number.lower()]
                elif number.isdigit():
                    n = int(number)
                    for _ in range(r.v()):
                        step, h0, h1 = r.v(), r.v(), r.v()
                        pts = dec_coords(r, 0.0, 0.0)
                        lo, hi_ = min(h0, h1), max(h0, h1)
                        if lo <= n <= hi_ and (step == 1 or (n - h0) % 2 == 0) and h1 != h0:
                            f = (n - h0) / (h1 - h0)
                            seglen = [math.hypot(*meters(b[0] - a[0], b[1] - a[1], a[1])) for a, b in zip(pts, pts[1:])]
                            target, acc = f * sum(seglen), 0
                            for (a, b), L in zip(zip(pts, pts[1:]), seglen):
                                if acc + L >= target and L > 0:
                                    t_ = (target - acc) / L
                                    hit["lon"], hit["lat"] = a[0] + t_ * (b[0] - a[0]), a[1] + t_ * (b[1] - a[1])
                                    hit["interp"] = True
                                    break
                                acc += L
                            break
        res.append(hit)
    return res


# ---------------------------------------------------------------- benchmark
def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def benchmark(path, data, rng):
    # reverse on sampled addresses (exact point) and offsets from streets
    addrs = rng.sample(data["addrs"], 400)
    pages, ok_street, ok_num, hit_addr = [], 0, 0, 0
    gname = {g["id"]: g["name"] for g in data["groups"]}
    for gid, hn, lon, lat in addrs:
        c = Cold(path)
        r = reverse(c.db, lon, lat)
        pages.append(c.pages())
        c.db.close()
        if r and r["kind"] == "addr":
            hit_addr += 1
            ok_street += gname[r["gid"]] == gname[gid]
            ok_num += r["hn"] == hn
    print(f"  reverse@address n=400: pages avg={statistics.mean(pages):.1f} p95={pct(pages,.95)} max={max(pages)}  "
          f"addr-hit={hit_addr/4:.0f}% street-ok={ok_street/4:.0f}% number-ok={ok_num/4:.0f}%")
    # reverse near streets: compare nearest street with brute force
    streets = data["streets"]
    geoms = [g for _, g in streets]
    tree = STRtree(geoms)
    by_gid = defaultdict(list)
    for gid2, g2 in streets:
        by_gid[gid2].append((gid2, g2))
    pages, agree, strict, n = [], 0, 0, 0
    for _ in range(400):
        gid0, g = rng.choice(streets)
        p = g.interpolate(rng.random(), normalized=True)
        lon, lat = p.x + rng.uniform(-1, 1) * 1.5e-4, p.y + rng.uniform(-1, 1) * 1e-4
        c = Cold(path)
        r = reverse(c.db, lon, lat, addr_radius=0.0)
        pages.append(c.pages())
        c.db.close()
        pt = Point(lon, lat)
        j = tree.nearest(pt)
        d_true = streets[j][1].distance(pt)
        n += 1
        if r and r["gid"]:
            d_got = min(g2.distance(pt) for gid2, g2 in by_gid[r["gid"]])
            agree += (d_got - d_true) * 111000 < 1.0  # forgive ties within 1 m
            strict += r["gid"] == streets[j][0]
    print(f"  reverse@street-offset n=400: pages avg={statistics.mean(pages):.1f} p95={pct(pages,.95)} max={max(pages)}  nearest-street-agree={agree/n*100:.0f}% (strict by-id {strict/n*100:.0f}%)")
    # search
    cname = {a["id"]: a["name"] for a in data["admin"]}
    sample = rng.sample(data["addrs"], 300)
    pages, top1, top5, coord_ok, found = [], 0, 0, 0, 0
    for gid, hn, lon, lat in sample:
        g = next(x for x in data["groups"] if x["id"] == gid) if False else data["groups"][gid - 1]
        city = cname.get(g["parent"], "")
        q = f"{g['name']} {hn}, {city}" if city else f"{g['name']} {hn}"
        c = Cold(path)
        res = search(c.db, q)
        pages.append(c.pages())
        c.db.close()
        ids = [h["gid"] for h in res]
        top1 += bool(ids and ids[0] == gid)
        top5 += gid in ids
        for h in res:
            if h["gid"] == gid and h["lat"] is not None:
                found += 1
                coord_ok += math.hypot(*meters(h["lon"] - lon, h["lat"] - lat, lat)) < 50
                break
    print(f"  search 'street N, city' n=300: pages avg={statistics.mean(pages):.1f} p95={pct(pages,.95)} max={max(pages)}  "
          f"top1={top1/3:.0f}% top5={top5/3:.0f}% located={found/3:.0f}% within50m={coord_ok/3:.0f}%")
    # type-ahead: street prefix only, in city
    pages = []
    for gid, hn, lon, lat in sample[:100]:
        g = data["groups"][gid - 1]
        city = cname.get(g["parent"], "")
        pre = g["name"][: max(3, len(g["name"]) // 2)]
        c = Cold(path)
        search(c.db, f"{pre}, {city}" if city else pre)
        pages.append(c.pages())
        c.db.close()
    print(f"  search type-ahead (half-typed street, city) n=100: pages avg={statistics.mean(pages):.1f} p95={pct(pages,.95)} max={max(pages)}")


def warm_and_interp(path, data, rng):
    db = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY, vfs="logvfs2")
    db.pragma("cache_size", 64)  # ~256 KiB: keeps b-tree interior pages, not much else
    for gid, hn, lon, lat in rng.sample(data["addrs"], 100):
        reverse(db, lon, lat)  # warm up
    out = []
    for gid, hn, lon, lat in rng.sample(data["addrs"], 300):
        reads.clear()
        reverse(db, lon, lat)
        out.append(len(reads))
    print(f"  reverse warm(256KiB cache) pages/query avg={statistics.mean(out):.1f} p95={pct(out,.95)} max={max(out)}")
    gname = {g["id"]: g["name"] for g in data["groups"]}
    cname = {a["id"]: a["name"] for a in data["admin"]}
    ok = tot = 0
    for gid, step, h0, h1, g in data["interps"]:
        grp = data["groups"][gid - 1]
        lo, hi = min(h0, h1), max(h0, h1)
        for n_ in range(lo + (1 if step == 1 else 2), hi, step):
            if (step == 2 and (n_ - h0) % 2):
                continue
            q = f"{grp['name']} {n_}, {cname.get(grp['parent'], '')}"
            res = search(db, q)
            hit = next((h for h in res if h["gid"] == gid), None)
            tot += 1
            ok += bool(hit and hit["lat"] is not None and Point(hit["lon"], hit["lat"]).distance(g) * 111000 < 3)
    print(f"  interpolated house numbers resolved on-line: {ok}/{tot}")
    db.close()


def main():
    pbf, outdir = sys.argv[1], Path(sys.argv[2])
    configs = sys.argv[3:] or ["fixed16", "adaptive4000"]
    outdir.mkdir(parents=True, exist_ok=True)
    data = prepare(pbf, outdir / "prepared.pkl")
    rng = random.Random(7)
    for cfg in configs:
        t0 = time.time()
        if cfg.startswith("fixed"):
            z = int(cfg[5:])
            cells, st = build_cells(data, z, z, 10**9)
        else:
            cells, st = build_cells(data, MINZ, MAXZ, int(cfg[8:]))
        path = outdir / f"{Path(pbf).stem.split(".")[0]}_{cfg}.sqlite"
        write_db(path, data, cells)
        sizes = [len(b) for b in cells.values()]
        db = sqlite3.connect(path)
        parts = dict(db.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"))
        db.close()
        print(f"\n== {cfg}: build {time.time()-t0:.0f}s  file={path.stat().st_size/1024/1024:.2f} MiB  cells={len(cells)} "
              f"blob avg={statistics.mean(sizes):.0f} p95={pct(sizes,.95)} max={max(sizes)} >1page={sum(s>PAGE-100 for s in sizes)}  by-zoom={st}")
        print("  tables KiB: " + ", ".join(f"{k}={v/1024:.0f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1])[:6]))
        benchmark(path, data, rng)
        warm_and_interp(path, data, rng)


if __name__ == "__main__":
    main()
