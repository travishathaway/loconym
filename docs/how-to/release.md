# Publish a release

The Python CLI and the TypeScript client are versioned and released independently, each with its own tag prefix:

| Package | Version lives in | Tag | Workflow |
|---|---|---|---|
| `logator` on PyPI | `builder/src/logator/__init__.py` (`__version__`) | `py-vX.Y.Z` | `wheel.yml` |
| `@thath/logator` on npm | `client/package.json` (`version`) | `js-vX.Y.Z` | `npm-publish.yml` |

Both workflows fail early if the tag doesn't match the version in the package.

## One-time setup

### PyPI (trusted publishing)

1. On PyPI, go to **Your account → Publishing → Add a new pending publisher** and enter: project `logator`, owner
   `travishathaway`, repository `logator`, workflow `wheel.yml`, environment `pypi`.
2. In the GitHub repository, create an environment named `pypi` (**Settings → Environments**). You can add required
   reviewers to gate releases.

No API token is needed.

### npm (trusted publishing)

npm only lets you configure a trusted publisher for a package that already exists, so the **first** publish needs a
token:

1. Create a granular access token on npmjs.com with publish rights. Add it as the repository secret `NPM_TOKEN`.
2. Create a GitHub environment named `npm`.
3. Publish the first version (see below).
4. On npmjs.com, open the package's **Settings → Trusted publishing**, add GitHub Actions with repository
   `travishathaway/logator`, workflow `npm-publish.yml` and environment `npm`. Then delete the `NPM_TOKEN` secret.

Packages are published with [provenance](https://docs.npmjs.com/generating-provenance-statements).

### GitHub Pages

In **Settings → Pages**, set **Source** to **GitHub Actions**. `docs.yml` deploys on every push to `main`.

## Release the Python CLI

```sh
# 1. bump __version__ in builder/src/logator/__init__.py, e.g. to 0.1.0, and commit
# 2. tag and push
git tag py-v0.1.0
git push origin py-v0.1.0
```

`wheel.yml` builds the sdist and wheel, tests the wheel on Python 3.11–3.14 (Linux and macOS), and uploads to PyPI.
To check the artifacts locally first:

```sh
pixi run -e release check-dist   # builds into dist/ and runs twine check
```

## Release the TypeScript client

```sh
# 1. bump "version" in client/package.json, e.g. to 0.1.0, and commit
# 2. tag and push
git tag js-v0.1.0
git push origin js-v0.1.0
```

To see exactly what would be published without publishing, run the **npm** workflow manually from the Actions tab
with *dry-run* checked (the default).

## Format compatibility

The database [format version](../reference/format-spec.md#7-versioning) is independent of both package versions.
A client accepts any database with format major version `0`. When you change the format incompatibly, release the
builder and the client together.
