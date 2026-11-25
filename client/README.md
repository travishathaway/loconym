# loconym

Offline reverse and forward geocoding in the browser, from a single compact SQLite file built with the
[`loconym`](https://pypi.org/project/loconym/) Python CLI. No server, no API keys.

```sh
npm install loconym
```

```ts
import { Loconym } from 'loconym';

const geocoder = await Loconym.open({ url: '/data/monaco.sqlite', mode: 'range' }); // or 'fetch'

const place = await geocoder.reverse({ lat: 43.7384, lon: 7.4246 });
// place.display_name === 'Avenue des Papalins 9, Monte-Carlo, Monaco'

const hits = await geocoder.search('Avenue des Papalins 9, Monaco');
// [{ display_name: 'Avenue des Papalins 9, Monaco', lat: 43.7385194, lon: 7.4241888, ... }]
```

- `mode: 'range'` reads only the database pages a query needs over HTTP `Range` requests. It needs a
  cross-origin-isolated page (`Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp`).
- `mode: 'fetch'` downloads the file once; best for small, bundled databases.

Documentation: <https://travishathaway.github.io/loconym/>

Data © OpenStreetMap contributors (ODbL). License: MIT.
