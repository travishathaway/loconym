# Python API

The `loconym` package is mainly a [command-line tool](cli.md), but its builder and its reference reader can also be
used from Python.

!!! note

    This API isn't stable before 1.0. The command line is the supported interface.

## `loconym.build.build`

```python
from loconym.build import build

stats = build(
    "monaco-latest.osm.pbf",
    "monaco.sqlite",
    language="en",
    city_level=8,
    search=True,
    max_leaf_bytes=16384,
    keep_scratch=False,
    log=print,
    prefilter_mode="auto",
    node_index="auto",
)
# {'size': 110592, 'cells': 56, 'split_markers': 0, 'streets': 343, 'housenumbers': 452, 'admins': 11}
```

The keyword arguments match the [`loconym build`](cli.md#loconym-build) options. `search=False` is `--search none`.
`log` is called with each progress message. Returns a dict of summary statistics.

## `loconym.reader.Loconym`

A Python implementation of the query algorithms in the [format spec](format-spec.md). The TypeScript client mirrors
it, and the parity tests check both against the same golden vectors. Use it for testing, analysis, or server-side
lookups.

```python
from loconym.reader import Loconym

g = Loconym.open("monaco.sqlite")

g.meta["format_version"]        # '0.2'
g.caps                          # {'reverse', 'search', 'housenumber', 'interpolation', 'poi'}

g.reverse(7.4246, 43.7384)      # note: lon, lat
# {'kind': 'addr', 'street': 'Avenue des Papalins', 'housenumber': '9', ...,
#  'display_name': 'Avenue des Papalins 9, Monte-Carlo, Monaco'}

g.search("Avenue des Papalins 9, Monaco")
# [{'street_id': 103, 'name': 'Avenue des Papalins', 'lat': 43.7385194, 'lon': 7.4241888,
#   'housenumber': '9', 'city': 'Monaco', 'display_name': 'Avenue des Papalins 9, Monaco', ...}]

g.search(street="Rue Grimaldi", city="Monaco", limit=1)
```

| Member | Description |
|---|---|
| `Loconym.open(path)` | Open a database file read-only. |
| `Loconym(db)` | Wrap an open `sqlite3` or `apsw` connection, for example one using a page-counting VFS. |
| `meta` | `dict` of the `meta` table. |
| `caps` | `set` of capabilities. |
| `reverse(lon, lat, zoom=18)` | Same algorithm and result shape as the TypeScript [`reverse`](typescript-api.md#geocoderreverseoptions). **Argument order is lon, lat.** |
| `search(q=None, *, street=None, city=None, limit=5, min_prefix=3)` | Same as the TypeScript [`search`](typescript-api.md#geocodersearchoptions). |

`reverse` and `search` raise `loconym.reader.CapabilityError` for capabilities the database lacks.

## `loconym.normalize`

```python
from loconym.normalize import normalize_tokens, normalize_key

normalize_tokens("Hauptstr. 12a")       # ['hauptstrasse', '12a']
normalize_key("  Ünter den  Linden ")   # 'unter den linden'
```

Identical to the TypeScript [`normalizeTokens`](typescript-api.md#normalizetokenstext).
