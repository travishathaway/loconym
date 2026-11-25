---
title: loconym
description: Offline reverse and forward geocoding from a single compact SQLite file.
---

<style>
h1 { display: none }
</style>

<div class="loconym-hero" markdown>
![loconym logo](assets/logo/svg/loconym-large.svg)
<div style="text-align: center">
<em>A local geocoder with alligator mascot!</em>
</div>
</div>


**Offline geocoding from a single compact SQLite file built from OpenStreetMap data.** No server, no API keys.

- **Reverse geocoding**: lat/lon → address (house number, street, suburb, city, state, country)
- **Search**: address text → lat/lon, with type-ahead, house numbers and address interpolation

<iframe class="loconym-demo" src="demo/" title="loconym demo: search Berlin addresses" loading="lazy"></iframe>
<p class="loconym-demo-caption">Search any address in Berlin. It runs entirely in your browser from one SQLite file,
which downloads when you start. Source: <a href="https://github.com/travishathaway/loconym/tree/main/examples/berlin-map"><code>examples/berlin-map</code></a>.</p>

!!! tip "Try the full example app"

    The [example app](https://github.com/travishathaway/loconym/tree/main/examples/browser-demo) in the repository
    goes further: it reads the database with HTTP range requests, switches between datasets and retrieval modes,
    and reverse geocodes wherever you click.
    [Run it yourself](how-to/run-the-example.md).

loconym has two parts that share one [file format](reference/format-spec.md):

| | What it does | Install |
|---|---|---|
| **Python CLI** (`loconym`) | Builds a database from an `.osm.pbf` extract | `pip install loconym` |
| **TypeScript client** (`loconym`) | Queries the database in the browser, by downloading it or by reading only the pages it needs over HTTP range requests | `npm install loconym` |

```sh
loconym build monaco-latest.osm.pbf -o monaco.sqlite
```

```ts
import { Loconym } from 'loconym';

const geocoder = await Loconym.open({ url: '/data/monaco.sqlite', mode: 'fetch' });
const place = await geocoder.reverse({ lat: 43.7384, lon: 7.4246 });
console.log(place?.display_name); // "Avenue des Papalins 9, Monte-Carlo, Monaco"
```

## Where to go next

<div class="grid cards" markdown>

-   **Tutorials**

    ---

    New to loconym? [Build your first offline geocoder](tutorials/first-geocoder.md) end to end in about 15 minutes.

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

    [How loconym works](explanation/architecture.md), [range vs fetch mode](explanation/range-vs-fetch.md), and
    [how search matches addresses](explanation/matching.md).

</div>

!!! warning "Early software"

    The format is v0 and the defaults are tuned for Germany. See [Status and limitations](explanation/status.md).
