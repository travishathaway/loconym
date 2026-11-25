# loconym example app

A complete browser app built on [`loconym`](../../client): search addresses with type-ahead, click the map
to reverse geocode, and switch between datasets (Berlin, Monaco) and data retrieval modes (HTTP range requests or
a full download).

Built with [Vite](https://vite.dev), [MapLibre GL JS](https://maplibre.org) with the
[OpenFreeMap](https://openfreemap.org) Bright basemap, and [Bootstrap](https://getbootstrap.com).

**Setup and walkthrough: [Run the example app](https://travishathaway.github.io/loconym/how-to/run-the-example/)**

Quick start, from the repository root:

```sh
curl -L --create-dirs -o fixtures/berlin/berlin.osm.pbf https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
pixi run example-data      # Berlin + Monaco databases into public/data/
pixi run example-dev       # http://localhost:5173
```

A smaller, search-only demo runs on the documentation site's home page. Its source is in [`../berlin-map`](../berlin-map).

Data © OpenStreetMap contributors (ODbL). License: MIT.
