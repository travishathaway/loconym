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

## Cost

POIs add a `poi` table, a postings namespace and a trailing section in each cell that has one. On the fixtures:
Monaco grows from 110 KB to 155 KB and Bremen from 3.9 MB to 4.5 MB. Use `--no-poi` for an address-only database.

## Known limits

- A station node and its platform polygon, or a building and its node, can both be indexed.
- There are no class queries yet ("museum in Bremen"). Nominatim does this with its special phrases.
- Only the first matching main tag with the best rank is kept for each object.
