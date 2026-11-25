# Build a smaller, reverse-only database

If your application only turns coordinates into addresses, drop the search index:

```sh
loconym build bremen-latest.osm.pbf -o bremen-reverse.sqlite --search none
```

This leaves the `term` and `housenumber` tables empty. On Bremen, the `housenumber` table alone is about 31% of the
file. Street names are kept, because reverse geocoding needs them.

The database's `capabilities` no longer include `search`. Check before calling:

```ts
import { CapabilityError, Loconym } from 'loconym';

const geocoder = await Loconym.open({ url: '/data/bremen-reverse.sqlite', mode: 'range' });

geocoder.capabilities;                       // ['reverse']
await geocoder.reverse({ lat: 53.0758, lon: 8.8072 });

try {
  await geocoder.search('Am Wall');
} catch (e) {
  if (e instanceof CapabilityError) console.log('this database has no search index');
}
```
