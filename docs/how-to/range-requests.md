# Serve a database with HTTP range requests

In `range` mode the client reads only the database pages that each query touches. A typical lookup reads a few KiB,
whatever the file size. In the test suite, 30 queries against Bremen (3.9 MB) read about 136 KB in 29 requests. Use
range mode when the database is too large to download up front. For the trade-offs, see
[Range mode vs fetch mode](../explanation/range-vs-fetch.md).

Range mode has two requirements:

1. **The page must be cross-origin isolated.** SQLite runs in a worker that shares memory with the page
   (`SharedArrayBuffer`), and browsers only allow that on isolated pages.
2. **The server hosting the `.sqlite` file must support HTTP `Range` requests.** Nearly all static hosts and CDNs do.

## 1. Make the page cross-origin isolated

Serve the **HTML page** with these two response headers:

```http
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

With `require-corp`, every cross-origin resource the page loads (map tiles, fonts, images) must be served with CORS
or `Cross-Origin-Resource-Policy: cross-origin`. For Leaflet tiles, set `crossOrigin: true` on the tile layer.

You can check isolation in the browser console: `self.crossOriginIsolated` must be `true`.

=== "Vite"

    ```ts title="vite.config.ts"
    import { defineConfig, type Plugin } from 'vite';

    const isolation = {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    };

    // sqlite-wasm-http starts its workers as classic workers, but they are ES modules.
    // The Vite dev server serves them as-is, so request module workers explicitly.
    const moduleWorkers: Plugin = {
      name: 'sqlite-wasm-http-module-workers',
      enforce: 'pre',
      transform(code, id) {
        if (!/sqlite-wasm-http[\\/].*dist[\\/]index\.js/.test(id)) return null;
        return code.replace(/new Worker\(new URL\('(\.\/[\w-]+\.js)', import\.meta\.url\)\)/g,
          "new Worker(new URL('$1', import.meta.url), { type: 'module' })");
      },
    };

    export default defineConfig({
      plugins: [moduleWorkers],
      server: { headers: isolation },
      preview: { headers: isolation },
      optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm', 'sqlite-wasm-http'] },
      worker: { format: 'es' },
    });
    ```

    This is the configuration used by `examples/browser-demo` in the repository.

=== "nginx"

    ```nginx
    location / {
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Cross-Origin-Embedder-Policy "require-corp" always;
    }
    ```

=== "Netlify / Cloudflare Pages"

    ```text title="_headers"
    /*
      Cross-Origin-Opener-Policy: same-origin
      Cross-Origin-Embedder-Policy: require-corp
    ```

!!! note "GitHub Pages"

    GitHub Pages can't set custom response headers, so it can't make a page cross-origin isolated. Host the page
    elsewhere, or use `fetch` mode there.

## 2. Host the database file

Put the `.sqlite` file on any static host that answers `Range: bytes=…` requests with `206 Partial Content`. Check
with curl:

```sh
curl -sI -H 'Range: bytes=0-99' https://example.com/data/bremen.sqlite | head -1
# HTTP/2 206
```

If the file is on a **different origin** from the page, the file's host must also send CORS headers that allow the
`Range` request header and expose the range response headers:

```http
Access-Control-Allow-Origin: https://your-site.example
Access-Control-Allow-Headers: Range
Access-Control-Expose-Headers: Content-Range, Content-Length, Accept-Ranges
```

Serve the file **uncompressed**. A whole-file `Content-Encoding` breaks byte offsets. Let the CDN apply compression
to the page and scripts only.

## 3. Open it in range mode

```ts
import { Logator } from '@thath/logator';

const gator = await Logator.open({
  url: 'https://example.com/data/bremen.sqlite',
  mode: 'range',
  range: { cacheSizeKiB: 4096 }, // optional, see the reference
});
```

If the page isn't isolated, `Logator.open` throws an error that names the two headers. You can fall back to fetch
mode:

```ts
const mode = self.crossOriginIsolated ? 'range' : 'fetch';
const gator = await Logator.open({ url, mode });
```

See [`OpenOptions`](../reference/typescript-api.md#openoptions) for the tuning options.
