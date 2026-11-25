"""Binary codecs for cell and housenumber blobs. Spec: docs/format-spec.md sections 3-4."""
import math
from dataclasses import dataclass, field

COORD_QUANTUM = 1e-6      # cell coordinates (meta.coord_quantum)
HN_QUANTUM = 1e-7         # housenumber blob address coordinates
GEOM_QUANTUM = 1e-6       # polylines in housenumber blobs

LEAF = 0
SPLIT = 1


# ------------------------------------------------------------------ varints
def put_varint(out: bytearray, n: int) -> None:
    if n < 0:
        raise ValueError("negative varint")
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def unzigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


class Reader:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def v(self) -> int:
        n = s = 0
        while True:
            x = self.b[self.i]
            self.i += 1
            n |= (x & 0x7F) << s
            s += 7
            if not x & 0x80:
                return n

    def sv(self) -> int:
        return unzigzag(self.v())

    def raw(self, n: int) -> bytes:
        r = self.b[self.i:self.i + n]
        self.i += n
        return r

    def more(self) -> bool:
        return self.i < len(self.b)


# ------------------------------------------------------------------ tiles
def tile_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) of a web-mercator tile."""
    n = 1 << z

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def lonlat_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def cell_key(x: int, y: int, z: int) -> int:
    k = 0
    for i in range(z):
        k |= ((x >> i) & 1) << (2 * i) | ((y >> i) & 1) << (2 * i + 1)
    return (1 << (2 * z)) | k


# ------------------------------------------------------------------ coordinate lists
def _enc_coords(out: bytearray, coords, ox: float, oy: float, q: float) -> None:
    put_varint(out, len(coords))
    px = py = 0
    for x, y in coords:
        ix, iy = round((x - ox) / q), round((y - oy) / q)
        put_varint(out, zigzag(ix - px))
        put_varint(out, zigzag(iy - py))
        px, py = ix, iy


def _dec_coords(r: Reader, ox: float, oy: float, q: float):
    n = r.v()
    pts, px, py = [], 0, 0
    for _ in range(n):
        px += r.sv()
        py += r.sv()
        pts.append((ox + px * q, oy + py * q))
    return pts


# ------------------------------------------------------------------ cells
@dataclass
class Cell:
    """Decoded leaf. admin: [(admin_id, None | [polygon]) ], polygon = [ring], ring = [(lon, lat)]
    streets: [(street_id, [(lon, lat)])]; addrs: [(street_id, housenumber, lon, lat)];
    interps: [(street_id, step, first, last, [(lon, lat)])]"""
    admin: list = field(default_factory=list)
    streets: list = field(default_factory=list)
    addrs: list = field(default_factory=list)
    interps: list = field(default_factory=list)


def encode_split() -> bytes:
    return bytes([SPLIT])


def is_split(blob: bytes) -> bool:
    return blob[0] == SPLIT


def encode_leaf(box, cell: Cell) -> bytes:
    """cell.admin polygons / streets / interps carry lists of coordinate lists (already clipped)."""
    ox, oy, q = box[0], box[1], COORD_QUANTUM
    out = bytearray([LEAF])
    put_varint(out, len(cell.admin))
    for aid, polys in cell.admin:
        put_varint(out, aid)
        if polys is None:
            put_varint(out, 0)
        else:
            put_varint(out, len(polys) + 1)
            for rings in polys:
                put_varint(out, len(rings))
                for ring in rings:
                    _enc_coords(out, ring, ox, oy, q)
    put_varint(out, len(cell.streets))
    for sid, pts in cell.streets:
        put_varint(out, sid)
        _enc_coords(out, pts, ox, oy, q)
    # addresses grouped by street id (runs), sorted by (street id, housenumber)
    addrs = sorted(cell.addrs, key=lambda a: (a[0], a[1]))
    groups = []
    for a in addrs:
        if groups and groups[-1][0] == a[0]:
            groups[-1][1].append(a)
        else:
            groups.append((a[0], [a]))
    put_varint(out, len(groups))
    prev_sid = px = py = 0
    for sid, items in groups:
        put_varint(out, sid - prev_sid)
        prev_sid = sid
        put_varint(out, len(items))
        for _, hn, lon, lat in items:
            b = hn.encode()
            put_varint(out, len(b))
            out += b
            ix, iy = round((lon - ox) / q), round((lat - oy) / q)
            put_varint(out, zigzag(ix - px))
            put_varint(out, zigzag(iy - py))
            px, py = ix, iy
    put_varint(out, len(cell.interps))
    for sid, step, first, last, pts in cell.interps:
        put_varint(out, sid)
        put_varint(out, step)
        put_varint(out, first)
        put_varint(out, last)
        _enc_coords(out, pts, ox, oy, q)
    return bytes(out)


def decode_leaf(blob: bytes, box) -> Cell:
    ox, oy, q = box[0], box[1], COORD_QUANTUM
    r = Reader(blob)
    if r.v() != LEAF:
        raise ValueError("not a leaf")
    c = Cell()
    for _ in range(r.v()):
        aid, flag = r.v(), r.v()
        if flag == 0:
            c.admin.append((aid, None))
        else:
            polys = []
            for _ in range(flag - 1):
                polys.append([_dec_coords(r, ox, oy, q) for _ in range(r.v())])
            c.admin.append((aid, polys))
    for _ in range(r.v()):
        sid = r.v()
        c.streets.append((sid, _dec_coords(r, ox, oy, q)))
    sid = px = py = 0
    for _ in range(r.v()):
        sid += r.v()
        for _ in range(r.v()):
            hn = r.raw(r.v()).decode()
            px += r.sv()
            py += r.sv()
            c.addrs.append((sid, hn, ox + px * q, oy + py * q))
    for _ in range(r.v()):
        sid, step, first, last = r.v(), r.v(), r.v(), r.v()
        c.interps.append((sid, step, first, last, _dec_coords(r, ox, oy, q)))
    return c


# ------------------------------------------------------------------ housenumber blobs
@dataclass
class StreetNumbers:
    """addrs: [(housenumber, lon, lat)] in natural order; interps: [(step, first, last, [(lon, lat)])]"""
    addrs: list = field(default_factory=list)
    interps: list = field(default_factory=list)


def encode_housenumbers(sn: StreetNumbers) -> bytes:
    out = bytearray()
    put_varint(out, len(sn.addrs))
    plat = plon = 0
    for hn, lon, lat in sn.addrs:
        b = hn.encode()
        put_varint(out, len(b))
        out += b
        la, lo = round(lat / HN_QUANTUM), round(lon / HN_QUANTUM)
        put_varint(out, zigzag(la - plat))
        put_varint(out, zigzag(lo - plon))
        plat, plon = la, lo
    put_varint(out, len(sn.interps))
    for step, first, last, pts in sn.interps:
        put_varint(out, step)
        put_varint(out, first)
        put_varint(out, last)
        _enc_coords(out, pts, 0.0, 0.0, GEOM_QUANTUM)
    return bytes(out)


def decode_housenumbers(blob: bytes) -> StreetNumbers:
    r = Reader(blob)
    sn = StreetNumbers()
    plat = plon = 0
    for _ in range(r.v()):
        hn = r.raw(r.v()).decode()
        plat += r.sv()
        plon += r.sv()
        sn.addrs.append((hn, plon * HN_QUANTUM, plat * HN_QUANTUM))
    for _ in range(r.v()):
        step, first, last = r.v(), r.v(), r.v()
        sn.interps.append((step, first, last, _dec_coords(r, 0.0, 0.0, GEOM_QUANTUM)))
    return sn


# ------------------------------------------------------------------ postings
def encode_postings(ids) -> bytes:
    out, prev = bytearray(), 0
    for i in sorted(set(ids)):
        put_varint(out, i - prev)
        prev = i
    return bytes(out)


def decode_postings(blob: bytes) -> list[int]:
    r, acc, out = Reader(blob), 0, []
    while r.more():
        acc += r.v()
        out.append(acc)
    return out
