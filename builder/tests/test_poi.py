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
