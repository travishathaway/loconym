"""Generate golden vectors + a database so the TypeScript client can be checked against the Python reference.

  loconym-golden NAME PBF OUTDIR
Writes OUTDIR/NAME.sqlite and OUTDIR/NAME.golden.json (normalizer, codec and query expectations).
"""
import argparse
import json
import random
from pathlib import Path

from .build import build
from .codec import Cell, StreetNumbers, encode_housenumbers, encode_leaf, encode_postings, lonlat_tile, tile_bounds
from .codec import decode_housenumbers as _dhn
from .reader import Loconym

NORMALIZER_CASES = [
    "Rue Grimaldi", "Hauptstraße", "Hauptstr.", "HAUPTSTR", "Str", "Am Wall 12a", "Église-Saint-Étienne",
    "  Ünter den  Linden ", "Müllerstraße 5", "Łódź", "İstanbul Caddesi", "ﬁnance ﬂow", "ＦＵＬＬ ＷＩＤＴＨ 12",
    "Straße des 17. Juni", "Rue de l'Église", "Ἀθῆναι", "東京都", "Москва ул. Тверская", "naïve café", "Zoë's",
    "Åre Straße", "straße", "Schloßstr. 1", "x" * 3 + "str", "ǅ digraph", "Königsallee", "Œuvre", "Ærø", "ñandú",
    "ß", "ẞ", "", "---", "12/14", "Hbf. (Süd)",
]


def _rand_cell(rng, box):
    ox, oy, ex, ey = box

    def pt():
        return rng.uniform(ox, ex), rng.uniform(oy, ey)

    def line(n):
        return [pt() for _ in range(n)]

    c = Cell()
    c.admin = [(1, None), (7, [[line(5), line(4)]]), (9, [[line(4)]])]
    c.streets = [(rng.randint(1, 100000), line(rng.randint(2, 8))) for _ in range(rng.randint(0, 6))]
    c.addrs = [(rng.randint(1, 100000), rng.choice(["1", "12a", "7-9", "Ä3", "100", "5/2"]), *pt())
               for _ in range(rng.randint(0, 12))]
    c.interps = [(rng.randint(1, 100000), rng.choice([1, 2]), rng.randint(1, 20), rng.randint(21, 99), line(3))]
    c.pois = [(rng.randint(1, 100000), *pt()) for _ in range(rng.randint(0, 5))]
    return c


def _jsonable(o):
    if isinstance(o, tuple):
        return [_jsonable(x) for x in o]
    if isinstance(o, list):
        return [_jsonable(x) for x in o]
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    return o


