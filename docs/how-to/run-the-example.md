# Run the example app

The repository contains a complete browser app built on the TypeScript client:
[`examples/browser-demo`](https://github.com/travishathaway/logator/tree/main/examples/browser-demo). It shows
address search with type-ahead, reverse geocoding on click, and both ways of reading the database: HTTP range
requests and a full download. It's a good starting point for your own app.

It uses [Vite](https://vite.dev), [MapLibre GL JS](https://maplibre.org) with the
[OpenFreeMap](https://openfreemap.org) Bright basemap, and [Bootstrap](https://getbootstrap.com).

## Prerequisites

- A clone of the repository and [pixi](https://pixi.sh). `pixi install` provides Python, Node.js and pnpm. See
  [Set up a development environment](develop.md).
- About 100 MB of disk space for the Berlin extract.

## 1. Build the databases

Download the Berlin extract from Geofabrik, then build the databases:

```sh
curl -L --create-dirs -o fixtures/berlin/berlin.osm.pbf \
  https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
pixi run example-data
```

`example-data` runs `logator build` on the extract, which takes about a minute. It then copies `berlin.sqlite`
(about 12 MB) and the committed `monaco.sqlite` fixture into `examples/browser-demo/public/data/`. Any database
built with `logator build` works: put it in that folder and add an `<option>` to the dataset selector in
`index.html`.

## 2. Start the app

```sh
pixi run example-dev
```

Open <http://localhost:5173>. The task builds the client first, then starts the Vite dev server.

## 3. Try it

- **Search**: type an address, e.g. `Unter den Linden 77`. Results appear as you type. Click one to fly to it.
- **Reverse geocode**: click anywhere inside the dashed outline of the database's coverage.
- **Dataset**: switch between Berlin and Monaco.
- **Data retrieval**:
    - *HTTP range requests* reads only the database pages each query needs.
    - *Full download* fetches the whole file once, then answers every query from memory.

To watch the difference, open the browser's developer tools on the Network tab. In range mode each query makes a
handful of 4 KiB `Range` requests to the `.sqlite` file. A Berlin search reads about 40 KiB of the 12 MB file. In fetch mode there's one request
for the whole file. For the trade-offs, see [Range mode vs fetch mode](../explanation/range-vs-fetch.md).

## How it handles range mode

Range mode needs a cross-origin-isolated page. `examples/browser-demo/vite.config.ts` does two things for that:

- It sends `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` from the dev
  server and from `vite preview`.
- It loads the workers of `sqlite-wasm-http` as module workers.

The map works under these headers because MapLibre fetches every resource (style, tiles, glyphs, sprites) with CORS.

If the page isn't isolated, the app disables the range option and uses fetch mode. That happens, for example,
behind a host that strips the headers.

## Build and deploy

```sh
pixi run example-build    # type-checks, then builds into examples/browser-demo/dist/
```

`dist/` is a static site. Serve it from a host that supports HTTP `Range` and lets you set the two isolation
headers. [Serve a database with HTTP range requests](range-requests.md) has configurations for nginx, Netlify and
Cloudflare Pages. GitHub Pages can't set headers, so there the app falls back to fetch mode. The demo on
[this site's home page](../index.md) uses fetch mode for the same reason.
