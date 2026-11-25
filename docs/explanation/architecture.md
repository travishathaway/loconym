# How loconym works

loconym splits geocoding into a **build** step that runs once on your machine and a **query** step that runs in your
users' browsers. One SQLite file connects the two.

```text
 .osm.pbf ──► loconym build (Python) ──► region.sqlite ──► static host / CDN ──► loconym (browser)
                                            │
                                            └── the only contract: docs/reference/format-spec.md
```

## Why a single SQLite file

A geocoder usually needs a server: Nominatim, Photon, or a hosted API. loconym aims at the cases where a server is
unwanted: offline apps, privacy-sensitive apps, static sites, and prototypes without a backend.

SQLite fits this well:

- **It is one file.** You can version it, put it on a CDN, or bundle it into an app.
- **Its B-trees are already a good on-disk index.** Every lookup in loconym is a keyed point read or a short range
  scan, so a query touches only a few 4 KiB pages. That makes it possible to read the file *over HTTP*, a page at a
  time (see [Range mode vs fetch mode](range-vs-fetch.md)).
- **It runs everywhere.** The official WebAssembly build runs in browsers and Node, and Python ships with it.

The format forbids table scans at query time. Each table is keyed for exactly the lookups the client makes.

## The builder

`loconym build` reads the extract in two passes with pyosmium:

1. **Administrative boundaries.** Boundary relations are assembled into polygons and nested into a hierarchy
   (country → state → … → city → suburb).
2. **Streets, addresses and interpolation lines.** Named ways are grouped into *streets*: the same normalized name
   inside the same city-level area (`--city-level`, default 8). Address points are attached to their street.
   Interpolation lines get their street from their endpoint addresses.

Intermediate data is spilled to a scratch SQLite database, so memory scales with the number of streets and admin
areas rather than with the size of the input.

Then it writes the tables:

- **`cell`: the spatial index for reverse geocoding.** The world is cut into web-mercator tiles at zoom 16 (about
  600 m across at mid latitudes). Each tile's row holds a compact binary blob with everything inside it: clipped
  admin polygons, clipped street polylines, address points and interpolation segments. A reverse lookup is one
  key lookup for one row. Tiles with no features but inside an admin area are merged into one coarser row. Tiles
  that would be too big are split into four children.
- **`term`: the inverted index for search.** It maps each normalized token to the streets that contain it, per city,
  and to the admin areas that contain it.
- **`housenumber`: house-number positions per street**, for search.
- **`street` and `admin`**: names and hierarchy.

All coordinates are stored as small integer deltas (1e-6° ≈ 0.1 m), varint-encoded. That is why a city of 150,000
addresses fits in about 4 MB.

## The client

`loconym` is a TypeScript port of the Python reference reader (`loconym.reader`). It runs the same algorithms
over a minimal `Db` interface with two implementations:

- **fetch**: download the file and open it in memory with the official SQLite WebAssembly build.
- **range**: run SQLite in a worker with an HTTP virtual file system that turns page reads into `Range` requests
  ([sqlite-wasm-http](https://github.com/mmomtchev/sqlite-wasm-http)).

## How the two halves stay in agreement

The builder and the client are written in different languages but must agree to the bit on binary encodings and
text normalization. The project enforces this with **golden vectors**. `loconym-golden` builds a database with
Python and records the expected output of every decoder, plus hundreds of reverse and search queries computed by
the Python reader. The TypeScript test suite must reproduce all of them, in both fetch and range mode. CI runs this
on every change.

## Where the name comes from

**loconym** is *local* + *toponym*. A toponym is a place name: a street, a suburb, a city. loconym turns
coordinates into toponyms and toponyms into coordinates, locally, from a file you host yourself.

## What's up with the alligator?

The project was originally conceived of as "logator" (locator alligator 😛), but the oringal author quickly realized the
web was awash in gator named companies and projects. Instead, loconym was chosen (see above), but the alligator
stayed. He still is and always will be the locator alligator.

(Strictly speaking the artwork started out as the Noto Emoji crocodile. He doesn't like to talk about it. See
[Credits](../credits.md).)
