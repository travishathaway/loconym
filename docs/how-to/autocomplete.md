# Build address autocomplete

`search` matches the **last word as a prefix** once it has at least 3 characters, so you can call it on every
keystroke. This guide adds the parts a real search box needs: debouncing, discarding stale responses, and moving the
map to the chosen result.

## Search as the user types

```ts
import { Logator, type SearchResult } from '@thath/logator';

const gator = await Logator.open({ url: '/data/bremen.sqlite', mode: 'range' });
const input = document.querySelector<HTMLInputElement>('#q')!;
const list = document.querySelector<HTMLUListElement>('#results')!;

let seq = 0;      // id of the most recent request
let timer: number | undefined;

input.addEventListener('input', () => {
  clearTimeout(timer);
  timer = window.setTimeout(async () => {
    const mine = ++seq;
    const hits = await gator.search({ q: input.value, limit: 8 });
    if (mine !== seq) return; // a newer keystroke already started another search
    render(hits);
  }, 120);
});

function render(hits: SearchResult[]) {
  list.replaceChildren(
    ...hits.map((h) => {
      const li = document.createElement('li');
      li.textContent = h.display_name;
      li.onclick = () => choose(h);
      return li;
    }),
  );
}

function choose(hit: SearchResult) {
  // hit.lat / hit.lon is the house if a number was found, otherwise a point on the street
  console.log(hit.display_name, hit.lat, hit.lon, hit.interpolated ? '(interpolated)' : '');
}
```

In range mode each search costs a few round trips. The debounce keeps fast typists from queueing requests, and the
sequence number makes sure an old, slow response never overwrites a newer one.

## Narrow results to a city

What follows the **last comma** is treated as the place:

```ts
await gator.search('Am Wall 1, Bremen');
```

If your UI has separate fields, pass them as structured parameters. The comma splitting is then skipped:

```ts
await gator.search({ street: 'Am Wall 1', city: 'Bremen' });
```

## Tune prefix matching

- `minPrefix` (default `3`): the minimum length before the last word is matched as a prefix. A shorter last word
  only matches whole words. Raising it reduces work on very large databases, where short prefixes in big cities
  match many streets.
- `limit` (default `5`): the number of results returned.

```ts
await gator.search({ q: input.value, limit: 10, minPrefix: 4 });
```

## Show house numbers

When the street part contains a house number (`Am Wall 12a` or `12a Am Wall`), the top results are positioned on
that address and `housenumber` is set. If the number only falls on an interpolation line, `interpolated` is `true`.
If the number isn't found, the result still points at the street and `housenumber` is `null`, so you can show the
street and say the number is unknown.

See [How search and reverse geocoding match](../explanation/matching.md) for the full rules.
