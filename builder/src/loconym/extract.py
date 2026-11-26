"""Stage 1: read an .osm.pbf and stream features into a scratch SQLite database.

Pass 1 collects administrative boundaries (needed to assign streets/addresses to cities).
Pass 2 streams streets, addresses and interpolation ways; bulk rows go to scratch tables so memory stays
bounded by the number of street *groups*, not addresses.
"""
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import osmium
import shapely
import shapely.wkb as wkb
from shapely.strtree import STRtree

from .codec import lonlat_tile, tile_bounds
from .normalize import normalize_key
from .poi import poi_class, poi_name

ROOT_ZOOM = 12
BATCH = 50_000
_wkbf = osmium.geom.WKBFactory()


@dataclass
class Admin:
    id: int
    level: int
    name: str
    geom: object
    parent: int = 0
    city: int = 0


@dataclass
class Extracted:
    admins: list
    groups: list            # [(tmp_gid, name, city_id)] in tmp gid order (index = tmp_gid - 1)
    group_point: dict       # tmp_gid -> (lon, lat) representative point
    interps: list           # [(tmp_gid, step, first, last, LineString)]
    bbox: tuple
    counts: dict = field(default_factory=dict)


# ------------------------------------------------------------------ pass 1
class _AdminCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def area(self, a):
        t = a.tags
        if t.get("boundary") != "administrative" or "name" not in t or a.from_way():
            return
        try:
            g = wkb.loads(_wkbf.create_multipolygon(a), hex=True)
            self.rows.append((int(t.get("admin_level", "99")), t["name"], g))
        except Exception:
            pass


def collect_admins(pbf: str, city_level: int, idx: str = "flex_mem") -> list[Admin]:
    c = _AdminCollector()
    # the filter limits multipolygon assembly to relations that carry a boundary tag
    c.apply_file(pbf, locations=True, idx=idx, filters=[osmium.filter.KeyFilter("boundary")])
    rows = sorted(c.rows, key=lambda r: (r[0], -r[2].area))
    admins = []
    for lvl, name, g in rows:
        tol = 5e-5 if lvl <= 4 else 2e-5
        g = shapely.make_valid(g.simplify(tol))
        if g.is_empty:
            continue
        admins.append(Admin(len(admins) + 1, lvl, name, g))
    shapely.prepare([a.geom for a in admins])
    tree = STRtree([a.geom for a in admins])
    rep_pts = [a.geom.representative_point() for a in admins]
    reps = shapely.points([(p.x, p.y) for p in rep_pts]) if admins else []
    if admins:
        pi, ai = tree.query(reps, predicate="within")
        best = {}
        for p, a in zip(pi, ai):
            if admins[a].level < admins[p].level and (p not in best or admins[a].geom.area < admins[best[p]].geom.area):
                best[p] = a
        for p, a in best.items():
            admins[p].parent = admins[a].id
    for a in admins:
        cur = a
        while cur and cur.level > city_level:
            cur = admins[cur.parent - 1] if cur.parent else None
        a.city = cur.id if cur else 0
    return admins


class CityAssigner:
    """Deepest admin area with level <= city_level containing a point (0 if none)."""

    def __init__(self, admins: list[Admin], city_level: int):
        self.items = [a for a in admins if a.level <= city_level]
        self.tree = STRtree([a.geom for a in self.items]) if self.items else None
        self.areas = [a.geom.area for a in self.items]

    def assign(self, xs, ys) -> list[int]:
        n = len(xs)
        out = [0] * n
        if not self.items or n == 0:
            return out
        pi, ai = self.tree.query(shapely.points(xs, ys), predicate="within")
        bl, ba = [-1] * n, [0.0] * n
        for p, a in zip(pi.tolist(), ai.tolist()):
            lv, ar = self.items[a].level, self.areas[a]
            if lv > bl[p] or (lv == bl[p] and ar < ba[p]):
                bl[p], ba[p], out[p] = lv, ar, self.items[a].id
        return out


# ------------------------------------------------------------------ pass 2
SCRATCH_SCHEMA = """
CREATE TABLE way(gid INT, root INT, wkb BLOB);
CREATE TABLE addr(gid INT, root INT, hn TEXT, lon REAL, lat REAL);
CREATE TABLE anode(id INTEGER PRIMARY KEY, hn TEXT, street TEXT);
CREATE TABLE poi(root INT, name TEXT, cls TEXT, rank INT, city INT, lon REAL, lat REAL, street TEXT, hn TEXT);
"""


def root_key(x: int, y: int) -> int:
    return (x << 20) | y


def root_xy(k: int) -> tuple[int, int]:
    return k >> 20, k & 0xFFFFF


