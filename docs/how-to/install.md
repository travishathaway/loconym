# Install the CLI and the client

## Python CLI

=== "pip"

    ```sh
    pip install loconym
    ```

=== "uv"

    ```sh
    uv tool install loconym
    ```

=== "pixi / conda"

    The dependencies are on conda-forge. Install them, then the CLI:

    ```sh
    pixi init my-project && cd my-project
    pixi add python pyosmium shapely apsw osmium-tool
    pixi add --pypi loconym
    ```

The CLI needs Python 3.11 or newer. It depends on [pyosmium](https://osmcode.org/pyosmium/) (PyPI name `osmium`),
[Shapely](https://shapely.readthedocs.io/) and [APSW](https://rogerbinns.github.io/apsw/). All three ship binary
wheels for Linux, macOS and Windows.

Check the install:

```sh
loconym --help
```

### Optional: osmium-tool

For extracts larger than about 400 MiB, the builder can pre-filter the input with the
[osmium-tool](https://osmcode.org/osmium-tool/) `osmium` binary to keep memory bounded (see
[Build a database from a large extract](large-extracts.md)). It is not on PyPI. Install it with your system package
manager or conda:

```sh
conda install -c conda-forge osmium-tool   # or: apt install osmium-tool / brew install osmium-tool
```

## TypeScript client

```sh
npm install loconym     # or: pnpm add loconym / yarn add loconym
```

The package is ESM-only and ships its own type declarations.

### Bundler setup

The client loads SQLite's WebAssembly build at runtime. With Vite, exclude the SQLite packages from dependency
pre-bundling:

```ts title="vite.config.ts"
import { defineConfig } from 'vite';

export default defineConfig({
  optimizeDeps: { exclude: ['@sqlite.org/sqlite-wasm', 'sqlite-wasm-http'] },
  worker: { format: 'es' },
});
```

To use [range mode](range-requests.md), the page must also be cross-origin isolated. That guide shows the extra
Vite settings.
