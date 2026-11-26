"""Reference reader: implements the query algorithms of docs/format-spec.md in Python.

Used for tests and conformance; the TypeScript client mirrors it. Takes any DB-API-ish connection
(sqlite3 or apsw) so tests can also count page reads.
"""
import math
import re
import sqlite3

from .codec import Cell, cell_key, decode_housenumbers, decode_leaf, decode_postings, is_split, lonlat_tile, tile_bounds
from .normalize import normalize_tokens

ADDR_RADIUS_M = 40.0
POI_RADIUS_M = 50.0
POI_PARENT = -2   # term.parent for POI postings is POI_PARENT - city
MAX_ROWS_PER_TOKEN = 200
MIN_PREFIX = 3
ADMIN_KEYS = {2: "country", 3: "region", 4: "state", 5: "state_district", 6: "county", 7: "municipality",
              8: "city", 9: "city_district", 10: "suburb", 11: "neighbourhood"}
_HN_TOKEN = re.compile(r"[0-9]+[a-zA-Z]?")
_INT = re.compile(r"[0-9]+")


class CapabilityError(Exception):
    pass


def _m_per_deg(lat):
    return 111320 * math.cos(math.radians(lat)), 110540


def _pip(polygon, x, y):
    inside = False
    for ring in polygon:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def _seg_dist(px, py, a, b, lat):
    cx, cy = _m_per_deg(lat)
    ax, ay, bx, by = a[0] * cx, a[1] * cy, b[0] * cx, b[1] * cy
    px, py = px * cx, py * cy
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), qx / cx, qy / cy


