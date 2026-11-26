<p align="center"><img src="docs/assets/logo/svg/loconym-large.svg" alt="loconym" width="300"></p>

<p align="center"><em>A local geocoder with an alligator mascot! </em></p>

[![CI](https://github.com/travishathaway/loconym/actions/workflows/ci.yml/badge.svg)](https://github.com/travishathaway/loconym/actions/workflows/ci.yml)
[![Wheel](https://github.com/travishathaway/loconym/actions/workflows/wheel.yml/badge.svg)](https://github.com/travishathaway/loconym/actions/workflows/wheel.yml)
[![PyPI](https://img.shields.io/pypi/v/loconym)](https://pypi.org/project/loconym/)
[![npm](https://img.shields.io/npm/v/loconym)](https://www.npmjs.com/package/loconym)
[![Docs](https://img.shields.io/badge/docs-travishathaway.github.io%2Floconym-70853C)](https://travishathaway.github.io/loconym/)

Offline geocoding from a single compact SQLite file built from an `.osm.pbf`:

- **reverse**: lat/lon → address (house number, street, suburb, city, state, country)
- **search**: address text → lat/lon, with type-ahead, house numbers and address interpolation

A Python **builder** creates the database; a TypeScript **client** queries it in the browser, either by downloading the
file or by reading only the pages it needs with HTTP range requests. No server, no API keys.

**Documentation: <https://travishathaway.github.io/loconym/>**

```
builder/   Python CLI + reference reader + benchmarks   (PyPI: loconym)
client/    TypeScript API                                (npm: loconym)
examples/  browser-demo: full example app (Vite + MapLibre + Bootstrap, range/fetch, Berlin/Monaco)
           berlin-map: the small demo on the docs home page
docs/      documentation website (Zensical), incl. the format spec: docs/reference/format-spec.md
fixtures/  Geofabrik extracts (git-ignored), golden test vectors (monaco committed, bremen generated)
```

Data © OpenStreetMap contributors (ODbL). License: MIT.

## Install

```sh
pip install loconym              # CLI: loconym build
npm install loconym       # browser client
```

## Usage

```sh
loconym build monaco-latest.osm.pbf -o monaco.sqlite
```

```ts
import { Loconym } from 'loconym';

const geocoder = await Loconym.open({ url: '/data/bremen.sqlite', mode: 'range' }); // or 'fetch'

const r = await geocoder.reverse({ lat: 53.0758, lon: 8.8072 });
// { display_name, address: { house_number, road, suburb, city, state, country }, lat, lon, kind, place_rank, ... }

const hits = await geocoder.search({ q: 'Am Wall 1, Bremen', limit: 5 });
// [{ display_name, lat, lon, housenumber, interpolated?, score, ... }]
const hits2 = await geocoder.search({ street: 'Am Wall', city: 'Bremen' });   // structured
```

- `mode: 'range'` needs a cross-origin-isolated page (`Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp`, for SharedArrayBuffer) and a host that supports HTTP `Range` (and CORS `Range`/`Content-Range` if cross-origin). A lookup
  typically reads a few KB; in our tests 30 queries on Bremen (3.9 MB) read ~136 KB in 29 requests.
- `mode: 'fetch'` downloads the file once; best for small bundled databases.
- `search`/`reverse` throw `CapabilityError` when the database was built without them (`--search none`).

See the [tutorial](https://travishathaway.github.io/loconym/tutorials/first-geocoder/) for a complete walkthrough.

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
pixi run demo-data         # builds the Berlin demo database (needs fixtures/berlin/berlin.osm.pbf)
pixi run demo-dev          # http://localhost:5173
pixi run example-data      # Berlin + Monaco databases for examples/browser-demo
pixi run example-dev       # http://localhost:5173
```

Releases: publishing a GitHub release tagged `py-vX.Y.Z` publishes the CLI to PyPI; one tagged `js-vX.Y.Z` publishes
the client to npm. See [Publish a release](https://travishathaway.github.io/loconym/how-to/release/).

## Status

Early. v0 format, Germany-oriented defaults (street grouping at `admin_level` 8). Measured on Monaco, Bremen and Hessen
(see `docs/reference/spike-notes.md`). Not yet implemented: postcodes, OSM ids, POI queries without a place ("pharmacy near me"), non-Latin normalization, OPFS
driver, scoring beyond token coverage. Germany-scale builds are untested (memory profile is the next task).
