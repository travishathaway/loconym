"""Stages 2-4: tile the scratch data into cells, build tables, write the final SQLite file (format-spec.md)."""
import datetime
import re
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

import shapely
import shapely.wkb as wkb

from .codec import (
    COORD_QUANTUM,
    Cell,
    StreetNumbers,
    cell_key,
    encode_housenumbers,
    encode_id_list,
    encode_leaf,
    encode_postings,
    encode_split,
    lonlat_tile,
    tile_bounds,
)
from .extract import ROOT_ZOOM, extract, root_key, root_xy
from .normalize import NORMALIZER_VERSION, normalize_key, normalize_tokens
from .poi import CATEGORY_LIMIT, connectors, phrase_rows
from .prefilter import available as osmium_available
from .prefilter import prefilter
from .snap import snap_pois

FORMAT_VERSION = "0.3"
CELL_ZOOM = 16
MAX_SPLIT_ZOOM = 19
PAGE_SIZE = 4096
POI_PARENT = -2   # term.parent for POI postings is POI_PARENT - city (admin = -1, streets = city >= 0)
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"

SCHEMA = """
CREATE TABLE meta(k TEXT PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE admin(id INTEGER PRIMARY KEY, level INT, name TEXT, parent INT, city INT, rank INT);
CREATE TABLE street(id INTEGER PRIMARY KEY, name TEXT, parent INT, lat INT, lon INT);
CREATE TABLE poi(id INTEGER PRIMARY KEY, name TEXT, class TEXT, rank INT, parent INT, lat INT, lon INT,
                 street TEXT, housenumber TEXT);
CREATE TABLE phrase(token TEXT, class TEXT, PRIMARY KEY(token, class)) WITHOUT ROWID;
CREATE TABLE poi_class(class TEXT, parent INT, postings BLOB, PRIMARY KEY(class, parent)) WITHOUT ROWID;
CREATE TABLE cell(id INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE term(t TEXT, parent INT, postings BLOB, PRIMARY KEY(t, parent)) WITHOUT ROWID;
CREATE TABLE housenumber(street_id INTEGER PRIMARY KEY, data BLOB);
"""

# admin_level -> Nominatim-style place_rank (germany/europe defaults; documented in meta)
LEVEL_RANK = {2: 4, 3: 6, 4: 8, 5: 10, 6: 12, 7: 14, 8: 16, 9: 18, 10: 20, 11: 22}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ------------------------------------------------------------------ geometry helpers
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


def clip(g, box):
    return shapely.clip_by_rect(g, *box)


# ------------------------------------------------------------------ tiling
class CellWriter:
    def __init__(self, out_db, max_leaf_bytes):
        self.db, self.max_leaf = out_db, max_leaf_bytes
        self.rows, self.n_leaf, self.n_split, self.bytes = [], 0, 0, 0

    def put(self, key, blob, split=False):
        self.rows.append((key, blob))
        self.n_split += split
        self.n_leaf += not split
        self.bytes += len(blob)

    def flush(self):
        self.db.executemany("INSERT INTO cell VALUES (?,?)", self.rows)
        self.rows = []


def _to_cell(adm, streets, addrs, interps, pois=()) -> Cell:
    c = Cell()
    for aid, g in adm:
        if g is None:
            c.admin.append((aid, None))
        else:
            polys = [[list(p.exterior.coords)] + [list(r.coords) for r in p.interiors] for p in polys_of(g)]
            c.admin.append((aid, polys))
    c.streets = [(sid, list(l.coords)) for sid, g in streets for l in lines_of(g)]
    c.addrs = list(addrs)
    c.pois = list(pois)
    c.interps = [(sid, step, first, last, list(l.coords)) for sid, step, first, last, g in interps for l in lines_of(g)]
    return c


def _children(x, y, z, adm, streets, addrs, interps, pois):
    for i in (0, 1):
        for j in (0, 1):
            cx, cy = 2 * x + i, 2 * y + j
            cb = tile_bounds(cx, cy, z + 1)
            cbox = shapely.box(*cb)
            cadm = []
            for aid, g in adm:
                if g is None:
                    cadm.append((aid, None))
                    continue
                piece = clip(g, cb)
                if piece.is_empty or piece.area == 0:
                    continue
                full = piece.area >= cbox.area * (1 - 1e-9) or piece.contains(cbox)
                cadm.append((aid, None if full else piece))
            cst = [(sid, p) for sid, g in streets if lines_of(p := clip(g, cb))]
            cin = [(*t[:4], p) for t in interps if lines_of(p := clip(t[4], cb))]
            cad = [a for a in addrs if cb[0] <= a[2] < cb[2] and cb[1] <= a[3] < cb[3]]
            cpo = [p for p in pois if cb[0] <= p[1] < cb[2] and cb[1] <= p[2] < cb[3]]
            yield cx, cy, cadm, cst, cad, cin, cpo


