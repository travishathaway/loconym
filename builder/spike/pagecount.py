"""Count distinct 4 KiB pages read per query (cold connection each time) for both spike variants.

Run: pixi run python builder/spike/pagecount.py /tmp/out
"""
import math
import sys
from pathlib import Path

import apsw

sys.path.insert(0, str(Path(__file__).parent))
from spike import E7, CELL_Z, norm_tokens, quadkey  # noqa: E402

PAGE = 4096
reads: set[int] = set()
nreads = 0


class LogFile(apsw.VFSFile):
    def __init__(self, inherit, name, flags):
        super().__init__(inherit, name, flags)

    def xRead(self, amount, offset):
        global nreads
        nreads += 1
        for p in range(offset // PAGE, (offset + amount - 1) // PAGE + 1):
            reads.add(p)
        return super().xRead(amount, offset)


class LogVFS(apsw.VFS):
    def __init__(self):
        super().__init__("logvfs", "")

    def xOpen(self, name, flags):
        return LogFile("", name, flags)


_vfs = LogVFS()  # keep a reference or apsw unregisters it


def cold(path):
    reads.clear()
    global nreads
    nreads = 0
    db = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY, vfs="logvfs")
    db.pragma("cache_size", 0)
    return db


def report(label, db):
    print(f"  {label:34s} pages={len(reads):3d} ({len(reads)*PAGE/1024:5.1f} KiB)  reads={nreads}")
    db.close()


def dec_varints(b):
    out, n, s = [], 0, 0
    for x in b:
        n |= (x & 0x7F) << s
        if x & 0x80:
            s += 7
        else:
            out.append(n); n = s = 0
    return out


def parents(db, pid):
    chain = []
    while pid:
        row = db.execute("SELECT name,parent FROM place WHERE id=?", (pid,)).fetchone()
        chain.append(row[0]); pid = row[1]
    return chain


def reverse_a(path, lat, lon):
    db = cold(path)
    d = 0.0005  # ~50 m
    ids = [r[0] for r in db.execute(
        "SELECT id FROM rt WHERE minlat<=? AND maxlat>=? AND minlon<=? AND maxlon>=?",
        (lat + d, lat - d, lon + d, lon - d))]
    for i in ids:
        db.execute("SELECT poly FROM geom WHERE id=?", (i,)).fetchone()
    if ids:  # only the winner's address chain is resolved
        r = db.execute("SELECT name,parent FROM place WHERE id=?", (ids[0],)).fetchone()
        parents(db, r[1])
    report(f"reverse ({len(ids)} candidates)", db)


def reverse_b(path, lat, lon):
    db = cold(path)
    ids = set()
    base = quadkey(lat, lon, CELL_Z)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            row = db.execute("SELECT data FROM cell WHERE id=?", (base + (dy << CELL_Z) + dx,)).fetchone()
            if row:
                b, i = row[0], 0
                while i < len(b):
                    n = s = 0
                    while True:
                        x = b[i]; i += 1; n |= (x & 0x7F) << s; s += 7
                        if not x & 0x80: break
                    ids.add(n)
                    ln = s2 = m = 0
                    while True:
                        x = b[i]; i += 1; ln |= (x & 0x7F) << s2; s2 += 7
                        if not x & 0x80: break
                    i += ln
    if ids:  # geometry is inlined in the cell; only the winner's chain is resolved
        r = db.execute("SELECT name,parent FROM place WHERE id=?", (min(ids),)).fetchone()
        parents(db, r[1])
    report(f"reverse 3x3 cells ({len(ids)} cands)", db)


def search(path, street_tok, city_tok=None, number=None):
    db = cold(path)
    def prefix(tok):
        hi = tok[:-1] + chr(ord(tok[-1]) + 1)
        out = set()
        for _, blob in db.execute("SELECT t,postings FROM term WHERE t>=? AND t<?", (tok, hi)):
            acc = 0
            for dlt in dec_varints(blob):
                acc += dlt; out.add(acc)
        return out
    cands = prefix(street_tok)
    if city_tok:
        cands &= {i for i in cands}  # admin-resolve step placeholder (single-city Monaco)
    top = sorted(cands)[:5]
    for i in top:
        db.execute("SELECT name,lat,lon,parent FROM place WHERE id=?", (i,)).fetchone()
        if number:
            db.execute("SELECT data FROM housenumber WHERE street_id=?", (i,)).fetchone()
    report(f"search '{street_tok}'{' +hn' if number else ''} ({len(cands)} hits)", db)


def main(outdir):
    a, b = Path(outdir) / "a_rtree.sqlite", Path(outdir) / "b_cells.sqlite"
    lat, lon = 43.7384, 7.4246  # Monaco centre
    print(f"A: R*Tree ({a.stat().st_size//1024} KiB)")
    reverse_a(a, lat, lon)
    print(f"B: cells  ({b.stat().st_size//1024} KiB)")
    reverse_b(b, lat, lon)
    for name, p in (("A", a), ("B", b)):
        print(f"{name}: search")
        search(p, "boulevard"); search(p, "grimaldi"); search(p, "grim", number="1")


if __name__ == "__main__":
    main(sys.argv[1])
