---
title: Database format
---

# logator database format — v0 (draft)

The contract between `builder/` (writes) and `client/` (reads). Derived from the Monaco, Bremen and Hessen spikes ([Measurements and design notes](spike-notes.md)). Anything marked **[measure]** is a hypothesis to validate with the real builder.

## 1. Container
- One SQLite 3 file. `page_size = 4096`, `journal_mode = off` / never written after build, `VACUUM`ed.
- `PRAGMA application_id = 0x4c474154` ("LGAT"), `PRAGMA user_version = <format major>` (v0 = 0).
- Readers must work through an HTTP range VFS: every query is a small number of keyed point reads or short b-tree range scans. **No table scans at query time.**
- Ship uncompressed `.sqlite` and let the CDN apply brotli.

## 2. Tables
```sql
meta(k TEXT PRIMARY KEY, v) WITHOUT ROWID;
admin(id INTEGER PRIMARY KEY, level INT, name TEXT, parent INT, city INT, rank INT);   -- level = OSM admin_level
street(id INTEGER PRIMARY KEY, name TEXT, parent INT, lat INT, lon INT);                -- parent = admin.id of the city-level area (0 = none); lat/lon = point on the longest way, 1e-6 deg
cell(id INTEGER PRIMARY KEY, data BLOB);
term(t TEXT, parent INT, postings BLOB, PRIMARY KEY(t, parent)) WITHOUT ROWID;
housenumber(street_id INTEGER PRIMARY KEY, data BLOB);
```
- `admin.city`: the nearest ancestor-or-self with `level <= 8` (0 if none); this is the "municipality" streets are grouped under. (Germany-specific default; the level is a build option stored in `meta`.)
- `admin.rank` follows Nominatim's place_rank scale (country 4, state 8, county 12, city 16, suburb 20, ...), derived from `level` through a table in `meta`.
- A **street** is a group of OSM ways with the same normalized name inside the same city area. Ids are dense, assigned in sorted `(parent, normalized name)` order so neighbouring ids share strings and b-tree pages.

### meta keys
`format_version`, `created_utc`, `source` (file name), `osm_timestamp`, `bbox` (minlon,minlat,maxlon,maxlat), `language`, `capabilities` (comma list: `reverse`, `search`, `housenumber`, `interpolation`), `cell_zoom` (16), `coord_quantum` (1e-6), `city_level` (8), `attribution` ("© OpenStreetMap contributors, ODbL 1.0"), `normalizer` (version string, see §6).

## 3. Cells (reverse geocoding)
Key: `id = (1 << 2z) | morton(x, y)` for web-mercator tile `(x, y)` at zoom `z`; the leading sentinel bit makes keys unique across zooms. Base zoom `z = cell_zoom` (16). Cells with no features and no admin coverage are absent (a lookup outside the dataset returns "no result"). Featureless areas that are covered by admin polygons are stored as one admin-only leaf at the coarsest quadtree node (≥ `root_zoom`, 12) that has no features, so lookups probe `cell_zoom` first and then each ancestor up to `root_zoom`; the first row found wins. Tiles with features are always stored at `cell_zoom` (or below it, via a split marker), so the common lookup is a single probe.

A cell blob is one of:
- **Leaf**: `varint 0` then the sections below.
- **Split marker**: `varint 1`. The tile's features are held by its four children at `z+1` (keys computed the same way; recursively the same rule). The builder emits a marker only when a leaf would exceed `max_leaf_bytes` (default 16384) **[measure on Berlin/Munich density]**.

All coordinates are varint zigzag deltas of integers `round((deg - origin) / coord_quantum)`, `origin` = the tile's min lon/lat; the first point of each list is relative to the origin, later points relative to the previous point.

Leaf sections, in order:
1. **admin**: `n`; per entry `admin_id`, `flag`. `flag = 0`: the whole tile lies inside the area. `flag = k+1`: `k` clipped polygons follow; each = `ring_count`, then rings (exterior first), each ring = `point_count` + points. Even-odd fill over all rings of a polygon.
2. **streets**: `n` polylines; per entry `street_id`, `point_count`, points. Polylines are clipped to the tile; a street crossing tiles appears in each.
3. **addresses**: `n`; entries sorted by `street_id`, then housenumber. **[measure: run-length street ids]** `street_id`, `len`, housenumber UTF-8 bytes, point (delta from previous address in the cell).
4. **interpolations**: `n`; per entry `street_id`, `step` (1 all, 2 odd/even), `first`, `last` (integers), `point_count`, points. `first`→`last` runs along the polyline from its first to last vertex.

