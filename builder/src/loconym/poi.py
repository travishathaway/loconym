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


# --------------------------------------------------------------------------------------------------
# Class queries ("museums in Bremen"): phrases -> class, modelled on Nominatim's special phrases.
# Every phrase is its own entry (plurals and translations are not derived), keyed by language. All
# languages are embedded in every database, so a query works whichever ``--language`` was used.
# Values are classes from POI_CLASSES, written "key=value".
PHRASES: dict[str, dict[str, list[str]]] = {
    "tourism=museum": {
        "en": ["museum", "museums"], "es": ["museo", "museos"], "de": ["museum", "museen"],
        "fr": ["musee", "musees"]},
    "tourism=gallery": {
        "en": ["gallery", "galleries", "art gallery", "art galleries"], "es": ["galeria", "galerias"],
        "de": ["galerie", "galerien"], "fr": ["galerie", "galeries"]},
    "tourism=attraction": {
        "en": ["attraction", "attractions", "sight", "sights", "tourist attraction", "tourist attractions"],
        "es": ["atraccion", "atracciones"], "de": ["sehenswurdigkeit", "sehenswurdigkeiten"],
        "fr": ["attraction", "attractions"]},
    "tourism=zoo": {
        "en": ["zoo", "zoos"], "es": ["zoo", "zoos", "zoologico", "zoologicos"], "de": ["zoo", "zoos", "tierpark"],
        "fr": ["zoo", "zoos"]},
    "tourism=theme_park": {
        "en": ["theme park", "theme parks", "amusement park", "amusement parks"],
        "es": ["parque tematico", "parques tematicos"], "de": ["freizeitpark", "freizeitparks", "vergnugungspark"],
        "fr": ["parc d attractions", "parcs d attractions"]},
    "tourism=aquarium": {
        "en": ["aquarium", "aquariums"], "es": ["acuario", "acuarios"], "de": ["aquarium", "aquarien"],
        "fr": ["aquarium", "aquariums"]},
    "tourism=viewpoint": {
        "en": ["viewpoint", "viewpoints"], "es": ["mirador", "miradores"], "de": ["aussichtspunkt", "aussichtspunkte"],
        "fr": ["point de vue", "points de vue", "belvedere"]},
    "tourism=hotel": {
        "en": ["hotel", "hotels"], "es": ["hotel", "hoteles"], "de": ["hotel", "hotels"], "fr": ["hotel", "hotels"]},
    "tourism=hostel": {
        "en": ["hostel", "hostels"], "es": ["albergue", "albergues", "hostal", "hostales"],
        "de": ["hostel", "hostels", "jugendherberge", "jugendherbergen"], "fr": ["auberge", "auberges"]},
    "historic=castle": {
        "en": ["castle", "castles"], "es": ["castillo", "castillos"], "de": ["schloss", "schlosser", "burg", "burgen"],
        "fr": ["chateau", "chateaux"]},
    "historic=monument": {
        "en": ["monument", "monuments"], "es": ["monumento", "monumentos"], "de": ["denkmal", "denkmaler"],
        "fr": ["monument", "monuments"]},
    "historic=memorial": {
        "en": ["memorial", "memorials"], "es": ["memorial", "memoriales"], "de": ["mahnmal", "mahnmale"],
        "fr": ["memorial", "memoriaux"]},
    "historic=ruins": {
        "en": ["ruins"], "es": ["ruinas"], "de": ["ruine", "ruinen"], "fr": ["ruines"]},
    "leisure=park": {
        "en": ["park", "parks"], "es": ["parque", "parques"], "de": ["park", "parks", "parkanlage"],
        "fr": ["parc", "parcs"]},
    "leisure=garden": {
        "en": ["garden", "gardens"], "es": ["jardin", "jardines"], "de": ["garten", "garten"],
        "fr": ["jardin", "jardins"]},
    "leisure=stadium": {
        "en": ["stadium", "stadiums", "stadia"], "es": ["estadio", "estadios"], "de": ["stadion", "stadien"],
        "fr": ["stade", "stades"]},
    "leisure=nature_reserve": {
        "en": ["nature reserve", "nature reserves"], "es": ["reserva natural", "reservas naturales"],
        "de": ["naturschutzgebiet", "naturschutzgebiete"], "fr": ["reserve naturelle", "reserves naturelles"]},
    "natural=beach": {
        "en": ["beach", "beaches"], "es": ["playa", "playas"], "de": ["strand", "strande"], "fr": ["plage", "plages"]},
    "natural=peak": {
        "en": ["peak", "peaks", "mountain", "mountains"], "es": ["pico", "picos", "montana", "montanas"],
        "de": ["gipfel", "berg", "berge"], "fr": ["sommet", "sommets", "montagne", "montagnes"]},
    "amenity=university": {
        "en": ["university", "universities"], "es": ["universidad", "universidades"],
        "de": ["universitat", "universitaten", "uni", "unis"], "fr": ["universite", "universites"]},
    "amenity=college": {
        "en": ["college", "colleges"], "es": ["colegio", "colegios"], "de": ["hochschule", "hochschulen"],
        "fr": ["college", "colleges"]},
    "amenity=school": {
        "en": ["school", "schools"], "es": ["escuela", "escuelas"], "de": ["schule", "schulen"],
        "fr": ["ecole", "ecoles"]},
    "amenity=hospital": {
        "en": ["hospital", "hospitals"], "es": ["hospital", "hospitales"], "de": ["krankenhaus", "krankenhauser"],
        "fr": ["hopital", "hopitaux"]},
    "amenity=pharmacy": {
        "en": ["pharmacy", "pharmacies", "chemist", "chemists"], "es": ["farmacia", "farmacias"],
        "de": ["apotheke", "apotheken"], "fr": ["pharmacie", "pharmacies"]},
    "amenity=library": {
        "en": ["library", "libraries"], "es": ["biblioteca", "bibliotecas"],
        "de": ["bibliothek", "bibliotheken", "bucherei"], "fr": ["bibliotheque", "bibliotheques"]},
    "amenity=theatre": {
        "en": ["theatre", "theatres", "theater", "theaters"], "es": ["teatro", "teatros"],
        "de": ["theater"], "fr": ["theatre", "theatres"]},
    "amenity=cinema": {
        "en": ["cinema", "cinemas", "movie theater", "movie theaters"], "es": ["cine", "cines"],
        "de": ["kino", "kinos"], "fr": ["cinema", "cinemas"]},
    "amenity=arts_centre": {
        "en": ["arts centre", "arts centres", "arts center", "arts centers"],
        "es": ["centro de arte", "centros de arte"],
        "de": ["kulturzentrum", "kulturzentren"], "fr": ["centre d art", "centres d art"]},
    "amenity=townhall": {
        "en": ["town hall", "town halls", "city hall", "city halls"], "es": ["ayuntamiento", "ayuntamientos"],
        "de": ["rathaus", "rathauser"], "fr": ["mairie", "mairies", "hotel de ville"]},
    "amenity=place_of_worship": {
        "en": ["church", "churches", "place of worship", "places of worship", "mosque", "mosques", "synagogue",
               "synagogues", "temple", "temples", "cathedral", "cathedrals"],
        "es": ["iglesia", "iglesias", "mezquita", "mezquitas", "sinagoga", "sinagogas", "catedral", "catedrales"],
        "de": ["kirche", "kirchen", "moschee", "moscheen", "synagoge", "synagogen", "dom", "dome", "kathedrale"],
        "fr": ["eglise", "eglises", "mosquee", "mosquees", "synagogue", "synagogues", "cathedrale", "cathedrales"]},
    "amenity=restaurant": {
        "en": ["restaurant", "restaurants"], "es": ["restaurante", "restaurantes"],
        "de": ["restaurant", "restaurants", "gaststatte", "gaststatten"], "fr": ["restaurant", "restaurants"]},
    "amenity=cafe": {
        "en": ["cafe", "cafes", "coffee shop", "coffee shops"], "es": ["cafe", "cafes", "cafeteria", "cafeterias"],
        "de": ["cafe", "cafes", "kaffee"], "fr": ["cafe", "cafes"]},
    "amenity=pub": {
        "en": ["pub", "pubs"], "es": ["pub", "pubs", "taberna", "tabernas"], "de": ["kneipe", "kneipen", "pub", "pubs"],
        "fr": ["pub", "pubs", "bistrot", "bistrots"]},
    "amenity=bar": {
        "en": ["bar", "bars"], "es": ["bar", "bares"], "de": ["bar", "bars"], "fr": ["bar", "bars"]},
    "shop=supermarket": {
        "en": ["supermarket", "supermarkets", "grocery", "groceries", "grocery store", "grocery stores"],
        "es": ["supermercado", "supermercados"], "de": ["supermarkt", "supermarkte"],
        "fr": ["supermarche", "supermarches"]},
    "shop=mall": {
        "en": ["mall", "malls", "shopping mall", "shopping malls", "shopping centre", "shopping centres"],
        "es": ["centro comercial", "centros comerciales"], "de": ["einkaufszentrum", "einkaufszentren"],
        "fr": ["centre commercial", "centres commerciaux"]},
    "shop=department_store": {
        "en": ["department store", "department stores"], "es": ["grandes almacenes"],
        "de": ["kaufhaus", "kaufhauser", "warenhaus"], "fr": ["grand magasin", "grands magasins"]},
    "railway=station": {
        "en": ["station", "stations", "train station", "train stations", "railway station", "railway stations"],
        "es": ["estacion", "estaciones", "estacion de tren", "estaciones de tren"],
        "de": ["bahnhof", "bahnhofe"], "fr": ["gare", "gares"]},
    "aeroway=aerodrome": {
        "en": ["airport", "airports"], "es": ["aeropuerto", "aeropuertos"], "de": ["flughafen", "flughafen"],
        "fr": ["aeroport", "aeroports"]},
}

# Words between the phrase and the place ("museums IN Bremen"), already normalized, longest first.
CONNECTORS = {
    "en": ["in", "near", "around"],
    "es": ["cerca de", "en"],
    "de": ["in", "bei", "nahe", "um"],
    "fr": ["pres de", "dans", "a"],
}

# A POI list per (class, city) stays small: the best of them by (rank, id) answer a category query.
CATEGORY_LIMIT = 200


def phrase_rows() -> list[tuple[str, str]]:
    """Distinct ``(normalized phrase, class)`` rows for the ``phrase`` table (all languages)."""
    from .normalize import normalize_key

    rows = set()
    for cls, langs in PHRASES.items():
        assert cls in {f"{k}={v}" for k, v in POI_CLASSES}, cls
        for words in langs.values():
            for w in words:
                rows.add((normalize_key(w), cls))
    return sorted(rows)


def connectors() -> list[str]:
    """All connector words, normalized and ordered longest (most tokens) first, without duplicates."""
    from .normalize import normalize_key

    seen = {normalize_key(c) for words in CONNECTORS.values() for c in words}
    return sorted(seen, key=lambda c: (-len(c.split()), c))
