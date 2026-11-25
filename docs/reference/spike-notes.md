---
title: Measurements and design notes
---

!!! info "Development log"

    Measurements and decisions recorded while designing the format, in chronological order. Later sections
    supersede earlier ones (for example, the Hessen results revise the Bremen recommendation).

# Spike notes (Monaco, 2026-11-24)

Script: `builder/spike/spike.py` (throwaway). Input: Geofabrik `monaco-latest.osm.pbf` (705 KB).

Extracted: 11 admin areas, 972 named street ways (366 street groups by parent+name), 452 housenumber rows (126 street groups).

| Variant | Total | Spatial index + geometry | place | term | housenumber |
|---|---|---|---|---|---|
| A: R*Tree + geom table | 184 KiB | ~100 KiB | 48 | 12 | 12 |
| B: cell blobs (z16) | 136 KiB | 56 | 48 | 12 | 12 |

Takeaways: both are far below the ~1 MB Monaco budget; cell blobs are ~26% smaller. Not yet measured: bytes fetched per query over HTTP range, admin polygon storage, cell size at larger scale. Spike gaps: admin polygons are used for parenting but not stored; no interpolation ways; cells use row-major keys (not Hilbert/Z-order).

## Pages read per query (cold, 4 KiB pages, `builder/spike/pagecount.py`, apsw logging VFS)

| Query | A: R*Tree | B: cells |
|---|---|---|
| reverse at Monaco centre | 12 pages (48 KiB) | 12 pages (48 KiB), 3x3 cell ring, 560 candidate features |
| search `boulevard` (187 hits) | 5 pages (20 KiB) | same (shared term index) |
| search `grimaldi` | 8 pages (32 KiB) | same |
| search `grim*` + house numbers | 11 pages (44 KiB) | same |

Caveats: single sample point; the 3x3 ring in B is wasteful (z16 cells hold ~1.2 KB avg, up to 4.8 KB, so some blobs overflow a page) — a smaller z or distance-based neighbour check should cut it. Search "admin resolve" is a placeholder in Monaco's single-city case, and search returns candidates by id order, not scored. Reverse I/O is a tie at this size; B wins on file size (-26%).

# Spike 2: Bremen (2026-11-24)

Script: `builder/spike/spike2.py`. Input: Geofabrik `bremen-latest.osm.pbf` (21 MB; 152k addresses, 21k named street ways -> 6.2k street groups, 149 admin areas at levels 2/4/6/8/9/10/11, 32 interpolation ways).
Format under test: leaf cells keyed by `(1<<2z)|morton(x,y)`; each cell holds clipped admin polygons (or a "fully inside" flag), clipped street polylines, address points with housenumber strings, interpolation segments. Coordinates are varint deltas at 1e-6 deg. Search: `term(t, parent_city) -> postings`, `housenumber(street_id) -> blob`, admin tier keyed `parent=-1`.

| Config | File | Cells | Blob avg/p95/max | Blobs > 1 page | Reverse pages cold / warm | Search pages cold |
|---|---|---|---|---|---|---|
| fixed z16 | 4.05 MiB | 3489 | 611 / 2215 / 6484 B | 27 | 8.5 / 2.4 | 9.9 |
| adaptive (split > 4000 B, z11-19) | 4.06 MiB | 1227 | 1645 / 3411 / 3986 B | 0 | 9.5 / 2.8 | 10.1 |

("warm" = 256 KiB page cache kept across queries, i.e. b-tree interior pages cached; cold = fresh connection each query, which overstates browser cost.)

Sizes by table: cell 2.59 MiB (63%), housenumber 1.26 MiB (31%), street 160 KiB, term 140 KiB, admin 4 KiB. About 27 bytes per address overall.

Correctness (400 / 300 samples, same seed):
- reverse at an address point: 100% returns that address, street and number correct.
- reverse near streets: 98% agree with brute-force nearest street (1 m tie tolerance). Includes neighbour-cell lookup when the nearest street is farther than the cell edge; not yet audited for the 2% misses.
- search "Street N, City": top-1 96-97%, top-5 97-99%, located 97-99% (within 50 m 97-99%). Results are ordered by id (no scoring yet), so top-1 misses are mostly ordering.
- type-ahead (half-typed street + city): ~8 pages cold.
- interpolation: 106 of 166 interior numbers resolved on the interpolated polyline; the other 60 correctly returned an existing real address instead.

