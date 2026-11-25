import random
from pathlib import Path

import pytest

from logator.build import build
from logator.reader import CapabilityError, Gator

PBF = Path(__file__).resolve().parents[2] / "fixtures" / "monaco" / "monaco.osm.pbf"
pytestmark = pytest.mark.skipif(not PBF.exists(), reason="monaco fixture missing")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    out = tmp_path_factory.mktemp("build") / "monaco.sqlite"
    build(str(PBF), str(out), log=lambda m: None)
    return out


def test_meta_and_size(db):
    g = Gator.open(db)
    assert g.meta["format_version"].startswith("0.")
    assert {"reverse", "search", "housenumber"} <= g.caps
    assert db.stat().st_size < 300_000


def test_reverse_at_addresses(db):
    g = Gator.open(db)
    rows = g.db.execute("SELECT street_id, data FROM housenumber").fetchall()
    from logator.codec import decode_housenumbers
    rng = random.Random(3)
    names = dict(g.db.execute("SELECT id, name FROM street"))
    samples = []
    for sid, blob in rows:
        for hn, lon, lat in decode_housenumbers(bytes(blob)).addrs:
            samples.append((sid, hn, lon, lat))
    ok = 0
    sample = rng.sample(samples, min(200, len(samples)))
    for sid, hn, lon, lat in sample:
        r = g.reverse(lon, lat)
        ok += bool(r and r["kind"] == "addr" and r["street"] == names[sid] and r["housenumber"] == hn)
    assert ok / len(sample) > 0.95


def test_reverse_admin_chain(db):
    g = Gator.open(db)
    r = g.reverse(7.4246, 43.7384)
    assert r and any(a["name"] == "Monaco" for a in r["admin"])


def test_reverse_outside_dataset(db):
    assert Gator.open(db).reverse(0.0, 0.0) is None


def test_search_roundtrip(db):
    g = Gator.open(db)
    n = ok = 0
    for sid, name in g.db.execute("SELECT id, name FROM street WHERE parent>0 LIMIT 150").fetchall():
        res = g.search(name, limit=10)
        n += 1
        ok += any(h["street_id"] == sid for h in res)
    assert ok / n > 0.9


def test_search_housenumber_located(db):
    g = Gator.open(db)
    from logator.codec import decode_housenumbers
    sid, blob = g.db.execute("SELECT street_id, data FROM housenumber WHERE length(data)>20 LIMIT 1").fetchone()
    name = g.db.execute("SELECT name FROM street WHERE id=?", (sid,)).fetchone()[0]
    hn, lon, lat = decode_housenumbers(bytes(blob)).addrs[0]
    res = g.search(f"{name} {hn}")
    hit = next(h for h in res if h["street_id"] == sid)
    assert abs(hit["lon"] - lon) < 1e-6 and abs(hit["lat"] - lat) < 1e-6 and hit["housenumber"] == hn


def test_search_none_capability(tmp_path):
    out = tmp_path / "m.sqlite"
    build(str(PBF), str(out), search=False, log=lambda m: None)
    g = Gator.open(out)
    assert "search" not in g.caps
    with pytest.raises(CapabilityError):
        g.search("x")
    assert g.reverse(7.4246, 43.7384)["street"] is not None
