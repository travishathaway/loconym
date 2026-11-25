import random

from logator.codec import (
    Cell,
    StreetNumbers,
    cell_key,
    decode_housenumbers,
    decode_leaf,
    decode_postings,
    encode_housenumbers,
    encode_leaf,
    encode_postings,
    encode_split,
    is_split,
    lonlat_tile,
    tile_bounds,
)

BOX = tile_bounds(*lonlat_tile(8.8, 53.07, 16), 16)


def close(a, b, q=1e-6):
    return abs(a - b) <= q


def test_cell_roundtrip():
    ox, oy = BOX[0], BOX[1]
    c = Cell(
        admin=[(1, None), (7, [[[(ox, oy), (ox + 1e-4, oy), (ox + 1e-4, oy + 1e-4), (ox, oy)]]])],
        streets=[(3, [(ox + 1e-5, oy + 2e-5), (ox + 2e-4, oy + 1e-4)])],
        addrs=[(3, "12a", ox + 5e-5, oy + 5e-5), (3, "4", ox + 6e-5, oy + 1e-5), (9, "1", ox + 7e-5, oy + 9e-5)],
        interps=[(3, 2, 2, 10, [(ox, oy), (ox + 1e-4, oy + 1e-4)])],
    )
    blob = encode_leaf(BOX, c)
    assert not is_split(blob)
    d = decode_leaf(blob, BOX)
    assert d.admin[0] == (1, None) and d.admin[1][0] == 7
    assert all(close(a, b) for p, q in zip(d.admin[1][1][0][0], c.admin[1][1][0][0]) for a, b in zip(p, q))
    assert d.streets[0][0] == 3 and len(d.streets[0][1]) == 2
    assert sorted((s, h) for s, h, *_ in d.addrs) == [(3, "12a"), (3, "4"), (9, "1")]
    for s, h, x, y in d.addrs:
        ref = next(a for a in c.addrs if a[:2] == (s, h))
        assert close(x, ref[2]) and close(y, ref[3])
    assert d.interps[0][:4] == (3, 2, 2, 10)


def test_split_marker():
    assert is_split(encode_split())


def test_housenumbers_roundtrip():
    sn = StreetNumbers(addrs=[("1", 8.8, 53.07), ("2b", 8.8001, 53.0702)], interps=[(2, 2, 10, [(8.8, 53.07), (8.81, 53.08)])])
    d = decode_housenumbers(encode_housenumbers(sn))
    assert [a[0] for a in d.addrs] == ["1", "2b"]
    assert close(d.addrs[1][1], 8.8001, 1e-7) and close(d.addrs[1][2], 53.0702, 1e-7)
    assert d.interps[0][:3] == (2, 2, 10) and close(d.interps[0][3][1][0], 8.81)


def test_postings_roundtrip():
    ids = random.Random(1).sample(range(1, 10**6), 500)
    assert decode_postings(encode_postings(ids)) == sorted(ids)


def test_cell_key_unique_across_zoom():
    assert cell_key(0, 0, 3) != cell_key(0, 0, 4)
    assert cell_key(5, 9, 16) > cell_key(5, 9, 15)
