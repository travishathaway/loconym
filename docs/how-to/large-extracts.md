# Build a database from a large extract

For state- or country-sized extracts (hundreds of MB and up), memory is the constraint, not CPU. This guide shows
the options that keep a large build within your machine's memory.

## Reference points

Measured with `loconym build` (see [Measurements and design notes](../reference/spike-notes.md#real-builder-results-2026-11-24)):

| Extract | Input | Output | Build time | Peak memory |
|---|---|---|---|---|
| Bremen | 21 MB | 3.75 MiB | 13 s | 219 MB |
| Hessen | 332 MB | 51.2 MiB | 311 s | 982 MB |

Memory grows with the number of **streets and admin areas**, not addresses. Germany-scale builds haven't been
measured yet.

## 1. Install osmium-tool

pyosmium's node-location cache stores every node of the file it reads. Pre-filtering with `osmium tags-filter`
first writes two much smaller files that contain only what the builder needs:

- `boundaries.pbf`: administrative boundary relations
- `features.pbf`: highways, house numbers and interpolation ways

```sh
conda install -c conda-forge osmium-tool   # or: apt install osmium-tool / brew install osmium-tool
osmium --version
```

## 2. Build

```sh
loconym build germany-latest.osm.pbf -o germany.sqlite
```

For inputs larger than 400 MiB, the defaults already:

- pre-filter with osmium-tool if the `osmium` binary is on your `PATH` (`--prefilter auto`), and
- keep the node-location index in a file on disk instead of in memory (`--node-index auto`).

To force either behaviour regardless of size:

```sh
loconym build input.osm.pbf -o out.sqlite --prefilter always --node-index disk
```

`--prefilter always` fails with an error if osmium-tool isn't installed.

## 3. Give it scratch space

The builder writes its scratch database and the on-disk node index to a temporary directory **next to the output
file**. Put the output on a disk with free space of at least several times the input size. The scratch files are
deleted when the build finishes, unless you pass `--keep-scratch`.

## Troubleshooting

- **The process is killed (out of memory)**: make sure pre-filtering actually ran. The log starts with
  `prefilter: osmium tags-filter …`. If it doesn't, install osmium-tool or pass `--prefilter always`.
- **The build is slow on a laptop**: the disk-backed node index trades speed for memory. If you have the RAM, use
  `--node-index memory`.