Address points for building areas use a point inside the building (representative point), not the centroid.

### Reverse lookup (client)
1. Compute `(x, y)` at `cell_zoom`, read `cell`; if a split marker, descend one level at a time. No row ⇒ no result.
2. Admin chain = entries with `flag = 0` plus partial entries whose clipped polygons contain the point. Sort by `level` for display order.
3. Candidates (by requested `zoom`): addresses within 40 m (nearest wins) → streets (nearest segment, metric distance with latitude-scaled longitude) → admin only.
4. If the nearest street is farther than the distance to a tile edge, also read the neighbour tile(s) across that edge and re-evaluate.
5. Resolve names: `street` row for the winner; `admin` rows for the chain. Format `display_name` from street, housenumber, and admin names by level.

## 4. Search (forward geocoding)
- `term(t, parent)`: `t` is a normalized token (§6). `parent = -1`: the postings list admin ids (all levels); `parent >= 0`: postings list street ids belonging to city `parent` (`0` = streets without a city).
- `postings`: ascending ids as delta varints.
- `housenumber(street_id)`: `n` addresses sorted by natural housenumber order; per entry `len`, UTF-8 number, `Δlat`, `Δlon` (first relative to 0), coordinates as integers of 1e-7° **[measure: 1e-6]**; then `m` interpolation segments (`step`, `first`, `last`, `point_count`, absolute points at 1e-6°).

### Search algorithm (client)
1. Split `q` on commas. Last part (if more than one) = place: resolve tokens against `parent = -1` (exact for all but the last token; prefix scan for the last), intersect, map admin ids → `admin.city` → set of cities. Structured parameters (`street`, `city`, …) skip the split.
2. Street part: strip a housenumber token (leading or trailing `[0-9]+[A-Za-z]?`, ASCII digits only), normalize, then for each token look up `(t, city)` for each city (prefix scan for the last token only). Intersect street ids.
3. Cap work: prefix tokens need ≥ 3 characters (configurable), and at most `max_rows` (default 200) postings rows are read per token.
4. Score (client-side, not stored): token coverage, exact vs prefix match, street name length difference, and a preference for larger cities. Return top `limit`.
5. Housenumber: look up `housenumber(street_id)`; exact match first, else the interpolation segment covering the number (matching parity), positioned by proportional distance along the polyline; else the street's own `lat`/`lon` (a point on its longest way).

## 5. Capabilities
`meta.capabilities` declares what is present. A build with `--search none` leaves `term` and `housenumber` empty (`street` is kept: reverse needs street names; addresses stay in cells); the client raises `CapabilityError` for unsupported calls.

## 6. Normalizer (must be bit-identical in Python and TypeScript)
Version string `meta.normalizer`, golden vectors in `fixtures/normalizer.json`, tested in both languages.
1. Replace `ß`/`ẞ` → `ss`.
2. Unicode NFKD, drop all characters of general category `M*` (marks), lowercase (`toLowerCase`/`str.lower`).
3. Split on `[^0-9a-z]+`, drop empties. Non-Latin scripts: **open** (v0 keeps only ASCII after folding; add per-script handling before non-Latin builds).
4. A token ending in `str` with length > 3 gets `asse` appended (`hauptstr` → `hauptstrasse`). Language-specific abbreviation tables are **open**.

## 7. Versioning
`user_version` major changes on incompatible layout changes; `meta.format_version` carries `major.minor`. Readers reject a higher major and tolerate unknown `meta` keys and trailing bytes in blobs.

## 8. Open items
Postcodes; `addr:place` and `associatedStreet`; street names in multiple languages; `extratags`; POIs and zoom-18 buildings as non-address features; multi-region merges; non-Latin normalization; exact `max_leaf_bytes`.
