# Command line

The `logator` Python package installs three commands.

## `logator build`

Build a database from an OpenStreetMap `.osm.pbf` file.

```text
logator build [-h] -o OUTPUT [--language LANGUAGE] [--city-level CITY_LEVEL]
              [--search {none,full}] [--max-leaf-bytes MAX_LEAF_BYTES] [--keep-scratch]
              [--prefilter {auto,always,never}] [--node-index {auto,memory,disk}]
              input
```

| Argument | Default | Description |
|---|---|---|
| `input` | *(required)* | Path to the `.osm.pbf` extract. |
| `-o`, `--output` | *(required)* | Path of the database to write. An existing file is replaced. |
| `--search {none,full}` | `full` | `none` leaves out the search index (`term` and `housenumber` tables) to make a smaller, reverse-only database. See [Build a smaller, reverse-only database](../how-to/reverse-only.md). |
| `--city-level N` | `8` | OSM `admin_level` that streets are grouped under. Search narrows by these areas, and a street name is unique within one. `8` is the municipality level in Germany. |
| `--language CODE` | `en` | Recorded in the database's `meta.language`. In v0 it doesn't change which name tags are used. |
| `--max-leaf-bytes N` | `16384` | Largest encoded size of one z16 cell. Larger cells are split into four children. |
| `--prefilter {auto,always,never}` | `auto` | Pre-filter the input with osmium-tool to bound memory. `auto` pre-filters inputs larger than 400 MiB if the `osmium` binary is found. `always` fails without osmium-tool. See [Build a database from a large extract](../how-to/large-extracts.md). |
| `--node-index {auto,memory,disk}` | `auto` | Where node locations are cached while reading. `auto` uses disk for inputs larger than 400 MiB. |
| `--keep-scratch` | off | Keep the temporary scratch directory (created next to the output) for debugging. |

Progress goes to stderr. The last line summarizes the result:

```text
done: {'size': 110592, 'cells': 56, 'split_markers': 0, 'streets': 343, 'housenumbers': 452, 'admins': 11}
```

## `logator-bench`

Measure a database's correctness and query cost with the Python reference reader. See
[Check a database's quality and query cost](../how-to/benchmark.md) for how to read the output.

```text
logator-bench [-h] [--n N] [--seed SEED] db
```

| Argument | Default | Description |
|---|---|---|
| `db` | *(required)* | Database to benchmark. |
| `--n` | `300` | Number of sampled addresses per test. |
| `--seed` | `7` | Random seed for sampling. |

## `logator-golden`

Build a database and write golden test vectors that the TypeScript client's parity tests check against. This is a
development tool. See [Set up a development environment](../how-to/develop.md).

```text
logator-golden [-h] name pbf outdir
```

Writes `OUTDIR/NAME.sqlite` and `OUTDIR/NAME.golden.json`. The JSON holds normalizer cases, cell keys, encoded and
decoded cell leaves, house-number blobs, postings, and expected `reverse` and `search` results.
