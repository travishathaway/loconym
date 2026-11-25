<p align="center"><img src="docs/assets/logo/svg/logator-large.svg" alt="logator" width="140"></p>

# logator

[![CI](https://github.com/travishathaway/logator/actions/workflows/ci.yml/badge.svg)](https://github.com/travishathaway/logator/actions/workflows/ci.yml)
[![Wheel](https://github.com/travishathaway/logator/actions/workflows/wheel.yml/badge.svg)](https://github.com/travishathaway/logator/actions/workflows/wheel.yml)
[![PyPI](https://img.shields.io/pypi/v/logator)](https://pypi.org/project/logator/)
[![npm](https://img.shields.io/npm/v/@thath/logator)](https://www.npmjs.com/package/@thath/logator)
[![Docs](https://img.shields.io/badge/docs-travishathaway.github.io%2Flogator-70853C)](https://travishathaway.github.io/logator/)

Offline geocoding from a single compact SQLite file built from an `.osm.pbf`:

- **reverse**: lat/lon → address (house number, street, suburb, city, state, country)
- **search**: address text → lat/lon, with type-ahead, house numbers and address interpolation

A Python **builder** creates the database; a TypeScript **client** queries it in the browser, either by downloading the
file or by reading only the pages it needs with HTTP range requests. No server, no API keys.

**Documentation: <https://travishathaway.github.io/logator/>**

```
builder/   Python CLI + reference reader + benchmarks   (PyPI: logator)
client/    TypeScript API                                (npm: @thath/logator)
examples/  browser-demo (Vite + Leaflet)
docs/      documentation website (Zensical), incl. the format spec: docs/reference/format-spec.md
fixtures/  Geofabrik extracts (git-ignored), golden test vectors (monaco committed, bremen generated)
```

Data © OpenStreetMap contributors (ODbL). License: GPL-3.0-or-later.

## Install

```sh
pip install logator              # CLI: logator build
npm install @thath/logator       # browser client
```

## Usage

```sh
logator build monaco-latest.osm.pbf -o monaco.sqlite
```

```ts
import { Logator } from '@thath/logator';

const gator = await Logator.open({ url: '/data/bremen.sqlite', mode: 'range' }); // or 'fetch'

const r = await gator.reverse({ lat: 53.0758, lon: 8.8072 });
// { display_name, address: { house_number, road, suburb, city, state, country }, lat, lon, kind, place_rank, ... }

const hits = await gator.search({ q: 'Am Wall 1, Bremen', limit: 5 });
// [{ display_name, lat, lon, housenumber, interpolated?, score, ... }]
const hits2 = await gator.search({ street: 'Am Wall', city: 'Bremen' });   // structured
```

- `mode: 'range'` needs a cross-origin-isolated page (`Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp`, for SharedArrayBuffer) and a host that supports HTTP `Range` (and CORS `Range`/`Content-Range` if cross-origin). A lookup
  typically reads a few KB; in our tests 30 queries on Bremen (3.9 MB) read ~136 KB in 29 requests.
- `mode: 'fetch'` downloads the file once; best for small bundled databases.
- `search`/`reverse` throw `CapabilityError` when the database was built without them (`--search none`).

See the [tutorial](https://travishathaway.github.io/logator/tutorials/first-geocoder/) for a complete walkthrough.

## Development

Everything is managed with [pixi](https://pixi.sh) (Python, Node, pnpm, docs tooling; all from conda-forge).

```sh
pixi install
curl -L --create-dirs -o fixtures/monaco/monaco.osm.pbf https://download.geofabrik.de/europe/monaco-latest.osm.pbf
curl -L --create-dirs -o fixtures/bremen/bremen.osm.pbf https://download.geofabrik.de/europe/germany/bremen-latest.osm.pbf

pixi run test              # full suite: pytest + vitest
pixi run test-builder      # pytest
pixi run golden-data       # Bremen golden vectors for client-test
pixi run client-test       # vitest: decoders + queries vs the Python reference, fetch and range modes
pixi run lint              # ruff
pixi run docs-serve        # documentation at http://localhost:8000
pixi run demo-data         # builds Berlin + Monaco databases into the demo (needs fixtures/berlin/berlin.osm.pbf)
pixi run demo-dev          # http://localhost:5173
```

Releases: tag `py-vX.Y.Z` publishes the CLI to PyPI, `js-vX.Y.Z` publishes the client to npm. See
[Publish a release](https://travishathaway.github.io/logator/how-to/release/).

## Status

Early. v0 format, Germany-oriented defaults (street grouping at `admin_level` 8). Measured on Monaco, Bremen and Hessen
(see `docs/reference/spike-notes.md`). Not yet implemented: postcodes, POIs, OSM ids, non-Latin normalization, OPFS
driver, scoring beyond token coverage. Germany-scale builds are untested (memory profile is the next task).
