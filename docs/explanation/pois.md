# What counts as a POI

loconym indexes **named places people go to**: museums, parks, stations, universities, hospitals, landmarks,
churches, supermarkets, restaurants. It deliberately does not index street furniture such as post boxes, benches,
waste baskets, speed cameras or parking spaces, even though the OSM wiki's definition of a point of interest
includes them.

## How it was designed

Nominatim is the reference. Its import (`presets.lua` in the Nominatim repository) turns every `amenity=*`,
`shop=*`, `tourism=*`, `historic=*`, ... object into a searchable place, with a short blocklist of values to skip.
Importance then comes mostly from `wikipedia`/`wikidata` tags; objects without them all sit at the bottom.

loconym keeps three of those ideas and changes two:

| Idea | Nominatim | loconym |
|---|---|---|
| Main tag = class and type | `class=key`, `type=value` | Same: stored as `class`, e.g. `tourism=museum` |
| Name tags | `name`, plus `brand` for chains | Same: `name`, falling back to `brand` |
| Wikidata/Wikipedia signal | Drives importance | Boosts rank by 4 and is **required** for ambiguous classes (places of worship, viewpoints, memorials) |
| Which objects | Blocklist, unnamed objects kept | **Allowlist**, a name is required |
| One row per object | One row per main tag | One row, the most prominent class |

The allowlist is the `POI_CLASSES` table in `builder/src/loconym/poi.py`. A short list of values is never
indexed even when named (`EXCLUDED_VALUES`), and `highway=*` and `emergency=*` are always excluded. Named shops
outside the table are kept at the lowest rank.

## Ranking

Each class has a base rank on Nominatim's `rank_search` scale (lower is more prominent): universities and airports
around 20, museums, castles and stations around 22, parks and theatres around 24, supermarkets and restaurants 28
to 29. A `wikidata` or `wikipedia` tag lowers it by 4. At equal text-match score, the lower rank wins.

## Addresses

A search hit for a place shows its address, and `Netto Dammweg` finds that one branch. The street comes from the
POI's own `addr:street` and `addr:housenumber`. In the Bremen and Berlin extracts 42 to 49% of POIs have no address
tags (a shop mapped as a point, for example), so the builder gives them one:

1. the nearest address point within 40 m: its street and house number;
2. otherwise the nearest named street within 60 m: the street only;
3. otherwise nothing, and the result shows the name and city only.

Bremen: 3,652 of 7,180 POIs have the tags, 3,233 are snapped, and 295 have no address. The POI is indexed under the
words of its name and of its street, and a query word must be in the name for a POI to match, so searching for a
street still returns the street.

## Category queries

`museums in Bremen` returns the museums of Bremen, best first. Nominatim does this with *special phrases*: a table
of phrases such as "museums" or "Museen", each mapped to a class like `tourism=museum`, filled from per-language
OSM wiki pages. If a phrase starts the query, the rest is searched as a place, and the answer is the POIs of that
class inside it. loconym keeps that shape, with differences that follow from a static, scan-free file:

| | Nominatim | loconym |
|---|---|---|
| Phrase source | OSM wiki tables, imported per language | Built-in lists for English, Spanish, German and French, in every database |
| Singular and plural | Separate wiki rows | Separate entries |
| Place | Anchor found by name search, then its geometry (or a box of about 5 km around a point) | A city-level area from the normal city lookup |
| Which POIs | All of the class inside the anchor, nearest first, up to 40 | The best 200 per class and city, by rank, then the first `limit` |
| No place ("pharmacy") | Needs a viewbox or point | Not supported yet |
| Operators (`in`, `near`) | Stored per phrase | Both words are just skipped |

The phrase must start the query and the rest must resolve to a city, so a name such as `Hotel de Paris, Monaco`
stays a name search. Ranking inside a class is the POI rank, which is why a `wikidata` or `wikipedia` tag matters:
Berlin has 250 museums, and those with a tag come first.

## Cost

POIs add a `poi` table, a postings namespace, the phrase and category tables, and a trailing section in each cell
that has one. Measured on the fixtures:

| Extract | `--no-poi` | default | Growth |
|---|---|---|---|
| Monaco | 123 KB | 188 KB | +53% |
| Bremen | 3.9 MB | 4.7 MB | +20% |
| Berlin | 11.6 MB | 15.8 MB | +36% |

Berlin's 41,278 POIs do not split any cell: the largest cell is 4.4 KB against the 16 KB limit. Use `--no-poi` for
an address-only database.

## Known limits

- A station node and its platform polygon, or a building and its node, can both be indexed.
- A house number list such as `25;26;27` is kept as written.
- A POI near the edge of a 12-zoom tile (about 10 km) only snaps to features in its own tile.
- Category queries need a place. "Pharmacy near me" needs a spatial lookup that is not built.
- Only the first matching main tag with the best rank is kept for each object.
