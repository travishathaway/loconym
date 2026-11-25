# logator

Build compact, offline geocoding databases from OpenStreetMap `.osm.pbf` extracts.

`logator build` turns an extract into a single SQLite file that supports:

- **reverse geocoding**: lat/lon → address (house number, street, suburb, city, state, country)
- **search**: address text → lat/lon, with type-ahead, house numbers and address interpolation

The file is queried in the browser by the TypeScript client
[`@thath/logator`](https://www.npmjs.com/package/@thath/logator), either by downloading it or by reading only the
pages a query needs through HTTP range requests. No server, no API keys.

```sh
pip install logator
logator build monaco-latest.osm.pbf -o monaco.sqlite
```

Extracts are available from [Geofabrik](https://download.geofabrik.de/). For country-sized inputs, also install
[osmium-tool](https://osmcode.org/osmium-tool/) (e.g. `conda install -c conda-forge osmium-tool`) so the builder
can pre-filter the input and keep memory bounded.

Documentation: <https://travishathaway.github.io/logator/>

Data © OpenStreetMap contributors (ODbL). License: GPL-3.0-or-later.