class Loconym:
    def __init__(self, db):
        self.db = db
        self.meta = dict(db.execute("SELECT k, v FROM meta"))
        self.cell_zoom = int(self.meta["cell_zoom"])
        self.root_zoom = int(self.meta["root_zoom"])
        self.caps = set(self.meta["capabilities"].split(","))
        if int(self.meta["format_version"].split(".")[0]) != 0:
            raise ValueError("unsupported format version")

    @classmethod
    def open(cls, path):
        return cls(sqlite3.connect(f"file:{path}?mode=ro", uri=True))

    # -------------------------------------------------------------- cells
    def _row(self, x, y, z):
        r = self.db.execute("SELECT data FROM cell WHERE id=?", (cell_key(x, y, z),)).fetchone()
        return bytes(r[0]) if r else None

    def find_cell(self, lon, lat):
        """-> (Cell, box) or (None, None)."""
        x, y = lonlat_tile(lon, lat, self.cell_zoom)
        blob = self._row(x, y, self.cell_zoom)
        z = self.cell_zoom
        if blob is None:
            for z in range(self.cell_zoom - 1, self.root_zoom - 1, -1):
                x, y = lonlat_tile(lon, lat, z)
                blob = self._row(x, y, z)
                if blob is not None:
                    break
            else:
                return None, None
        while is_split(blob):
            z += 1
            x, y = lonlat_tile(lon, lat, z)
            blob = self._row(x, y, z)
            if blob is None:
                return None, None
        box = tile_bounds(x, y, z)
        return decode_leaf(blob, box), box

    # -------------------------------------------------------------- reverse
    def reverse(self, lon, lat, zoom=18, *, pois=False):
        """pois=True also reports a named POI within POI_RADIUS_M (below an exact address, above a street)."""
        pois = pois and "poi" in self.caps and zoom >= 17
        cell, box = self.find_cell(lon, lat)
        if cell is None:
            return None
        chain = [aid for aid, polys in cell.admin if polys is None or any(_pip(p, lon, lat) for p in polys)]
        best = [None, 1e18, None]  # (kind, sid, hn), distance (m), (lon, lat) of the matched feature

        def scan(c: Cell):
            if zoom >= 18:
                for sid, hn, x, y in c.addrs:
                    cx, cy = _m_per_deg(lat)
                    d = math.hypot((x - lon) * cx, (y - lat) * cy)
                    if d < ADDR_RADIUS_M and (best[0] is None or best[0][0] != "addr" or d < best[1]):
                        best[0], best[1], best[2] = ("addr", sid, hn), d, (x, y)
            if pois and (best[0] is None or best[0][0] != "addr"):
                for pid, x, y in c.pois:
                    cx, cy = _m_per_deg(lat)
                    d = math.hypot((x - lon) * cx, (y - lat) * cy)
                    if d < POI_RADIUS_M and (best[0] is None or best[0][0] != "poi" or d < best[1]):
                        best[0], best[1], best[2] = ("poi", pid, None), d, (x, y)
            if zoom >= 16 and (best[0] is None or best[0][0] not in ("addr", "poi")):
                for sid, pts in c.streets:
                    for a, b in zip(pts, pts[1:]):
                        d, qx, qy = _seg_dist(lon, lat, a, b, lat)
                        if d < best[1]:
                            best[0], best[1], best[2] = ("street", sid, None), d, (qx, qy)

        scan(cell)
        if best[0] is None or best[0][0] != "addr":
            r = best[1] if best[0] else 500.0
            cx, cy = _m_per_deg(lat)
            edges = [((lon - box[0]) * cx, (-1, 0)), ((box[2] - lon) * cx, (1, 0)),
                     ((lat - box[1]) * cy, (0, -1)), ((box[3] - lat) * cy, (0, 1))]
            for e, (ox, oy) in edges:
                if e < r:
                    n, _ = self.find_cell(lon + ox * (e + 0.5) / cx, lat + oy * (e + 0.5) / cy)
                    if n:
                        scan(n)
        out = dict(kind=best[0][0] if best[0] else None, street=None, housenumber=None, street_id=None, poi=None,
                   admin=[],
                   lon=best[2][0] if best[2] else lon, lat=best[2][1] if best[2] else lat,
                   distance_m=round(best[1], 1) if best[0] else None)
        if best[0] and best[0][0] == "poi":
            row = self.db.execute("SELECT name, class FROM poi WHERE id=?", (best[0][1],)).fetchone()
            out["poi"] = dict(id=best[0][1], name=row[0], **{"class": row[1]}) if row else None
        elif best[0]:
            kind, sid, hn = best[0]
            row = self.db.execute("SELECT name FROM street WHERE id=?", (sid,)).fetchone()
            out.update(street=row[0] if row else None, street_id=sid, housenumber=hn)
        rows = [self.db.execute("SELECT id,level,name,rank FROM admin WHERE id=?", (a,)).fetchone() for a in chain]
        out["admin"] = [dict(id=i, level=l, name=n, rank=r) for i, l, n, r in sorted(rows, key=lambda r: -r[1])]
        out["place_rank"] = 30 if out["kind"] in ("addr", "poi") else 26 if out["kind"] == "street" else (
            out["admin"][0]["rank"] if out["admin"] else None)
        addr = {}
        if out["poi"]:
            addr[out["poi"]["class"].split("=", 1)[1]] = out["poi"]["name"]
        if out["housenumber"]:
            addr["house_number"] = out["housenumber"]
        if out["street"]:
            addr["road"] = out["street"]
        for a in reversed(out["admin"]):  # shallowest first, so a deeper area wins a shared key
            key = ADMIN_KEYS.get(a["level"])
            if key:
                addr[key] = a["name"]
        out["address"] = addr
        parts = []
        if out["poi"]:
            parts.append(out["poi"]["name"])
        if out["street"]:
            parts.append(f"{out['street']} {out['housenumber']}" if out["housenumber"] else out["street"])
        for a in out["admin"]:
            if a["name"] not in parts:
                parts.append(a["name"])
        out["display_name"] = ", ".join(parts)
        return out

    # -------------------------------------------------------------- search
    def _postings(self, token, parent, prefix):
        ids = set()
        if prefix:
            hi = token[:-1] + chr(ord(token[-1]) + 1)
            rows = self.db.execute("SELECT postings FROM term WHERE t>=? AND t<? AND parent=? LIMIT ?",
                                   (token, hi, parent, MAX_ROWS_PER_TOKEN))
        else:
            rows = self.db.execute("SELECT postings FROM term WHERE t=? AND parent=?", (token, parent))
        for (b,) in rows:
            ids.update(decode_postings(bytes(b)))
        return ids

    def _cities(self, text):
        toks = normalize_tokens(text)
        sets = [self._postings(t, -1, prefix=(i == len(toks) - 1)) for i, t in enumerate(toks)]
        ids = set.intersection(*sets) if sets else set()
        cities = set()
        for i in ids:
            city = self.db.execute("SELECT city FROM admin WHERE id=?", (i,)).fetchone()[0]
            if city:
                cities.add(city)
        return cities

    def search(self, q=None, *, street=None, city=None, limit=5, min_prefix=MIN_PREFIX):
        if "search" not in self.caps:
            raise CapabilityError("database built without search")
        number = None
        if q is not None:
            parts = [p.strip() for p in q.split(",")]
            city = parts[-1] if len(parts) > 1 else None
            street = parts[0]
        toks = street.split() if street else []
        if toks and _HN_TOKEN.fullmatch(toks[-1]):
            number = toks.pop()
        elif toks and _HN_TOKEN.fullmatch(toks[0]):
            number = toks.pop(0)
        stoks = normalize_tokens(" ".join(toks))
        if not stoks:
            return []
        cities = self._cities(city) if city else None
        if cities is not None and not cities:
            return []
        cand = None
        for i, t in enumerate(stoks):
            last = i == len(stoks) - 1
            if last and len(t) < min_prefix:
                prefix = False
            else:
                prefix = last
            ids = set()
            if cities is None:
                ids = self._postings_any_city(t, prefix)
            else:
                for c in sorted(cities):
                    ids |= self._postings(t, c, prefix)
            cand = ids if cand is None else cand & ids
        results = []
        poi_cand = set()
        if number is None and "poi" in self.caps:
            for i, t in enumerate(stoks):
                last = i == len(stoks) - 1
                prefix = last and len(t) >= min_prefix
                ids = set()
                if cities is None:
                    ids = self._postings_any_poi_city(t, prefix)
                else:
                    for c in sorted(cities):
                        ids |= self._postings(t, POI_PARENT - c, prefix)
                poi_cand = ids if i == 0 else poi_cand & ids
        for pid in sorted(poi_cand)[:50]:
            name, cls, rank, parent, lat, lon = self.db.execute(
                "SELECT name,class,rank,parent,lat,lon FROM poi WHERE id=?", (pid,)).fetchone()
            ntoks = normalize_tokens(name)
            score = 10 * sum(t in ntoks for t in stoks) - abs(len(ntoks) - len(stoks))
            results.append(dict(kind="poi", poi_id=pid, name=name, **{"class": cls}, rank=rank, city_id=parent,
                                lat=lat / 1e6, lon=lon / 1e6, score=score))
        for sid in sorted(cand or [])[:50]:
            name, parent, lat, lon = self.db.execute(
                "SELECT name,parent,lat,lon FROM street WHERE id=?", (sid,)).fetchone()
            ntoks = normalize_tokens(name)
            score = 10 * sum(t in ntoks for t in stoks) - abs(len(ntoks) - len(stoks))
            hit = dict(kind="street", street_id=sid, name=name, city_id=parent, lat=lat / 1e6, lon=lon / 1e6,
                       score=score)
            results.append(hit)
        # equal scores: more prominent POI (lower rank) first, then streets, then id
        results.sort(key=lambda h: (-h["score"], h.get("rank", 30), h["kind"] == "street",
                                    h.get("poi_id", h.get("street_id"))))
        results = results[:limit]
        for h in results:
            h["housenumber"] = None
            if number and h["kind"] == "street":
                self._locate(h, number)
            h["city"] = self._admin_name(h["city_id"])
            h["display_name"] = ", ".join(p for p in (
                f"{h['name']} {h['housenumber']}" if h["housenumber"] else h["name"], h["city"]) if p)
        return results

    def _postings_any_poi_city(self, token, prefix):
        ids = set()
        if prefix:
            hi = token[:-1] + chr(ord(token[-1]) + 1)
            rows = self.db.execute("SELECT postings FROM term WHERE t>=? AND t<? AND parent<=? LIMIT ?",
                                   (token, hi, POI_PARENT, MAX_ROWS_PER_TOKEN))
        else:
            rows = self.db.execute("SELECT postings FROM term WHERE t=? AND parent<=? LIMIT ?",
                                   (token, POI_PARENT, MAX_ROWS_PER_TOKEN))
        for (b,) in rows:
            ids.update(decode_postings(bytes(b)))
        return ids

    def _postings_any_city(self, token, prefix):
        ids = set()
        if prefix:
            hi = token[:-1] + chr(ord(token[-1]) + 1)
            rows = self.db.execute("SELECT postings FROM term WHERE t>=? AND t<? AND parent>=0 LIMIT ?",
                                   (token, hi, MAX_ROWS_PER_TOKEN))
        else:
            rows = self.db.execute("SELECT postings FROM term WHERE t=? AND parent>=0 LIMIT ?",
                                   (token, MAX_ROWS_PER_TOKEN))
        for (b,) in rows:
            ids.update(decode_postings(bytes(b)))
        return ids

    def _admin_name(self, aid):
        if not aid:
            return None
        r = self.db.execute("SELECT name FROM admin WHERE id=?", (aid,)).fetchone()
        return r[0] if r else None

    def _locate(self, hit, number):
        row = self.db.execute("SELECT data FROM housenumber WHERE street_id=?", (hit["street_id"],)).fetchone()
        if not row:
            return
        sn = decode_housenumbers(bytes(row[0]))
        exact = {hn.lower(): (lon, lat) for hn, lon, lat in reversed(sn.addrs)}
        if number.lower() in exact:
            hit["lon"], hit["lat"] = exact[number.lower()]
            hit["housenumber"] = number
            return
        if not _INT.fullmatch(number):
            return
        n = int(number)
        for step, first, last, pts in sn.interps:
            lo, hi = min(first, last), max(first, last)
            if first != last and lo <= n <= hi and (step == 1 or (n - first) % 2 == 0):
                f = (n - first) / (last - first)
                segs = [math.hypot((b[0] - a[0]) * _m_per_deg(a[1])[0], (b[1] - a[1]) * _m_per_deg(a[1])[1])
                        for a, b in zip(pts, pts[1:])]
                target, acc = f * sum(segs), 0.0
                for (a, b), L in zip(zip(pts, pts[1:]), segs):
                    if acc + L >= target and L > 0:
                        t = (target - acc) / L
                        hit["lon"], hit["lat"] = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                        hit["housenumber"], hit["interpolated"] = number, True
                        return
                    acc += L
