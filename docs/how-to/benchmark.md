# Check a database's quality and query cost

`logator-bench` samples addresses from a built database, queries them back with the Python reference reader, and
reports how often the right answer comes back and how many 4 KiB pages each query reads. Use it after changing build
options, or to estimate range-mode traffic before you deploy.

```sh
logator-bench monaco.sqlite --n 50
```

```text
reverse@address n=50: street-ok=100.0% number-ok=100.0% pages cold avg=6.9 p95=7 max=7 | warm avg=1.0 p95=1 max=1
search 'street N, city' n=50: top1=94.0% top5=94.0% number-located=94.0% pages cold avg=9.7 p95=10 max=11
search type-ahead n=50: top5=56.0% pages cold avg=7.6 p95=9 max=9
```

## Read the output

| Line | What it checks |
|---|---|
| `reverse@address` | Reverse geocoding exactly at a known address point returns that street (`street-ok`) and house number (`number-ok`). |
| `search 'street N, city'` | Searching `"<street> <number>, <city>"` finds the street first (`top1`) or in the top 5 (`top5`), and positions the house number (`number-located`). |
| `search type-ahead` | Half of the street name plus the city finds the street in the top 5. |
| `pages cold` | Pages read with a fresh connection per query: an upper bound for the first query in range mode. |
| `pages warm` | Pages read with a 256 KiB cache kept across queries: closer to an open browser session. |

Multiply page counts by 4 KiB to estimate bytes per query in [range mode](range-requests.md).

## Options

- `--n` (default `300`): addresses sampled per test.
- `--seed` (default `7`): random seed. Keep it fixed to compare two builds.
