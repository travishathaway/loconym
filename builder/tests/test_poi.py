import pytest

from loconym.poi import poi_class


@pytest.mark.parametrize("tags,expected", [
    ({"name": "Louvre", "tourism": "museum"}, ("tourism", "museum")),
    ({"name": "Lidl", "shop": "supermarket"}, ("shop", "supermarket")),
    ({"name": "St. Mary", "amenity": "place_of_worship", "wikidata": "Q1"}, ("amenity", "place_of_worship")),
    ({"name": "Hauptbahnhof", "railway": "station"}, ("railway", "station")),
    ({"brand": "Edeka", "shop": "supermarket"}, ("shop", "supermarket")),
    ({"name": "Bakery Joe", "shop": "bakery"}, ("shop", "bakery")),
])
def test_included(tags, expected):
    c = poi_class(tags)
    assert c is not None and c[:2] == expected


@pytest.mark.parametrize("tags", [
    {"amenity": "post_box"},                                  # no name
    {"name": "Box 12", "amenity": "post_box"},
    {"name": "Bench", "amenity": "bench"},
    {"name": "Radar", "highway": "speed_camera"},
    {"name": "Cam", "man_made": "surveillance"},
    {"name": "Garage", "amenity": "parking"},
    {"name": "Chapel", "amenity": "place_of_worship"},       # ambiguous class without wikidata
    {"name": "Nope", "shop": "no"},
    {"tourism": "museum"},                                    # unnamed
])
def test_excluded(tags):
    assert poi_class(tags) is None


def test_wikidata_boost_and_best_class():
    plain = poi_class({"name": "X", "tourism": "museum"})
    wiki = poi_class({"name": "X", "tourism": "museum", "wikidata": "Q9"})
    assert wiki[2] < plain[2]
    # best (lowest-rank) class wins when an object carries several main tags
    both = poi_class({"name": "Uni Shop", "amenity": "university", "shop": "books"})
    assert both[:2] == ("amenity", "university")


def test_phrases_are_normalized_and_cover_all_languages():
    from loconym.normalize import normalize_key
    from loconym.poi import CONNECTORS, PHRASES, POI_CLASSES, connectors, phrase_rows

    rows = phrase_rows()
    assert len(rows) == len(set(rows))
    classes = {f"{k}={v}" for k, v in POI_CLASSES}
    for token, cls in rows:
        assert token == normalize_key(token) and token, token
        assert cls in classes
    for cls, langs in PHRASES.items():
        assert set(langs) == {"en", "es", "de", "fr"}, cls   # every class has a phrase in every language
    tokens = {t: c for t, c in rows}
    assert tokens["museum"] == tokens["museen"] == tokens["museos"] == tokens["musees"] == "tourism=museum"
    assert ("kirche", "amenity=place_of_worship") in rows and ("iglesias", "amenity=place_of_worship") in rows
    conns = connectors()
    assert {"in", "en", "near", "cerca de", "dans"} <= set(conns)
    assert [len(c.split()) for c in conns] == sorted((len(c.split()) for c in conns), reverse=True)
    assert set(CONNECTORS) == {"en", "es", "de", "fr"}


def test_snap_pois(tmp_path):
    import sqlite3

    import shapely
    import shapely.wkb as wkb

    from loconym.snap import snap_pois

    db = sqlite3.connect(tmp_path / "s.sqlite")
    db.executescript("CREATE TABLE addr(gid INT, root INT, hn TEXT, lon REAL, lat REAL);"
                     "CREATE TABLE way(gid INT, root INT, wkb BLOB);")
    # an address point at (8.0, 53.0), and a street running east-west 0.0004 deg (~44 m) north of it
    db.execute("INSERT INTO addr VALUES (1, 7, '12', 8.0, 53.0)")
    db.execute("INSERT INTO way VALUES (2, 7, ?)", (wkb.dumps(shapely.LineString([(7.99, 53.0004), (8.01, 53.0004)])),))
    names = {1: "Dammweg", 2: "Hauptstrasse"}
    pois = [
        (10, 7, 8.00001, 53.00001),   # next to the address: street + house number
        (11, 7, 8.0050, 53.0003),     # ~6 m from the street, > 40 m from any address: street only
        (12, 7, 8.0050, 53.0100),     # > 60 m from everything: nothing
        (13, 9, 8.0, 53.0),           # other root tile: nothing there
    ]
    assert snap_pois(db, names, pois) == {10: ("Dammweg", "12"), 11: ("Hauptstrasse", None)}


def test_every_poi_class_has_phrases():
    """A class without phrases can't be found by "<category> in <city>"; add them in all four languages."""
    from loconym.poi import PHRASES, POI_CLASSES

    missing = sorted(f"{k}={v}" for k, v in POI_CLASSES if f"{k}={v}" not in PHRASES)
    assert not missing, missing
    for cls, langs in PHRASES.items():
        for lang, words in langs.items():
            assert words, (cls, lang)


def test_new_phrases_resolve():
    from loconym.poi import phrase_rows

    rows = set(phrase_rows())
    for token, cls in [("dentists", "amenity=dentist"), ("zahnarzt", "amenity=dentist"), ("bancos", "amenity=bank"),
                       ("tankstellen", "amenity=fuel"), ("station service", "amenity=fuel"),
                       ("kindergartens", "amenity=kindergarten"), ("kitas", "amenity=kindergarten"),
                       ("wochenmarkt", "amenity=marketplace"), ("gares routieres", "amenity=bus_station"),
                       ("leuchtturm", "man_made=lighthouse"), ("eisdiele", "amenity=ice_cream"),
                       ("polizeiwache", "amenity=police"), ("bomberos", "amenity=fire_station")]:
        assert (token, cls) in rows, (token, cls)
