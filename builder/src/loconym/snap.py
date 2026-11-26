"""Give POIs without ``addr:street`` an address, so "Netto Dammweg" can find the right branch.

Order of preference, per POI (distances are metric, measured with latitude-scaled longitude):
1. its own ``addr:street`` / ``addr:housenumber`` tags (handled by the caller; this module is skipped),
2. the nearest address point within ``ADDR_SNAP_M`` (street name and house number),
3. the nearest named street way within ``STREET_SNAP_M`` (street name only),
4. nothing: the POI is shown with its name and city only.

Work is done one z12 root tile at a time, using the scratch ``addr`` and ``way`` tables, so memory stays bounded.
POIs within a few tens of metres of a root edge only see features of their own root (ways are replicated across
roots they cross, address points are not); that only costs the rare edge case an address.
"""
import math
import sqlite3
from collections import defaultdict

import shapely
import shapely.wkb as wkb

ADDR_SNAP_M = 40.0
STREET_SNAP_M = 60.0


def _scale(lat: float) -> tuple[float, float]:
    return 111320 * math.cos(math.radians(lat)), 110540


def snap_pois(scratch: sqlite3.Connection, street_names: dict[int, str],
              pois: list[tuple]) -> dict[int, tuple[str, str | None]]:
    """``pois``: ``[(poi_rowid, root, lon, lat)]`` lacking a street. ``street_names``: scratch gid -> name.

    Returns ``{poi_rowid: (street, housenumber or None)}`` for the POIs that could be snapped.
    """
    by_root = defaultdict(list)
    for rid, root, lon, lat in pois:
        by_root[root].append((rid, lon, lat))
    out: dict[int, tuple[str, str | None]] = {}
    for root, items in by_root.items():
        cx, cy = _scale(sum(i[2] for i in items) / len(items))
        pts = shapely.points([lon * cx for _rid, lon, _lat in items], [lat * cy for _rid, _lon, lat in items])

        addrs = scratch.execute("SELECT gid, hn, lon, lat FROM addr WHERE root=?", (root,)).fetchall()
        if addrs:
            tree = shapely.STRtree(shapely.points([a[2] * cx for a in addrs], [a[3] * cy for a in addrs]))
            pi, ai = tree.query_nearest(pts, max_distance=ADDR_SNAP_M, all_matches=False)
            for p, a in zip(pi.tolist(), ai.tolist()):
                gid, hn = addrs[a][0], addrs[a][1]
                if gid in street_names:
                    out[items[p][0]] = (street_names[gid], hn)

        rest = [i for i, it in enumerate(items) if it[0] not in out]
        if not rest:
            continue
        ways = scratch.execute("SELECT gid, wkb FROM way WHERE root=?", (root,)).fetchall()
        if ways:
            scale = (cx, cy)
            lines = [shapely.transform(wkb.loads(w[1]), lambda c, k=scale: c * k) for w in ways]
            tree = shapely.STRtree(lines)
            pi, wi = tree.query_nearest(pts[rest], max_distance=STREET_SNAP_M, all_matches=False)
            for p, w in zip(pi.tolist(), wi.tolist()):
                gid = ways[w][0]
                if gid in street_names:
                    out[items[rest[p]][0]] = (street_names[gid], None)
    return out
