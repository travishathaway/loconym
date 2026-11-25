# Range mode vs fetch mode

The client can read the same database file in two ways. Both return identical results (the test suite checks
this), so the choice is only about cost and deployment.

## Fetch mode

`mode: 'fetch'` downloads the whole file with one request and opens it in memory with the official SQLite
WebAssembly build.

- **Cost:** the whole file, once. After that every query is local and fast.
- **Requirements:** none beyond a normal static host.
- **Runtime size:** about 0.9 MB of WebAssembly (0.4 MB gzipped).

## Range mode

`mode: 'range'` opens the file over HTTP and fetches only the 4 KiB pages each query touches, with a page cache
shared across queries.

- **Cost:** a few KiB per query. Opening Bremen (3.9 MB) took 13 KB in 3 requests, and 30 mixed queries read
  136 KB in 29 requests, 3.5% of the file. A state-sized file (Hessen, 51 MiB) still reads only around 4 pages per
  reverse lookup once warm.
- **Requirements:** a host that supports `Range` requests, and a
  [cross-origin-isolated](../how-to/range-requests.md) page, because SQLite runs in a worker that uses
  `SharedArrayBuffer`.
- **Runtime size:** sqlite-wasm-http bundles its own SQLite build, about 3.6 MB of WebAssembly (1.7 MB gzipped).
- **Latency:** each query may need a few round trips. That's fine on a CDN, noticeable on a slow mobile connection.

## Which to choose

The runtime sizes give a rule of thumb. Range mode costs about 1.3 MB more (gzipped) to load, so **fetch mode wins
for databases up to a few MB**. A city-sized database downloads about as fast as the range-mode runtime.

| Situation | Use |
|---|---|
| Small database (a city), or the app is used offline after the first load | fetch |
| Database too large to download (a state, a country) | range |
| You can't set COOP/COEP headers (e.g. GitHub Pages) | fetch |
| Many lookups per session over a large area | range, with a larger `range.cacheSizeKiB` |

You can decide at runtime:

```ts
const mode = self.crossOriginIsolated && sizeMB > 5 ? 'range' : 'fetch';
```

## Why pages and not a custom API

Because every logator query is a short B-tree walk, "SQLite over HTTP" behaves like a purpose-built geocoding API
without running one. The CDN serves byte ranges of an immutable file, which caches perfectly. The cost is that the
file layout matters a lot: rows that are read together are stored next to each other (for example, street ids are
assigned in city-then-name order). That is why the [format spec](../reference/format-spec.md) is strict about it.
