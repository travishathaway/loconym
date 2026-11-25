"""Benchmark a built database with the reference reader: correctness against its own data + pages read per query.

  logator-bench DB [--n 300] [--seed 7]
Page counting uses an apsw logging VFS (4 KiB pages, cold = fresh connection per query, warm = 256 KiB cache).
"""
import argparse
import random
import statistics

import apsw

from .codec import decode_housenumbers
from .reader import Gator

PAGE = 4096
_reads: set[int] = set()


class _LogFile(apsw.VFSFile):
    def xRead(self, amount, offset):
        _reads.update(range(offset // PAGE, (offset + amount - 1) // PAGE + 1))
        return super().xRead(amount, offset)


class _LogVFS(apsw.VFS):
    def __init__(self):
        super().__init__("lgbench", "")

    def xOpen(self, name, flags):
        return _LogFile("", name, flags)


_vfs = _LogVFS()


def _open(path, cache_pages=0):
    db = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY, vfs="lgbench")
    db.pragma("cache_size", cache_pages)
    return db


def _stats(xs):
    xs = sorted(xs)
    return f"avg={statistics.mean(xs):.1f} p95={xs[int(len(xs) * 0.95)]} max={xs[-1]}"


def sample_addresses(path, n, rng):
    db = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READONLY)
    names = dict(db.execute("SELECT id, name FROM street"))
    cities = dict(db.execute("SELECT id, name FROM admin"))
    parents = dict(db.execute("SELECT id, parent FROM street"))
    ids = [r[0] for r in db.execute("SELECT street_id FROM housenumber")]
    out = []
    for sid in rng.sample(ids, min(n, len(ids))):
        blob = db.execute("SELECT data FROM housenumber WHERE street_id=?", (sid,)).fetchone()[0]
        sn = decode_housenumbers(bytes(blob))
        if sn.addrs:
            hn, lon, lat = rng.choice(sn.addrs)
            out.append((sid, names[sid], cities.get(parents[sid], ""), hn, lon, lat))
    db.close()
    return out


def run(path, n=300, seed=7, out=print):
    rng = random.Random(seed)
    samples = sample_addresses(path, n, rng)
    # reverse
    cold, ok_s, ok_n = [], 0, 0
    for sid, _name, _city, hn, lon, lat in samples:
        _reads.clear()
        g = Gator(_open(path))
        r = g.reverse(lon, lat)
        cold.append(len(_reads))
        ok_s += bool(r and r["street_id"] == sid)
        ok_n += bool(r and r["housenumber"] == hn)
    warm_db = Gator(_open(path, 64))
    for _, _, _, _, lon, lat in samples[:50]:
        warm_db.reverse(lon, lat)
    warm = []
    for _, _, _, _, lon, lat in samples:
        _reads.clear()
        warm_db.reverse(lon, lat)
        warm.append(len(_reads))
    out(f"reverse@address n={len(samples)}: street-ok={ok_s / len(samples):.1%} number-ok={ok_n / len(samples):.1%} "
        f"pages cold {_stats(cold)} | warm {_stats(warm)}")
    # search
    cold, top1, top5, located = [], 0, 0, 0
    for sid, name, city, hn, _lon, _lat in samples:
        q = f"{name} {hn}, {city}" if city else f"{name} {hn}"
        _reads.clear()
        g = Gator(_open(path))
        res = g.search(q)
        cold.append(len(_reads))
        ids = [h["street_id"] for h in res]
        top1 += bool(ids and ids[0] == sid)
        top5 += sid in ids
        located += any(h["street_id"] == sid and h["housenumber"] == hn for h in res)
    out(f"search 'street N, city' n={len(samples)}: top1={top1 / len(samples):.1%} top5={top5 / len(samples):.1%} "
        f"number-located={located / len(samples):.1%} pages cold {_stats(cold)}")
    # type-ahead: first half of the street name (>= 3 chars) + city
    cold, top5 = [], 0
    for sid, name, city, *_ in samples[:100]:
        pre = name[: max(3, len(name) // 2)]
        _reads.clear()
        g = Gator(_open(path))
        res = g.search(f"{pre}, {city}" if city else pre)
        cold.append(len(_reads))
        top5 += any(h["street_id"] == sid for h in res)
    out(f"search type-ahead n={len(cold)}: top5={top5 / len(cold):.1%} pages cold {_stats(cold)}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="logator-bench")
    p.add_argument("db")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    run(a.db, a.n, a.seed)


if __name__ == "__main__":
    main()