class _Collector(osmium.SimpleHandler):
    def __init__(self, db, assigner, bbox_acc, poi=True):
        super().__init__()
        self.db, self.assigner, self.poi = db, assigner, poi
        self.poi_buf, self.n_pois = [], 0
        self.groups, self.group_index = [], {}
        self.group_point, self.group_len = {}, {}
        self.way_buf, self.addr_buf, self.anode_buf, self.interp_raw = [], [], [], []
        self.n_ways = self.n_addrs = 0
        self.bbox = bbox_acc

    # -- group registry
    def gid(self, name: str, city: int) -> int:
        k = (city, normalize_key(name))
        g = self.group_index.get(k)
        if g is None:
            g = len(self.groups) + 1
            self.group_index[k] = g
            self.groups.append((g, name, city))
        return g

    def _grow_bbox(self, x0, y0, x1, y1):
        b = self.bbox
        b[0], b[1], b[2], b[3] = min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)

    # -- handlers
    def node(self, n):
        t = n.tags
        if self.poi and n.location.valid():
            self._add_poi(t, n.location.lon, n.location.lat)
        hn = t.get("addr:housenumber")
        if not hn:
            return
        st = t.get("addr:street")
        self.anode_buf.append((n.id, hn, st))   # kept so interpolation endpoints can be resolved later
        if len(self.anode_buf) >= BATCH:
            self.flush_anodes()
        if st and n.location.valid():
            self._add_addr(st, hn, n.location.lon, n.location.lat)

    def way(self, w):
        t = w.tags
        try:
            if "highway" in t and "name" in t:
                self.way_buf.append((t["name"], wkb.loads(_wkbf.create_linestring(w), hex=True)))
                if len(self.way_buf) >= BATCH:
                    self.flush_ways()
            elif "addr:interpolation" in t:
                refs = [nd.ref for nd in w.nodes]
                self.interp_raw.append((t["addr:interpolation"], t.get("addr:street"), refs[0], refs[-1],
                                        wkb.loads(_wkbf.create_linestring(w), hex=True)))
        except Exception:
            pass

    def area(self, a):
        t = a.tags
        is_addr = "addr:housenumber" in t and "addr:street" in t
        is_poi = self.poi and poi_class(t) is not None
        if is_addr or is_poi:
            try:
                p = wkb.loads(_wkbf.create_multipolygon(a), hex=True).representative_point()
                if is_addr:
                    self._add_addr(t["addr:street"], t["addr:housenumber"], p.x, p.y)
                if is_poi:
                    self._add_poi(t, p.x, p.y)
            except Exception:
                pass

    def _add_poi(self, tags, lon, lat):
        c = poi_class(tags)
        if c is None:
            return
        key, value, rank = c
        self.poi_buf.append((poi_name(tags), f"{key}={value}", rank, lon, lat, tags.get("addr:street") or None,
                             tags.get("addr:housenumber") or None))
        if len(self.poi_buf) >= BATCH:
            self.flush_pois()

    def _add_addr(self, st, hn, lon, lat):
        self.addr_buf.append((st, hn, lon, lat))
        if len(self.addr_buf) >= BATCH:
            self.flush_addrs()

    # -- flushing
    def flush_pois(self):
        buf, self.poi_buf = self.poi_buf, []
        if not buf:
            return
        cities = self.assigner.assign([b[3] for b in buf], [b[4] for b in buf])
        rows = []
        for (name, cls, rank, lon, lat, street, hn), city in zip(buf, cities):
            self._grow_bbox(lon, lat, lon, lat)
            rx, ry = lonlat_tile(lon, lat, ROOT_ZOOM)
            rows.append((root_key(rx, ry), name, cls, rank, city, lon, lat, street, hn))
        self.db.executemany("INSERT INTO poi VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.n_pois += len(buf)

    def flush_ways(self):
        buf, self.way_buf = self.way_buf, []
        if not buf:
            return
        mids = [g.interpolate(0.5, normalized=True) for _, g in buf]
        cities = self.assigner.assign([m.x for m in mids], [m.y for m in mids])
        rows = []
        for (name, g), city in zip(buf, cities):
            gid = self.gid(name, city)
            if g.length > self.group_len.get(gid, -1):
                self.group_len[gid] = g.length
                m = g.interpolate(0.5, normalized=True)
                self.group_point[gid] = (m.x, m.y)
            x0, y0, x1, y1 = g.bounds
            self._grow_bbox(x0, y0, x1, y1)
            ax, ay = lonlat_tile(x0, y1, ROOT_ZOOM)
            bx, by = lonlat_tile(x1, y0, ROOT_ZOOM)
            data = wkb.dumps(g)
            for rx in range(ax, bx + 1):
                for ry in range(ay, by + 1):
                    if (rx, ry) == (ax, ay) == (bx, by) or g.intersects(shapely.box(*tile_bounds(rx, ry, ROOT_ZOOM))):
                        rows.append((gid, root_key(rx, ry), data))
        self.db.executemany("INSERT INTO way VALUES (?,?,?)", rows)
        self.n_ways += len(buf)

    def flush_anodes(self):
        buf, self.anode_buf = self.anode_buf, []
        self.db.executemany("INSERT OR REPLACE INTO anode VALUES (?,?,?)", buf)

    def flush_addrs(self):
        buf, self.addr_buf = self.addr_buf, []
        if not buf:
            return
        cities = self.assigner.assign([b[2] for b in buf], [b[3] for b in buf])
        rows = []
        for (st, hn, lon, lat), city in zip(buf, cities):
            gid = self.gid(st, city)
            self.group_point.setdefault(gid, (lon, lat))
            self._grow_bbox(lon, lat, lon, lat)
            rx, ry = lonlat_tile(lon, lat, ROOT_ZOOM)
            rows.append((gid, root_key(rx, ry), hn, lon, lat))
        self.db.executemany("INSERT INTO addr VALUES (?,?,?,?,?)", rows)
        self.n_addrs += len(buf)


def _pass_index(node_index: str, n: int) -> str:
    """Each pass needs its own file-backed node index (a reused file would keep the previous pass's nodes)."""
    if "," not in node_index:
        return node_index
    kind, path = node_index.split(",", 1)
    Path(f"{path}.{n}").unlink(missing_ok=True)
    return f"{kind},{path}.{n}"


FEATURE_KEYS = ("highway", "addr:housenumber", "addr:interpolation")
POI_KEYS = ("tourism", "historic", "leisure", "natural", "man_made", "amenity", "railway", "aeroway", "shop")


def extract(pbf: str, scratch_path: str, city_level: int = 8, log=print, *, boundaries_pbf: str | None = None,
            node_index: str = "flex_mem", poi: bool = True) -> Extracted:
    """boundaries_pbf: optional smaller file holding just the admin boundary relations (see prefilter.py);
    node_index: libosmium location index ('flex_mem' or e.g. 'sparse_file_array,/path/nodes.idx')."""
    log("pass 1: administrative boundaries")
    admins = collect_admins(boundaries_pbf or pbf, city_level, _pass_index(node_index, 1))
    log(f"  {len(admins)} admin areas")
    assigner = CityAssigner(admins, city_level)
    db = sqlite3.connect(scratch_path)
    db.executescript("PRAGMA journal_mode=off; PRAGMA synchronous=off;" + SCRATCH_SCHEMA)
    log("pass 2: streets, addresses, interpolation" + (", POIs" if poi else ""))
    bbox = [180.0, 90.0, -180.0, -90.0]
    c = _Collector(db, assigner, bbox, poi)
    keys = FEATURE_KEYS + (POI_KEYS if poi else ())
    c.apply_file(pbf, locations=True, idx=_pass_index(node_index, 2), filters=[osmium.filter.KeyFilter(*keys)])
    c.flush_ways()
    c.flush_pois()
    c.flush_addrs()
    c.flush_anodes()

    interps = []
    if c.interp_raw:
        mids = [g.interpolate(0.5, normalized=True) for *_, g in c.interp_raw]
        cities = assigner.assign([m.x for m in mids], [m.y for m in mids])
        for (mode, st, n0, n1, g), city in zip(c.interp_raw, cities):
            e0, e1 = (db.execute("SELECT hn, street FROM anode WHERE id=?", (n,)).fetchone() for n in (n0, n1))
            if not (e0 and e1 and e0[0].isdigit() and e1[0].isdigit()):
                continue
            street = st or e0[1] or e1[1]   # real data: street usually only on endpoint nodes
            step = {"all": 1, "even": 2, "odd": 2}.get(mode)
            if street and step:
                interps.append((c.gid(street, city), step, int(e0[0]), int(e1[0]), g))
    db.execute("DROP TABLE anode")
    db.execute("CREATE INDEX way_root ON way(root)")
    db.execute("CREATE INDEX addr_root ON addr(root)")
    db.execute("CREATE INDEX poi_root ON poi(root)")
    db.commit()
    db.close()
    log(f"  ways={c.n_ways} addresses={c.n_addrs} street groups={len(c.groups)} interpolations={len(interps)}"
        f" pois={c.n_pois}")
    return Extracted(admins, c.groups, c.group_point, interps, tuple(bbox),
                     dict(ways=c.n_ways, addrs=c.n_addrs, interps=len(interps), pois=c.n_pois))
