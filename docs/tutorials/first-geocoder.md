# Build your first offline geocoder

In this tutorial you will build a geocoding database for Monaco and query it from a web page, with no server and no
API keys. Along the way you will use both halves of logator: the **Python CLI** that builds databases and the
**TypeScript client** that queries them.

You will need Python 3.11 or newer and Node.js 22 or newer. Plan for about 15 minutes.

## 1. Install the CLI

```sh
pip install logator
logator --help
```

You should see `usage: logator [-h] {build} ...`.

## 2. Download some OpenStreetMap data

logator builds from `.osm.pbf` extracts. [Geofabrik](https://download.geofabrik.de/) publishes them for every
country and region. Monaco is tiny (under 1 MB), which makes it a good first dataset:

```sh
curl -LO https://download.geofabrik.de/europe/monaco-latest.osm.pbf
```

## 3. Build the database

```sh
logator build monaco-latest.osm.pbf -o monaco.sqlite
```

The builder reads the file twice: once for administrative boundaries, once for streets and addresses. Then it writes
the database. The log ends with a summary like:

```text
done: {'size': 110592, 'cells': 56, 'split_markers': 0, 'streets': 343, 'housenumbers': 452, 'admins': 11}
```

So you have 343 streets, 452 addresses and 11 administrative areas in about 108 KiB. That file is everything the
browser needs.

## 4. Create a web page

Make a new Vite project and add the client:

```sh
npm create vite@latest my-geocoder -- --template vanilla-ts
cd my-geocoder
npm install
npm install @thath/logator
```

Put the database where Vite serves static files:

```sh
mkdir -p public/data
cp ../monaco.sqlite public/data/
```

The client runs SQLite compiled to WebAssembly, and that package loads its own `.wasm` file. Tell Vite not to
pre-bundle it. Create `vite.config.ts`:

```ts title="vite.config.ts"
import { defineConfig } from 'vite';

export default defineConfig({
  optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm'] },
});
```

Replace `index.html` with a search box and an output area:

```html title="index.html"
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>My geocoder</title>
  </head>
  <body>
    <input id="q" placeholder="Search Monaco, e.g. Avenue des Papalins 9" size="40" />
    <pre id="out">Loading…</pre>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

Replace `src/main.ts`:

```ts title="src/main.ts"
import { Logator } from '@thath/logator';

const out = document.getElementById('out')!;
const input = document.getElementById('q') as HTMLInputElement;

// 'fetch' mode downloads the whole file once, which suits a small database like this one.
const gator = await Logator.open({ url: '/data/monaco.sqlite', mode: 'fetch' });

// Reverse geocoding: coordinates -> address
const place = await gator.reverse({ lat: 43.7384, lon: 7.4246 });
out.textContent = `Reverse: ${place?.display_name}\n`;

// Search: address -> coordinates, on every keystroke
input.addEventListener('input', async () => {
  const hits = await gator.search({ q: input.value, limit: 5 });
  out.textContent = hits.map((h) => `${h.display_name}  (${h.lat.toFixed(5)}, ${h.lon.toFixed(5)})`).join('\n');
});
```

## 5. Run it

```sh
npm run dev
```

Open the URL that Vite prints (usually <http://localhost:5173>). The page shows:

```text
Reverse: Avenue des Papalins 9, Monte-Carlo, Monaco
```

Now type `Avenue des Papalins 9, Monaco` into the box. The first result is positioned on that house:

```text
Avenue des Papalins 9, Monaco  (43.73852, 7.42419)
```

Try typing only `grim`. Search matches prefixes of the last word, so you get `Rue Grimaldi`,
`Grimaldi Forum/Villa Sauber` and others while you type.

## What you did

- You built a self-contained geocoding database from raw OpenStreetMap data with `logator build`.
- You queried it in the browser with `Logator.open`, `reverse` and `search`. Nothing left your machine except the
  page's request for `monaco.sqlite`.

## Next steps

- For larger regions, don't download the whole file: [serve it with HTTP range requests](../how-to/range-requests.md).
- Turn the search box into proper [address autocomplete](../how-to/autocomplete.md).
- Look up every option in the [TypeScript API reference](../reference/typescript-api.md).
- Read [how logator works](../explanation/architecture.md).