def make(name: str, pbf: str, outdir: str, n_queries: int = 150, seed: int = 11):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / f"{name}.sqlite"
    build(pbf, str(db_path), log=lambda m: None)
    rng = random.Random(seed)
    from .normalize import normalize_tokens

    golden = {"normalizer": [[s, normalize_tokens(s)] for s in NORMALIZER_CASES]}

    # codec vectors
    leaves = []
    for z in (12, 16, 17, 19):
        for _ in range(4):
            lon, lat = rng.uniform(-170, 170), rng.uniform(-70, 70)
            box = tile_bounds(*lonlat_tile(lon, lat, z), z)
            cell = _rand_cell(rng, box)
            blob = encode_leaf(box, cell)
            from .codec import decode_leaf
            leaves.append({"box": list(box), "hex": blob.hex(), "decoded": _jsonable(decode_leaf(blob, box).__dict__)})
    golden["leaves"] = leaves
    hn = []
    for _ in range(6):
        sn = StreetNumbers(
            addrs=[(rng.choice(["1", "2a", "10", "3-5", "Ä"]), rng.uniform(-170, 170), rng.uniform(-80, 80))
                   for _ in range(rng.randint(0, 20))],
            interps=[(2, 2, 40, [(rng.uniform(-100, 100), rng.uniform(-60, 60)) for _ in range(3)])])
        blob = encode_housenumbers(sn)
        hn.append({"hex": blob.hex(), "decoded": _jsonable(_dhn(blob).__dict__)})
    golden["housenumbers"] = hn
    ids = sorted(rng.sample(range(1, 3_000_000), 50))
    golden["postings"] = {"hex": encode_postings(ids).hex(), "ids": ids}
    golden["cell_keys"] = [[x, y, z, __import__("loconym.codec", fromlist=["cell_key"]).cell_key(x, y, z)]
                           for x, y, z in [(0, 0, 1), (5, 9, 16), (34567, 21000, 16), (200000, 100000, 19), (3, 2, 12)]]

    # query expectations from a real DB
    g = Loconym.open(db_path)
    names = dict(g.db.execute("SELECT id, name FROM street"))
    cities = dict(g.db.execute("SELECT id, name FROM admin"))
    parents = dict(g.db.execute("SELECT id, parent FROM street"))
    rows = g.db.execute("SELECT street_id, data FROM housenumber").fetchall()
    samples = []
    for sid, blob in rows:
        for h, lon, lat in _dhn(bytes(blob)).addrs:
            samples.append((sid, h, lon, lat))
    rng.shuffle(samples)
    samples = samples[:n_queries]
    minx, miny, maxx, maxy = (float(v) for v in g.meta["bbox"].split(","))
    reverse = []
    for _sid, _h, lon, lat in samples:
        for zoom, dx, dy in ((18, 0, 0), (18, 8e-5, -6e-5), (17, 2e-4, 1e-4), (10, 0, 0)):
            reverse.append({"lon": lon + dx, "lat": lat + dy, "zoom": zoom,
                            "expected": _jsonable(g.reverse(lon + dx, lat + dy, zoom))})
    for _ in range(20):
        lon, lat = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        reverse.append({"lon": lon, "lat": lat, "zoom": 18, "expected": _jsonable(g.reverse(lon, lat, 18))})
    reverse.append({"lon": 0.0, "lat": 0.0, "zoom": 18, "expected": None})
    # POI-aware reverse, at (and near) a sample of POIs
    for _pid, lat, lon in g.db.execute("SELECT id, lat, lon FROM poi ORDER BY rank, id LIMIT 60").fetchall():
        for dx, dy in ((0, 0), (2e-4, 1e-4)):
            x, y = lon / 1e6 + dx, lat / 1e6 + dy
            reverse.append({"lon": x, "lat": y, "zoom": 18, "pois": True,
                            "expected": _jsonable(g.reverse(x, y, 18, pois=True))})
    golden["reverse"] = reverse

    search = []
    for sid, h, _lon, _lat in samples:
        city = cities.get(parents[sid], "")
        nm = names[sid]
        for q in (f"{nm} {h}, {city}", f"{h} {nm}", nm, f"{nm[: max(3, len(nm) // 2)]}, {city}", f"{nm.upper()} {h}, {city}"):
            search.append({"args": {"q": q, "limit": 5}, "expected": _jsonable(g.search(q, limit=5))})
        search.append({"args": {"street": nm, "city": city, "limit": 3}, "expected": _jsonable(g.search(street=nm, city=city, limit=3))})
    # POI queries: by name, by name + city, and by a prefix
    for _pid, nm, parent in g.db.execute("SELECT id, name, parent FROM poi ORDER BY rank, id LIMIT 60").fetchall():
        city = cities.get(parent, "")
        for q in (nm, f"{nm}, {city}", nm[: max(3, len(nm) // 2)]):
            search.append({"args": {"q": q, "limit": 5}, "expected": _jsonable(g.search(q, limit=5))})
    # POI name + address ("Netto Dammweg"), with and without the house number
    for _pid, nm, street, hn in g.db.execute(
            "SELECT id, name, street, housenumber FROM poi WHERE street IS NOT NULL ORDER BY rank, id LIMIT 60"):
        for q in (f"{nm} {street}", f"{nm} {street} {hn}" if hn else f"{nm}, {street}"):
            search.append({"args": {"q": q, "limit": 5}, "expected": _jsonable(g.search(q, limit=5))})
    # category queries in every language, with connector words, comma form, and structured form
    phrases = g.db.execute("SELECT token FROM phrase WHERE token IN ('museum','museen','museos','restaurants',"
                           "'supermarkets','supermarche','churches','kirchen','iglesias','pharmacies','parks')").fetchall()
    places = [c for (c,) in g.db.execute("SELECT DISTINCT name FROM admin WHERE level<=8 ORDER BY level DESC, id LIMIT 3")]
    for (tok,) in phrases:
        for place in places:
            for q in (f"{tok} in {place}", f"{tok} near {place}", f"{tok} en {place}", f"{tok}, {place}", f"{tok} {place}"):
                search.append({"args": {"q": q, "limit": 5}, "expected": _jsonable(g.search(q, limit=5))})
            search.append({"args": {"street": tok, "city": place, "limit": 3},
                           "expected": _jsonable(g.search(street=tok, city=place, limit=3))})
    # interpolation: interior housenumbers that have no real address
    n_interp = 0
    for sid, blob in rows:
        sn = _dhn(bytes(blob))
        have = {h.lower() for h, *_ in sn.addrs}
        for step, first, last, _pts in sn.interps:
            lo, hi = min(first, last), max(first, last)
            for num in range(lo + 1, hi):
                if (step == 1 or (num - first) % 2 == 0) and str(num) not in have and n_interp < 80:
                    n_interp += 1
                    q = f"{names[sid]} {num}, {cities.get(parents[sid], '')}"
                    search.append({"args": {"q": q, "limit": 5}, "expected": _jsonable(g.search(q, limit=5))})
    golden["search"] = search
    (out / f"{name}.golden.json").write_text(json.dumps(golden, ensure_ascii=False, separators=(",", ":")))
    return db_path


def main(argv=None):
    p = argparse.ArgumentParser(prog="loconym-golden")
    p.add_argument("name")
    p.add_argument("pbf")
    p.add_argument("outdir")
    a = p.parse_args(argv)
    path = make(a.name, a.pbf, a.outdir)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
