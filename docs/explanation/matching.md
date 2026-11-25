# How search and reverse geocoding match

This page explains the rules behind the results, so you can predict them and know their limits. The exact
algorithms are in the [format spec](../reference/format-spec.md).

## Text normalization

Indexing and searching both go through the same normalizer, so matching is insensitive to case, accents and common
abbreviations:

1. `ß` and `ẞ` become `ss`.
2. Unicode compatibility decomposition (NFKD), then all combining marks are removed: `Église` → `eglise`,
   `ﬁ` → `fi`.
3. Lowercase, then split on anything that isn't `a–z` or `0–9`.
4. A word ending in `str` that is longer than 3 letters gets `asse` appended: `Hauptstr.` → `hauptstrasse`.

Two consequences:

- **Words are matched whole, or by prefix, never by suffix.** German compounds like `Hauptstraße` are one token, so
  `haupt` finds it as you type but `strasse` doesn't.
- **Non-Latin scripts are not supported yet.** After step 3 only ASCII letters and digits remain, so Cyrillic, Greek
  or CJK names produce no tokens.

The normalizer must give bit-identical output in Python and TypeScript. That is why it is deliberately simple and is
covered by golden vectors.

## Streets and cities

logator's unit of search is a **street**: all OSM ways with the same normalized name inside the same city-level
admin area (OSM `admin_level` 8 by default, the municipality in Germany). A "Hauptstraße" in two different towns is
two streets, and one made of fifteen ways is one.

The **city** is the nearest enclosing area at or above `--city-level`. Suburbs and districts (levels 9–11) aren't
used to group streets. They appear in reverse-geocoding results, which are computed from the polygons at the
point.

In countries where the municipality isn't level 8, build with a different `--city-level`.

## Search

Given `"Am Wall 12a, Bremen"`:

1. **Place.** Text after the last comma (`Bremen`) is matched against admin area names, with a prefix match on its
   last word, and mapped to city-level areas. If it matches nothing, the search returns no results instead of
   ignoring the place.
2. **House number.** A leading or trailing token of digits with an optional letter (`12a`) is taken as the house
   number.
3. **Street.** Every remaining word must match: exactly, or as a prefix for the last word once it has
   `minPrefix` (3) letters. Streets that match all words are candidates, within the cities from step 1 or anywhere
   if no place was given.
4. **Ranking.** Each candidate scores 10 per query word that is a whole word of its name, minus the difference in
   word count. Exact names rank above prefix matches and longer names. Ties go to the lower street id, which
   groups by city.
5. **Positioning.** For each returned street with a house number: an exact address match (case-insensitive) wins.
   Otherwise a matching interpolation line is used, with odd/even parity respected and the position proportional
   to the distance along the line (`interpolated: true`). Otherwise the result stays on the street.

To bound the cost in range mode, at most 200 index rows are read per word, and only the first 50 candidates are
scored.

## Reverse geocoding

Given a point and a `zoom`:

1. Read the z16 cell containing the point.
2. The **admin chain** is every area that covers the whole cell, plus those whose clipped polygon contains the
   point.
3. At `zoom >= 18`, the nearest **address point within 40 m** wins.
4. Otherwise, at `zoom >= 16`, the **nearest street segment** wins.
5. If the best street so far is farther away than a cell edge, the neighbouring cell across that edge is read too,
   so results don't change at tile boundaries.

`display_name` joins the street (with house number), then the admin names from deepest to broadest, skipping
repeats.
