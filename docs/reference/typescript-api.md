# TypeScript API

Package: [`loconym`](https://www.npmjs.com/package/loconym), ESM only, with type declarations.

```ts
import { Loconym, CapabilityError, normalizeTokens } from 'loconym';
import type {
  OpenOptions, ReverseOptions, ReverseResult, SearchOptions, SearchResult, AdminArea, Db,
} from 'loconym';
```

## `Loconym`

### `Loconym.open(options)`

```ts
static open(options: OpenOptions): Promise<Loconym>
```

Opens a database and reads its `meta` table. Rejects if:

- the file can't be fetched;
- `mode` is `'range'` and the page isn't cross-origin isolated (`SharedArrayBuffer` is unavailable);
- the database's format major version isn't `0` (`unsupported format version …`).

### `OpenOptions`

| Property | Type | Default | Description |
|---|---|---|---|
| `url` | `string` | *(required)* | URL of the `.sqlite` file. Relative URLs are resolved against the page. |
| `mode` | `'range' \| 'fetch'` | `'range'` | `'range'` reads pages on demand with HTTP range requests. `'fetch'` downloads the whole file once and queries it in memory. See [Range mode vs fetch mode](../explanation/range-vs-fetch.md). |
| `wasmUrl` | `string` | bundled | Fetch mode only: where to load `sqlite3.wasm` from. |
| `range.maxPageSize` | `number` | `4096` | Range mode: largest page size expected, in bytes. |
| `range.cacheSizeKiB` | `number` | `4096` | Range mode: size of the shared page cache, in KiB. |
| `range.timeoutMs` | `number` | `20000` | Range mode: timeout for one HTTP request. |

### `geocoder.reverse(options)`

```ts
reverse(options: ReverseOptions): Promise<ReverseResult | null>
```

Finds the address, street or area at a point. Returns `null` when the point is outside the area the database
covers. Throws `CapabilityError` if the database has no `reverse` capability.

### `ReverseOptions`

| Property | Type | Default | Description |
|---|---|---|---|
| `lat` | `number` | *(required)* | Latitude, WGS 84 degrees. |
| `lon` | `number` | *(required)* | Longitude, WGS 84 degrees. |
| `zoom` | `number` | `18` | Detail level, following Nominatim: `>= 18` may return an address, `>= 16` a street, lower values only admin areas. |

### `ReverseResult`

| Property | Type | Description |
|---|---|---|
| `kind` | `'addr' \| 'street' \| null` | What was matched: an address point within 40 m, the nearest street, or nothing (admin areas only). |
| `street` | `string \| null` | Street name. |
| `housenumber` | `string \| null` | House number, when `kind` is `'addr'`. |
| `street_id` | `number \| null` | Internal street id. |
| `admin` | `AdminArea[]` | Containing administrative areas, deepest first. |
| `lat`, `lon` | `number` | The matched point: the address, or the nearest point on the street. The input point if nothing matched. |
| `distance_m` | `number \| null` | Distance from the input point to the match, in metres (0.1 m precision). |
| `place_rank` | `number \| null` | Nominatim-style rank: 30 for an address, 26 for a street, otherwise the deepest area's rank. |
| `address` | `Record<string, string>` | Nominatim-style parts: `house_number`, `road`, and area keys by admin level (see below). |
| `display_name` | `string` | Formatted, e.g. `"Avenue des Papalins 9, Monte-Carlo, Monaco"`. |

Area keys in `address`, by OSM `admin_level`:

| Level | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|
| Key | `country` | `region` | `state` | `state_district` | `county` | `municipality` | `city` | `city_district` | `suburb` | `neighbourhood` |

### `AdminArea`

| Property | Type | Description |
|---|---|---|
| `id` | `number` | Internal admin id. |
| `level` | `number` | OSM `admin_level`. |
| `name` | `string` | Name. |
| `rank` | `number` | Nominatim-style place rank (country 4, state 8, county 12, city 16, suburb 20, …). |

Example (Monaco):

```json
{
  "kind": "addr",
  "street": "Avenue des Papalins",
  "housenumber": "9",
  "street_id": 103,
  "admin": [
    { "id": 4, "level": 10, "name": "Monte-Carlo", "rank": 20 },
    { "id": 2, "level": 8, "name": "Monaco", "rank": 16 },
    { "id": 1, "level": 2, "name": "Monaco", "rank": 4 }
  ],
  "lon": 7.4241886484375,
  "lat": 43.73851917799621,
  "distance_m": 35.6,
  "place_rank": 30,
  "address": { "house_number": "9", "road": "Avenue des Papalins", "country": "Monaco", "city": "Monaco", "suburb": "Monte-Carlo" },
  "display_name": "Avenue des Papalins 9, Monte-Carlo, Monaco"
}
```

### `geocoder.search(options)`

```ts
search(options: SearchOptions | string): Promise<SearchResult[]>
```

Finds streets, and house numbers on them, matching a text query. A string argument is shorthand for `{ q: string }`.
Returns at most `limit` results, best first. It returns an empty array when nothing matches, or when the city part
matches no area. Throws `CapabilityError` if the database was built with `--search none`.

### `SearchOptions`

| Property | Type | Default | Description |
|---|---|---|---|
| `q` | `string` | | Free-form query, e.g. `"Hauptstraße 12, Bremen"`. Text after the last comma is the place; text before the first comma is the street and optional house number. |
| `street` | `string` | | Structured query: street, optionally with a house number. Ignored if `q` is set. |
| `city` | `string` | | Structured query: place name. Ignored if `q` is set. |
| `limit` | `number` | `5` | Maximum number of results. |
| `minPrefix` | `number` | `3` | Minimum length of the last street word before it is matched as a prefix (type-ahead). |

### `SearchResult`

| Property | Type | Description |
|---|---|---|
| `street_id` | `number` | Internal street id. |
| `name` | `string` | Street name. |
| `city_id` | `number` | Admin id of the street's city-level area (`0` if none). |
| `city` | `string \| null` | Name of that area. |
| `lat`, `lon` | `number` | The house if the number was found, otherwise a point on the street's longest way. |
| `score` | `number` | Ranking score (higher is better). Only meaningful within one result list. |
| `housenumber` | `string \| null` | The house number, if the query had one and it was located. |
| `interpolated` | `boolean \| undefined` | `true` if the position comes from an address interpolation line. |
| `display_name` | `string` | Formatted, e.g. `"Avenue des Papalins 9, Monaco"`. |

### `geocoder.capabilities`

```ts
readonly capabilities: string[]
```

What the database supports: some of `reverse`, `search`, `housenumber` and `interpolation`.

### `geocoder.meta`

```ts
readonly meta: Record<string, string>
```

The database's `meta` table: `format_version`, `created_utc`, `source`, `bbox`, `attribution`, `city_level`, and
others. See [meta keys](format-spec.md#meta-keys).

### `geocoder.close()`

```ts
close(): Promise<void>
```

Closes the database and, in range mode, stops its worker.

## `CapabilityError`

```ts
class CapabilityError extends Error {}
```

Thrown by `reverse` or `search` when the database was built without that capability.

## `normalizeTokens(text)`

```ts
normalizeTokens(input: string): string[]
```

The text normalizer used for indexing and search. It returns the tokens a string is matched by, and is identical to
the Python builder's (see [Normalizer](format-spec.md#6-normalizer-must-be-bit-identical-in-python-and-typescript)).

```ts
normalizeTokens('Hauptstr. 12a');   // ['hauptstrasse', '12a']
normalizeTokens('Église-Saint-Étienne'); // ['eglise', 'saint', 'etienne']
```

## `Db`

```ts
interface Db {
  all(sql: string, bind?: (string | number)[]): Promise<unknown[][]>;
  close(): Promise<void>;
}
```

The minimal read-only SQL interface the geocoder runs on. Both storage modes implement it.
