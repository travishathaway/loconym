"""POI selection: which named OSM objects become searchable places.

Nominatim imports every ``amenity=*``/``shop=*``/... object (a blocklist), which brings in benches, post boxes
and similar street furniture. loconym instead uses an allowlist of destination-type classes and requires a name.
See docs/explanation/pois.md.

``POI_CLASSES`` maps ``(key, value)`` to a base rank (lower = more prominent, like Nominatim's rank_search
scale used by the rest of loconym). ``poi_class`` picks the best class of an object and applies a boost for
``wikidata`` / ``wikipedia`` tags, Nominatim's strongest importance signal.
"""

# fmt: off
POI_CLASSES: dict[tuple[str, str], int] = {
    # landmarks & sights
    ("tourism", "attraction"): 22, ("tourism", "museum"): 22, ("tourism", "gallery"): 24,
    ("tourism", "zoo"): 22, ("tourism", "theme_park"): 22, ("tourism", "aquarium"): 22,
    ("tourism", "viewpoint"): 26, ("tourism", "hotel"): 27, ("tourism", "hostel"): 28,
    ("tourism", "guest_house"): 29,
    ("historic", "castle"): 22, ("historic", "palace"): 22, ("historic", "fort"): 24,
    ("historic", "monument"): 25, ("historic", "memorial"): 27, ("historic", "ruins"): 26,
    ("historic", "archaeological_site"): 24,
    # parks & nature
    ("leisure", "park"): 24, ("leisure", "nature_reserve"): 24, ("leisure", "garden"): 26,
    ("leisure", "stadium"): 24, ("leisure", "sports_centre"): 27,
    ("natural", "peak"): 24, ("natural", "volcano"): 22, ("natural", "beach"): 25,
    ("natural", "waterfall"): 25,
    ("man_made", "lighthouse"): 25, ("man_made", "tower"): 27, ("man_made", "pier"): 28,
    # institutions
    ("amenity", "university"): 20, ("amenity", "college"): 22, ("amenity", "hospital"): 22,
    ("amenity", "townhall"): 24, ("amenity", "theatre"): 24, ("amenity", "cinema"): 26,
    ("amenity", "library"): 26, ("amenity", "arts_centre"): 26, ("amenity", "school"): 28,
    ("amenity", "place_of_worship"): 27,
    # transport hubs
    ("railway", "station"): 22, ("aeroway", "aerodrome"): 20, ("aeroway", "terminal"): 24,
    # everyday named places
    ("shop", "mall"): 26, ("shop", "department_store"): 26, ("shop", "supermarket"): 28,
    ("amenity", "restaurant"): 29, ("amenity", "cafe"): 29, ("amenity", "pub"): 29,
    ("amenity", "bar"): 29, ("amenity", "pharmacy"): 29,
}
# fmt: on

# Named shops outside the table above are still searchable, at the lowest everyday rank.
GENERIC_SHOP_RANK = 30

# Classes that are too ambiguous to index unless they carry a wikidata/wikipedia tag.
NEEDS_WIKI = {("tourism", "viewpoint"), ("historic", "memorial"), ("amenity", "place_of_worship")}

# Never indexed, even with a name: street furniture and similar (the issue's "speed cameras", "post boxes").
EXCLUDED_KEYS = {"highway", "emergency"}
EXCLUDED_VALUES = {
    "bench", "post_box", "post_office", "waste_basket", "waste_disposal", "waste_transfer_station",
    "vending_machine", "drinking_water", "shelter", "bicycle_parking", "bicycle_rental", "parking",
    "parking_space", "parking_entrance", "toilets", "telephone", "atm", "fountain", "clock", "speed_camera",
    "surveillance", "street_lamp", "mast", "artwork",
}

WIKI_BOOST = 4
MIN_RANK = 1


def poi_name(tags) -> str | None:
    """Primary name, falling back to ``brand`` (Nominatim's poi name preset) for unnamed chains."""
    return tags.get("name") or tags.get("brand") or None


def poi_class(tags) -> tuple[str, str, int] | None:
    """Return ``(key, value, rank)`` for the best matching class of ``tags``, or None if not a POI."""
    if poi_name(tags) is None:
        return None
    has_wiki = "wikidata" in tags or "wikipedia" in tags
    best = None
    for key in ("tourism", "historic", "leisure", "natural", "man_made", "amenity", "railway", "aeroway", "shop"):
        value = tags.get(key)
        if value is None or value in EXCLUDED_VALUES or key in EXCLUDED_KEYS:
            continue
        rank = POI_CLASSES.get((key, value))
        if rank is None and key == "shop" and value != "no" and value != "yes":
            rank = GENERIC_SHOP_RANK
        if rank is None:
            continue
        if (key, value) in NEEDS_WIKI and not has_wiki:
            continue
        if best is None or rank < best[2]:
            best = (key, value, rank)
    if best is None:
        return None
    key, value, rank = best
    if has_wiki:
        rank = max(MIN_RANK, rank - WIKI_BOOST)
    return key, value, rank
