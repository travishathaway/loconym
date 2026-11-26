# Status and limitations

loconym is early software. The database format is **v0**: it may change incompatibly before 1.0. When it does, the
builder and the client are released together, and the client rejects databases with a format major version it
doesn't know.

## What works

- Reverse geocoding to address, street and admin areas, with Nominatim-style address parts.
- Street and house-number search with type-ahead, city narrowing and address interpolation.
- Fetch and range modes, verified to give identical results to the Python reference reader.
- Measured on Monaco, Bremen (152k addresses) and Hessen (1.64M addresses). On Hessen, reverse at an address returned
  the right street and number 100% of the time, and search found the right street first 99% of the time. See
  [Measurements and design notes](../reference/spike-notes.md).

## Not yet implemented

- Postcodes, `addr:place` addresses and `associatedStreet` relations.
- OSM ids (so there is no Nominatim-style `lookup`), POI de-duplication across node/area pairs, and class-word
  queries such as "museum in Bremen". Named POIs are searchable; see [What counts as a POI](pois.md).
- Names in multiple languages. `--language` is recorded but doesn't select name tags yet.
- Normalization for non-Latin scripts.
- Scoring beyond word coverage. Type-ahead top-5 accuracy is about 85% on large regions, limited by ties among
  streets that share a prefix.
- An OPFS storage driver for persistent offline caching.

## Defaults tuned for Germany

Streets are grouped under `admin_level` 8, and the abbreviation rule (`str` → `strasse`) is German. Other countries
work, but you may need a different `--city-level`, and abbreviations in other languages aren't expanded.

## Scale

Germany-scale builds haven't been measured. Hessen (332 MB input) built in about 5 minutes with under 1 GB of
memory. Memory grows with the number of streets and admin areas. See
[Build a database from a large extract](../how-to/large-extracts.md).