## What Bremen surfaced (real-data issues for the format/builder)
1. **Interpolation ways carry no `addr:street`** (0 of 32); street must come from the endpoint nodes, and only 14 of 32 have housenumbers on both ends. Builder must resolve endpoints and fall back gracefully.
2. **Most addresses are building areas, not nodes** (136k of 152k). Area assembly is required, and a representative point must be chosen.
3. **Admin hierarchy is deep and uneven:** levels 2,4,6,8,9,10,11. Streets are grouped by the deepest admin with level <= 8 (the municipality); suburbs come from the point-in-polygon chain stored in the cell, not from the street.
4. **Text normalisation matters:** `ß`->`ss`, diacritics, and `Str.`/`straße` abbreviations are needed; compounds (`Hauptstraße`) are one token, so only prefix matching of the first word works (suffix matching like "strasse" doesn't).
5. **Term/posting key collisions:** admin and street postings must use separate key spaces (bug found and fixed in the spike).
6. **Housenumber coordinates are stored twice** (in cells for reverse, in `housenumber` blobs for search) — 31% of the file. Biggest compaction target.
7. Only 153 of 136k+15k addresses lacked `addr:street`, so dropping them is acceptable for now.

## Decisions / recommendation
- **Spatial index: cell blobs, adaptive split by blob size.** Same total size as fixed z16 and ~0.4 more pages warm, but it bounds blob size (no overflow) and adapts to dense city cores (Germany will include Berlin/Hamburg/Munich, denser than Bremen). Start with limit ~4000 B and re-measure on a bigger state (e.g. Nordrhein-Westfalen).
- **R*Tree dropped.**
- Rough extrapolation (not measured): ~27 B/address implies roughly 0.5-1 GB for all of Germany before compaction work; the housenumber duplication and string/coordinate coding are the levers.

## Open items for the real builder
- Stop duplicating housenumber coordinates (e.g. housenumber blob stores per-street delta coords at lower precision, or points into cells).
- Score search results (token coverage, rank, house number match) instead of id order.
- Handle streets in multiple municipalities; postcodes; `addr:place`; associatedStreet relations.
- Lookup probing: up to 9 key probes per reverse; consider storing the zoom range present per root tile.
- Audit the 2% nearest-street disagreements (likely edge cases in neighbour lookup or quantisation).

# Spike 3: Hessen (2026-11-24)

Input: Geofabrik `hessen-latest.osm.pbf` (332 MB): 1.64M addresses, 302k named street ways -> 104k street groups, 3367 admin areas, 18 interpolation ways (9 usable). Spike extraction 85 s + preparation 237 s in pure Python (memory not measured; NRW at 876 MB was skipped because the in-memory spike would not fit in the 7 GB sandbox).

| Config | File | Cells | Blob avg/p95/max | Blobs > 1 page | Reverse pages cold / warm | Search pages cold avg/p95/max |
|---|---|---|---|---|---|---|
| adaptive (split > 4000 B) | 54.7 MiB | 18.8k | 1524 / 3424 / 4000 B | 7 | 14.8 / **5.6** | 18.4 / 27 / 29 |
| fixed z16 | 57.6 MiB | 145k | 234 / 1184 / 7661 B | 49 | 12.5 / **3.9** | 18.7 / 27 / 57 |

Sizes (adaptive): cell 36.6 MiB, housenumber 12.9 MiB (24%), street 2.6, term 2.5, admin 0.09. About 31 B per address for cells+housenumbers; overall ~35 B/address (was 27 on Bremen: bigger ids and more strings).

Correctness at 1.6M addresses (adaptive/fixed): reverse@address 100%/100% (street and number); nearest street 98%/99%; search top-1 96%/98%, top-5 99%/99%, located 99%/99%; interpolation 22/28 resolved on the polyline, the rest are existing real addresses.

## Revised conclusion (changes the Bremen recommendation)
- **Fixed base zoom (z16) beats adaptive on lookup cost at scale**: 3.9 vs 5.6 warm pages. Adaptive needs up to 9 key probes per lookup and a deeper b-tree; the size win is only 5%. Hot cells in Hessen (incl. central Frankfurt) peak at 7.7 KB (2 pages), so overflow is tolerable.
- **Design adopted for v0: fixed z16 cells, plus a "split" marker only for cells larger than a limit** (e.g. 16 KB); a lookup does one probe at z16 and only descends if it finds a marker. Re-measure on Berlin/Munich-scale density.
- Search type-ahead needs a hard cap: short prefixes in large cities touched up to 100 pages; the client must bound rows scanned per token and require >= 2-3 characters.
- Size at Germany scale (~20x Hessen, extrapolated not measured): ~1 GB uncompressed. Compaction levers to quantify in the real builder: street-id runs inside cells (saves ~3 B/addr), housenumber coordinates at 1e-6 instead of 1e-7, dedupe of name strings, coordinate quantum 1e-5 for admin/street geometry.
- The pure-Python in-memory pipeline does not scale to Germany (~4 GB pbf). The real builder must spill to a scratch SQLite database and process root tiles one at a time.

# Real builder results (2026-11-24)

`loconym build` (scratch-SQLite pipeline, fixed z16 cells + split markers, grouped street runs, admin polygons in cells), measured with `loconym-bench` (reference reader, same seed, 300 sampled addresses).

| Region | File | Build time | Peak RSS | Reverse@address street/number | Reverse pages cold / warm | Search top-1 / top-5 | Search pages cold avg / p95 / max | Type-ahead top-5 |
|---|---|---|---|---|---|---|---|---|
| Monaco | 108 KiB | 1 s | n/a | 100% (tests) | n/a | n/a | n/a | n/a |
| Bremen | 3.75 MiB | 13 s | 219 MB | 100% / 100% | 8.0 / 2.4 | 98% / 98% | 11.0 / 13 / 16 | 87% |
| Hessen | 51.2 MiB | 311 s | 982 MB | 100% / 100% | 11.5 / 3.9 | 99% / 100% | 19.0 / 25 / 67 | 85% |

- Hessen: 103k cells, 0 split markers (no leaf exceeded 16 KiB), 104k streets, 1.64M addresses, 3367 admin areas. Smaller than the Hessen spike (54.7 MiB adaptive / 57.6 fixed) while now also storing admin polygons.
- Memory is dominated by the street-group registry, admin polygons and term postings; scales with streets, not addresses. Extrapolating 982 MB x ~12 suggests Germany needs an estimated several GB (not measured). Needs verification on NRW-sized input; posting construction is the likeliest first thing to stream/spill.
- Type-ahead top-5 (85-87%) is limited by tie-breaking among many streets sharing a prefix; needs real scoring (city size, name length, exact word match) and probably a posting-count-aware cap.
- Search max 67 pages comes from common tokens in big cities; cap or rank-limit postings.

# TypeScript client (2026-11-24)

`client/` ports `reader.py` to TypeScript (`loconym.ts`) on top of two storage drivers: `fetch` (whole file into `@sqlite.org/sqlite-wasm` via `sqlite3_deserialize`) and `range` (`sqlite-wasm-http` HTTP VFS in a worker).

Verification (vitest, Node):
- Golden vectors generated by Python (`loconym-golden`): normalizer (35 cases incl. ß, NFKD, CJK, Greek, ligatures), cell keys (>32-bit), random cell leaves at z12/16/17/19, housenumber blobs, postings: all identical.
- Queries against Monaco and Bremen DBs: 621 reverse and 900 search expectations per DB (incl. 80 interpolation cases on Bremen) reproduce the Python results in `fetch` mode; `range` mode checks every 12th case. 20 tests pass.
- Range traffic, Bremen (3.93 MB file): opening costs 13 KB / 3 requests; 30 queries (20 reverse, 10 search) = 136 KB over 29 range requests (3.5% of the file), with the library's 4 MB shared cache.

Findings:
1. **Numerics:** cell keys exceed 2^32, so the TS port computes them arithmetically; varints use multiplication instead of shifts. Python-only behaviours that would have diverged were removed from the spec: marks are stripped by Unicode category `M*` (not combining class), housenumber tokens use ASCII `[0-9]`.
2. **Range-mode wasm cost:** `sqlite-wasm-http` ships its own SQLite build: 3.6 MB raw / 1.7 MB gzip, versus 0.88 MB / 0.41 MB for the official build used in `fetch` mode. For small databases `fetch` mode is cheaper overall; a custom range VFS on the official build is an option to revisit.
3. **Page size:** `sqlite-wasm-http` recommends 1024-byte pages; we ship 4096. Not yet measured whether 1024 reduces bytes fetched per query (more, smaller requests).
4. The client has no OSM id, so Nominatim's `lookup` is not offered (would require storing ids).
