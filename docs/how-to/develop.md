# Set up a development environment and run the tests

The repository uses [pixi](https://pixi.sh) to manage Python, Node.js and pnpm. All dependencies come from
conda-forge.

## Set up

```sh
git clone https://github.com/travishathaway/loconym.git
cd loconym
pixi install
```

`pixi install` creates the `default` environment, which contains everything. The `pixi.toml` groups dependencies
into features:

| Feature | Contents | Used for |
|---|---|---|
| *(default)* | `python`, `pyosmium`, `shapely`, `apsw`, `osmium-tool`, plus `loconym` (editable) | Runtime of the Python package |
| `dev` | `pytest`, `ruff` | Python tests and linting |
| `js` | `nodejs`, `pnpm` | TypeScript client and browser demo |
| `docs` | `zensical` | This website |
| `release` | `python-build`, `twine` | Building the sdist and wheel |

CI also uses the lean `docs`, `js` and `release` environments (`pixi run -e docs …`).

## Get test data

The Python build test needs the Monaco extract, and the client's Bremen tests need Bremen golden vectors:

```sh
curl -L --create-dirs -o fixtures/monaco/monaco.osm.pbf https://download.geofabrik.de/europe/monaco-latest.osm.pbf
curl -L --create-dirs -o fixtures/bremen/bremen.osm.pbf https://download.geofabrik.de/europe/germany/bremen-latest.osm.pbf
pixi run golden-data      # writes fixtures/golden/bremen.{sqlite,golden.json}
```

Tests that need a missing fixture are skipped, not failed. The Monaco golden vectors
(`fixtures/golden/monaco.*`) are committed. Regenerate them with `pixi run golden-monaco` only when the format or
the reference reader changes on purpose.

## Run the tests

```sh
pixi run test             # everything: Python (pytest) + TypeScript (vitest)
pixi run test-builder     # Python only
pixi run client-test      # TypeScript only: decoders and queries vs the Python reference, fetch and range modes
pixi run lint             # ruff
pixi run demo-build       # type-checks and builds the client and the browser demo
```

The client tests are parity tests. The Python builder writes golden vectors (`loconym-golden`), and the TypeScript
client must reproduce the Python reference reader's results for every case.

## Work on the docs

```sh
pixi run docs-serve       # http://localhost:8000, live reload
pixi run docs-build       # static site in site/
```

Pages live in `docs/` and follow [Diátaxis](https://diataxis.fr/). Put each new page in the right section and add
it to `nav` in `zensical.toml`.

## Run the demos

The repository has two browser demos. The full example app (`examples/browser-demo`) is covered in
[Run the example app](run-the-example.md). The Berlin map demo (`examples/berlin-map`, MapLibre + the OpenFreeMap Bright basemap) is embedded on the home page
of this website. It opens the database in `fetch` mode, so it runs on GitHub Pages without cross-origin isolation.

```sh
curl -L --create-dirs -o fixtures/berlin/berlin.osm.pbf https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
pixi run demo-data        # builds examples/berlin-map/public/data/berlin.sqlite
pixi run demo-dev         # http://localhost:5173
```

`pixi run docs-serve` doesn't include the demo, so the home page embed is empty there. To see the site as GitHub Pages
serves it, build both and serve `site/`:

```sh
pixi run pages-build      # docs into site/, demo into site/demo/
python -m http.server -d site
```

## Continuous integration

| Workflow | Runs | Does |
|---|---|---|
| `ci.yml` | push to `main`, PRs | Lint, Python tests, Bremen golden vectors, client tests, demo build on Linux and macOS |
| `wheel.yml` | push to `main`, PRs, published `py-v*` releases | Builds the sdist and wheel, installs the wheel with plain pip on Python 3.11–3.14 and runs the tests against it; on a release, publishes to PyPI and attaches the files |
| `npm-publish.yml` | published `js-v*` releases, manual (dry run) | Tests and builds the client, stages it on npm for approval, and attaches the tarball to the release |
| `docs.yml` | push to `main`, PRs | Builds the Berlin database, this site and the demo; deploys them to GitHub Pages from `main` |
| `cache-warm.yml` | every 5 days, manual | Restores the cached Geofabrik extracts so GitHub doesn't evict them after 7 days unused; on a miss, downloads and caches them |

Workflows get Geofabrik extracts through `.github/actions/osm-extract`, which keeps one Actions cache entry per
extract (`osm-<name>-v1`) and downloads from Geofabrik only on a cache miss. The cached files are never refreshed
on their own. To pick up newer OpenStreetMap data, bump the action's `version` default, then run *Keep OSM caches
warm* on `main` to download each extract once.