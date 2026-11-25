# @thath/logator

Offline reverse and forward geocoding in the browser, from a single compact SQLite file built with the
[`logator`](https://pypi.org/project/logator/) Python CLI. No server, no API keys.

```sh
npm install @thath/logator
```

```ts
import { Logator } from '@thath/logator';

const gator = await Logator.open({ url: '/data/monaco.sqlite', mode: 'range' }); // or 'fetch'

const place = await gator.reverse({ lat: 43.7384, lon: 7.4246 });
// place.display_name === 'Avenue des Papalins 9, Monte-Carlo, Monaco'

const hits = await gator.search('Avenue des Papalins 9, Monaco');
// [{ display_name: 'Avenue des Papalins 9, Monaco', lat: 43.7385194, lon: 7.4241888, ... }]
```

- `mode: 'range'` reads only the database pages a query needs over HTTP `Range` requests. It needs a
  cross-origin-isolated page (`Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp`).
- `mode: 'fetch'` downloads the file once; best for small, bundled databases.

Documentation: <https://travishathaway.github.io/logator/>

Data © OpenStreetMap contributors (ODbL). License: GPL-3.0-or-later.