def _rec(w: CellWriter, x, y, z, adm, streets, addrs, interps, pois=()):
    if not (adm or streets or addrs or interps or pois):
        return
    key = cell_key(x, y, z)
    if not (streets or addrs or interps or pois):          # featureless: one coarse admin-only leaf
        w.put(key, encode_leaf(tile_bounds(x, y, z), _to_cell(adm, [], [], [])))
        return
    if z < CELL_ZOOM:                               # features exist: refine down to the base zoom
        for cx, cy, *rest in _children(x, y, z, adm, streets, addrs, interps, pois):
            _rec(w, cx, cy, z + 1, *rest)
        return
    blob = encode_leaf(tile_bounds(x, y, z), _to_cell(adm, streets, addrs, interps, pois))
    if len(blob) > w.max_leaf and z < MAX_SPLIT_ZOOM:  # oversized hot cell: marker + children
        w.put(key, encode_split(), split=True)
        for cx, cy, *rest in _children(x, y, z, adm, streets, addrs, interps, pois):
            _rec(w, cx, cy, z + 1, *rest)
    else:
        w.put(key, blob)


def _admin_roots(admins):
    roots = set()
    for a in admins:
        x0, y0, x1, y1 = a.geom.bounds
        ax, ay = lonlat_tile(x0, y1, ROOT_ZOOM)
        bx, by = lonlat_tile(x1, y0, ROOT_ZOOM)
        for rx in range(ax, bx + 1):
            for ry in range(ay, by + 1):
                if a.geom.intersects(shapely.box(*tile_bounds(rx, ry, ROOT_ZOOM))):
                    roots.add(root_key(rx, ry))
    return roots


def build_cells(ex, scratch: sqlite3.Connection, out_db, final_id, max_leaf_bytes, log, poi_id=None):
    poi_id = poi_id or {}
    admins = ex.admins
    atree = shapely.STRtree([a.geom for a in admins]) if admins else None
    interp_by_root = defaultdict(list)
    for t in ex.interps:
        x0, y0, x1, y1 = t[4].bounds
        ax, ay = lonlat_tile(x0, y1, ROOT_ZOOM)
        bx, by = lonlat_tile(x1, y0, ROOT_ZOOM)
        for rx in range(ax, bx + 1):
            for ry in range(ay, by + 1):
                if t[4].intersects(shapely.box(*tile_bounds(rx, ry, ROOT_ZOOM))):
                    interp_by_root[root_key(rx, ry)].append((final_id[t[0]], t[1], t[2], t[3], t[4]))
    roots = {r for (r,) in scratch.execute("SELECT DISTINCT root FROM way")}
    roots |= {r for (r,) in scratch.execute("SELECT DISTINCT root FROM addr")}
    roots |= {r for (r,) in scratch.execute("SELECT DISTINCT root FROM poi")}
    roots |= set(interp_by_root) | _admin_roots(admins)
    w = CellWriter(out_db, max_leaf_bytes)
    for n, r in enumerate(sorted(roots), 1):
        rx, ry = root_xy(r)
        box = tile_bounds(rx, ry, ROOT_ZOOM)
        bx = shapely.box(*box)
        adm = []
        if atree is not None:
            for ai in atree.query(bx, predicate="intersects"):
                piece = clip(admins[ai].geom, box)
                if piece.is_empty or piece.area == 0:
                    continue
                adm.append((admins[ai].id, None if piece.area >= bx.area * (1 - 1e-9) else piece))
        way_rows = scratch.execute("SELECT gid, wkb FROM way WHERE root=?", (r,))
        streets = [(final_id[g], wkb.loads(b)) for g, b in way_rows]
        addr_rows = scratch.execute("SELECT gid,hn,lon,lat FROM addr WHERE root=?", (r,))
        addrs = [(final_id[g], hn, lon, lat) for g, hn, lon, lat in addr_rows]
        poi_rows = scratch.execute("SELECT rowid, lon, lat FROM poi WHERE root=?", (r,))
        pois = [(poi_id[rid], lon, lat) for rid, lon, lat in poi_rows]
        _rec(w, rx, ry, ROOT_ZOOM, adm, streets, addrs, interp_by_root.get(r, []), pois)
        if n % 20 == 0 or len(w.rows) > 20000:
            w.flush()
            log(f"  roots {n}/{len(roots)}  cells={w.n_leaf} split markers={w.n_split}")
    w.flush()
    return w


