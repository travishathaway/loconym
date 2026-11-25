---
title: logator
description: Offline reverse and forward geocoding from a single compact SQLite file.
---

<div class="logator-hero" markdown>
![logator logo](assets/logo/svg/logator-large.svg)
</div>

# logator

**Offline geocoding from a single compact SQLite file built from OpenStreetMap data.** No server, no API keys.

- **Reverse geocoding**: lat/lon → address (house number, street, suburb, city, state, country)
- **Search**: address text → lat/lon, with type-ahead, house numbers and address interpolation

logator has two parts that share one [file format](reference/format-spec.md):

| | What it does | Install |
|---|---|---|
| **Python CLI** (`logator`) | Builds a database from an `.osm.pbf` extract | `pip install logator` |
| **TypeScript client** (`@thath/logator`) | Queries the database in the browser, by downloading it or by reading only the pages it needs over HTTP range requests | `npm install @thath/logator` |

```sh
logator build monaco-latest.osm.pbf -o monaco.sqlite
```

```ts
import { Logator } from '@thath/logator';

const gator = await Logator.open({ url: '/data/monaco.sqlite', mode: 'fetch' });
const place = await gator.reverse({ lat: 43.7384, lon: 7.4246 });
console.log(place?.display_name); // "Avenue des Papalins 9, Monte-Carlo, Monaco"
```

## Where to go next

<div class="grid cards" markdown>

-   **Tutorials**

    ---

    New to logator? [Build your first offline geocoder](tutorials/first-geocoder.md) end to end in about 15 minutes.

-   **How-to guides**

    ---

    Task recipes: [serve with range requests](how-to/range-requests.md), [build address autocomplete](how-to/autocomplete.md),
    [build country-sized databases](how-to/large-extracts.md), and more.

-   **Reference**

    ---

    The [CLI](reference/cli.md), the [TypeScript API](reference/typescript-api.md), the
    [Python API](reference/python-api.md) and the [database format](reference/format-spec.md).

-   **Explanation**

    ---

    [How logator works](explanation/architecture.md), [range vs fetch mode](explanation/range-vs-fetch.md), and
    [how search matches addresses](explanation/matching.md).

</div>

!!! warning "Early software"

    The format is v0 and the defaults are tuned for Germany. See [Status and limitations](explanation/status.md).
