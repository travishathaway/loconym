# Publish a release

Releases are made by publishing a [GitHub release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
The Python CLI and the TypeScript client are versioned and released independently; the release's tag prefix decides
which package it publishes:

| Package | Version lives in | Release tag | Workflow |
|---|---|---|---|
| `loconym` on PyPI | `builder/src/loconym/__init__.py` (`__version__`) | `py-vX.Y.Z` | `wheel.yml` |
| `loconym` on npm | `client/package.json` (`version`) | `js-vX.Y.Z` | `npm-publish.yml` |

Both workflows fail early if the tag doesn't match the version in the package. Once the package is published, the
built files (sdist and wheel, or the npm tarball) are attached to the GitHub release.

## Release the Python CLI

1. Bump `__version__` in `builder/src/loconym/__init__.py`, e.g. to `0.1.0`, and merge the change to `main`.
2. Create and publish a release whose tag is `py-v0.1.0`, targeting `main`. In the web UI: **Releases → Draft a new
   release**, type the new tag name, and choose **Publish release**. Or with the GitHub CLI:

    ```sh
    gh release create py-v0.1.0 --target main --title "loconym 0.1.0 (Python)" --generate-notes
    ```

`wheel.yml` builds the sdist and wheel, tests the wheel on Python 3.11–3.14 (Linux and macOS), uploads to PyPI and
attaches both files to the release. To check the artifacts locally first:

```sh
pixi run -e release check-dist   # builds into dist/ and runs twine check
```

For a pre-release, use a pre-release version such as `0.2.0rc1` (tag `py-v0.2.0rc1`). PyPI marks it as a
pre-release, so `pip install loconym` keeps installing the latest stable version.

## Release the TypeScript client

1. Bump `"version"` in `client/package.json`, e.g. to `0.1.0`, and merge the change to `main`. The version must be
   new: the bootstrap version you published by hand can't be released again.
2. Create and publish a release whose tag is `js-v0.1.0`, targeting `main`, in the web UI or with:

    ```sh
    gh release create js-v0.1.0 --target main --title "loconym 0.1.0 (TypeScript)" --generate-notes
    ```

    `npm-publish.yml` tests and builds the client, **stages** it on npm and attaches the package tarball to the
    release. The run's summary shows the staged version.

3. Approve the staged version. It isn't installable until you do. On npmjs.com, open **loconym → Staged Packages**
   and approve it (2FA required), or from the command line:

    ```sh
    pixi run -e js npm stage list loconym
    pixi run -e js npm stage approve <stage-id>   # or: npm stage reject <stage-id>
    ```

If you tick **Set as a pre-release** (`--prerelease` with `gh`), the version is staged under the `next` dist-tag
instead of `latest`, so `npm install loconym` keeps installing the latest stable version. Use a pre-release version
such as `0.2.0-rc.1` (tag `js-v0.2.0-rc.1`) for those. The dist-tag is fixed once staged: to change it, reject the
staged version and publish the release again.

To see exactly what would be published without publishing, run the **npm** workflow manually from the Actions tab
with *dry-run* checked (the default).

!!! note

    Saving a release as a **draft** doesn't publish anything. The workflows run when the release is published.

## Format compatibility

The database [format version](../reference/format-spec.md#7-versioning) is independent of both package versions.
A client accepts any database with format major version `0`. When you change the format incompatibly, release the
builder and the client together.