# ------------------------------------------------------------------ driver
BIG_INPUT_BYTES = 400 * 2**20   # above this, 'auto' prefilters and keeps the node-location index on disk


def build(pbf: str, output: str, *, language="en", city_level=8, search=True, max_leaf_bytes=16384,
          keep_scratch=False, log=print, prefilter_mode="auto", node_index="auto", poi=True) -> dict:
    """prefilter_mode: auto|always|never (osmium-tool pre-filtering, see prefilter.py);
    node_index: auto|memory|disk (where libosmium keeps node locations)."""
    out_path = Path(output)
    out_path.unlink(missing_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="loconym-", dir=str(out_path.parent))
    scratch_path = str(Path(tmpdir) / "scratch.sqlite")
    big = Path(pbf).stat().st_size > BIG_INPUT_BYTES
    use_prefilter = prefilter_mode == "always" or (prefilter_mode == "auto" and big and osmium_available())
    boundaries = None
    if use_prefilter:
        boundaries, pbf_in = prefilter(pbf, tmpdir, log, poi=poi)
    else:
        pbf_in = pbf
    on_disk = node_index == "disk" or (node_index == "auto" and big)
    idx = f"sparse_file_array,{Path(tmpdir) / 'nodes.idx'}" if on_disk else "flex_mem"
    ex = extract(pbf_in, scratch_path, city_level, log, boundaries_pbf=boundaries, node_index=idx, poi=poi)
    if not keep_scratch:   # large and no longer needed
        for f in ("nodes.idx.1", "nodes.idx.2", "boundaries.pbf", "features.pbf"):
            (Path(tmpdir) / f).unlink(missing_ok=True)

    # final street ids: dense, ordered by (city, normalized name)
    order = sorted(ex.groups, key=lambda g: (g[2], normalize_key(g[1])))
    final_id = {g[0]: i + 1 for i, g in enumerate(order)}

    # final POI ids: dense, ordered by (city, normalized name), like streets
    scratch = sqlite3.connect(scratch_path)
    prows = scratch.execute("SELECT rowid, name, cls, rank, city, lon, lat, street, hn, root FROM poi").fetchall()
    street_names = {g[0]: g[1] for g in ex.groups}
    todo = [(r[0], r[9], r[5], r[6]) for r in prows if not r[7]]   # no addr:street tag: snap to a nearby address
    snapped = snap_pois(scratch, street_names, todo) if todo else {}
    log(f"  POI addresses: {len(prows) - len(todo)} from tags, {len(snapped)} snapped, "
        f"{len(todo) - len(snapped)} without")
    prows = [(rid, name, cls, rank, city, lon, lat, *(snapped.get(rid, (None, None)) if not street else (street, hn)))
             for rid, name, cls, rank, city, lon, lat, street, hn, _root in prows]
    prows.sort(key=lambda r: (r[4], normalize_key(r[1]), r[0]))
    poi_id = {r[0]: i + 1 for i, r in enumerate(prows)}

    db = sqlite3.connect(out_path)
    db.executescript(f"PRAGMA page_size={PAGE_SIZE}; PRAGMA journal_mode=off; PRAGMA synchronous=off;" + SCHEMA)
    log("stage 2: cells")
    w = build_cells(ex, scratch, db, final_id, max_leaf_bytes, log, poi_id)

    log("stage 3: tables")
    db.executemany("INSERT INTO admin VALUES (?,?,?,?,?,?)",
                   [(a.id, a.level, a.name, a.parent, a.city, LEVEL_RANK.get(a.level, 30)) for a in ex.admins])
    srows = []
    for tmp, name, city in order:
        lon, lat = ex.group_point.get(tmp, (0.0, 0.0))
        srows.append((final_id[tmp], name, city, round(lat * 1e6), round(lon * 1e6)))
    db.executemany("INSERT INTO street VALUES (?,?,?,?,?)", srows)

    db.executemany("INSERT INTO poi VALUES (?,?,?,?,?,?,?,?,?)",
                   [(poi_id[rid], name, cls, rank, city, round(lat * 1e6), round(lon * 1e6), street, hn)
                    for rid, name, cls, rank, city, lon, lat, street, hn in prows])
    if poi:
        db.executemany("INSERT INTO phrase VALUES (?,?)", phrase_rows())
    by_class = defaultdict(list)
    for rid, _name, cls, rank, city, *_ in prows:
        by_class[(cls, city)].append((rank, poi_id[rid]))
    db.executemany("INSERT INTO poi_class VALUES (?,?,?)",
                   ((cls, city, encode_id_list(i for _r, i in sorted(v)[:CATEGORY_LIMIT]))   # rank order, not delta
                    for (cls, city), v in by_class.items()))

    post = defaultdict(set)
    for rid, name, _cls, _rank, city, _lon, _lat, street, _hn in prows:
        # name and street tokens share the POI namespace, so "Netto Dammweg" intersects to that one branch
        for t in set(normalize_tokens(name)) | set(normalize_tokens(street or "")):
            post[(t, POI_PARENT - city)].add(poi_id[rid])   # POI namespace: parent <= -2, never mixes with streets
    for a in ex.admins:
        for t in set(normalize_tokens(a.name)):
            post[(t, -1)].add(a.id)
    for sid, name, city, *_ in srows:
        for t in set(normalize_tokens(name)):
            post[(t, city)].add(sid)
    db.executemany("INSERT INTO term VALUES (?,?,?)", ((t, p, encode_postings(ids)) for (t, p), ids in post.items()))

    log("stage 4: housenumbers")
    scratch.execute("CREATE TEMP TABLE remap(tmp INTEGER PRIMARY KEY, fin INT)")
    scratch.executemany("INSERT INTO remap VALUES (?,?)", final_id.items())
    ints = defaultdict(list)
    for tmp, step, first, last, g in ex.interps:
        ints[final_id[tmp]].append((step, first, last, list(g.coords)))
    cur = scratch.execute("SELECT fin, hn, lon, lat FROM addr JOIN remap ON gid=tmp ORDER BY fin")
    cur_id, items, n_hn = None, [], 0

    def emit(sid, items):
        items.sort(key=lambda a: natural_key(a[0]))
        db.execute("INSERT INTO housenumber VALUES (?,?)",
                   (sid, encode_housenumbers(StreetNumbers(items, ints.pop(sid, [])))))

    for fin, hn, lon, lat in cur:
        if fin != cur_id and cur_id is not None:
            emit(cur_id, items)
            items = []
        cur_id = fin
        items.append((hn, lon, lat))
        n_hn += 1
    if cur_id is not None:
        emit(cur_id, items)
    for sid in list(ints):
        emit(sid, [])

    caps = ["reverse"] + (["search", "housenumber", "interpolation"] if search else [])
    if poi:
        caps.append("poi")
        if search:
            caps.append("category")
    meta = {
        "format_version": FORMAT_VERSION,
        "created_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "source": Path(pbf).name, "bbox": ",".join(f"{v:.6f}" for v in ex.bbox), "language": language,
        "capabilities": ",".join(caps), "cell_zoom": CELL_ZOOM, "root_zoom": ROOT_ZOOM, "coord_quantum": COORD_QUANTUM,
        "city_level": city_level, "attribution": ATTRIBUTION, "normalizer": NORMALIZER_VERSION,
        "max_leaf_bytes": max_leaf_bytes,
    }
    if poi:
        meta["connectors"] = "|".join(connectors())
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.execute("PRAGMA application_id=0x4c474154")
    db.execute("PRAGMA user_version=0")
    db.commit()
    scratch.close()
    if not keep_scratch:
        for f in Path(tmpdir).glob("*"):
            f.unlink()
        Path(tmpdir).rmdir()
    if not search:
        for t in ("term", "housenumber", "phrase", "poi_class"):  # reverse still needs street names
            db.execute(f"DELETE FROM {t}")
        db.commit()
    log("vacuum")
    db.execute("VACUUM")
    db.close()
    stats = dict(size=out_path.stat().st_size, cells=w.n_leaf, split_markers=w.n_split, streets=len(srows),
                 housenumbers=n_hn, admins=len(ex.admins), pois=len(prows))
    log(f"done: {stats}")
    return stats
