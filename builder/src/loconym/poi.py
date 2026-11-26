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
    # food and drink
    ("amenity", "restaurant"): 29, ("amenity", "cafe"): 29, ("amenity", "pub"): 29,
    ("amenity", "bar"): 29, ("amenity", "fast_food"): 29, ("amenity", "food_court"): 29,
    ("amenity", "ice_cream"): 29,
    ("amenity", "biergarten"): 29,
    # health
    ("amenity", "pharmacy"): 29,
    ("amenity", "clinic"): 26, ("amenity", "doctors"): 29, ("amenity", "dentist"): 29,
    ("amenity", "veterinary"): 29, ("amenity", "nursing_home"): 29,
    # education (hospital, university, college, school and library are above)
    ("amenity", "research_institute"): 26, ("amenity", "kindergarten"): 29,
    ("amenity", "music_school"): 29, ("amenity", "language_school"): 29,
    # culture, events and entertainment (theatre, cinema and arts_centre are above)
    ("amenity", "conference_centre"): 24, ("amenity", "exhibition_centre"): 24, ("amenity", "planetarium"): 24,
    ("amenity", "casino"): 26, ("amenity", "music_venue"): 26, ("amenity", "events_venue"): 27,
    ("amenity", "nightclub"): 27, ("amenity", "community_centre"): 28,
    # public services (townhall is above)
    ("amenity", "courthouse"): 24, ("amenity", "police"): 27, ("amenity", "fire_station"): 27,
    ("amenity", "prison"): 28, ("amenity", "ranger_station"): 28,
    # transport and mobility (railway stations and aerodromes are above)
    ("amenity", "bus_station"): 24, ("amenity", "ferry_terminal"): 24,
    ("amenity", "fuel"): 29, ("amenity", "car_rental"): 29,
    # money
    ("amenity", "bank"): 29,
    # other destinations
    ("amenity", "monastery"): 26, ("amenity", "public_bath"): 26, ("amenity", "marketplace"): 27,
    ("amenity", "animal_shelter"): 28,
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
    "aeroway=terminal": {
        "en": ["airport terminal", "airport terminals", "terminal", "terminals"],
        "es": ["terminal de aeropuerto", "terminales de aeropuerto", "terminal", "terminales"],
        "de": ["flughafenterminal", "flughafenterminals", "terminal", "terminals"],
        "fr": ["terminal d aeroport", "terminaux d aeroport", "terminal", "terminaux"]},
    "tourism=guest_house": {
        "en": ["guest house", "guest houses", "guesthouse", "guesthouses", "bed and breakfast", "b and b"],
        "es": ["casa de huespedes", "casas de huespedes", "pension", "pensiones"],
        "de": ["pension", "pensionen", "gasthaus", "gasthauser", "gastehaus", "gastehauser"],
        "fr": ["chambre d hotes", "chambres d hotes", "maison d hotes", "maisons d hotes"]},
    "historic=palace": {
        "en": ["palace", "palaces"], "es": ["palacio", "palacios"], "de": ["palast", "palaste", "residenz"],
        "fr": ["palais"]},
    "historic=fort": {
        "en": ["fort", "forts", "fortress", "fortresses"], "es": ["fuerte", "fuertes", "fortaleza", "fortalezas"],
        "de": ["festung", "festungen", "fort", "forts"], "fr": ["fort", "forts", "forteresse", "forteresses"]},
    "historic=archaeological_site": {
        "en": ["archaeological site", "archaeological sites", "archeological site", "archeological sites"],
        "es": ["yacimiento arqueologico", "yacimientos arqueologicos", "sitio arqueologico", "sitios arqueologicos"],
        "de": ["ausgrabungsstatte", "ausgrabungsstatten", "archaologische statte", "archaologische statten"],
        "fr": ["site archeologique", "sites archeologiques"]},
    "leisure=sports_centre": {
        "en": ["sports centre", "sports centres", "sports center", "sports centers", "leisure centre", "gym", "gyms"],
        "es": ["centro deportivo", "centros deportivos", "gimnasio", "gimnasios"],
        "de": ["sportzentrum", "sportzentren", "sporthalle", "sporthallen", "fitnessstudio", "fitnessstudios"],
        "fr": ["centre sportif", "centres sportifs", "salle de sport", "salles de sport"]},
    "natural=volcano": {
        "en": ["volcano", "volcanoes", "volcanos"], "es": ["volcan", "volcanes"], "de": ["vulkan", "vulkane"],
        "fr": ["volcan", "volcans"]},
    "natural=waterfall": {
        "en": ["waterfall", "waterfalls"], "es": ["cascada", "cascadas", "catarata", "cataratas"],
        "de": ["wasserfall", "wasserfalle"], "fr": ["cascade", "cascades", "chute d eau", "chutes d eau"]},
    "man_made=lighthouse": {
        "en": ["lighthouse", "lighthouses"], "es": ["faro", "faros"], "de": ["leuchtturm", "leuchtturme"],
        "fr": ["phare", "phares"]},
    "man_made=tower": {
        "en": ["tower", "towers"], "es": ["torre", "torres"], "de": ["turm", "turme"], "fr": ["tour", "tours"]},
    "man_made=pier": {
        "en": ["pier", "piers", "jetty", "jetties"], "es": ["muelle", "muelles", "embarcadero", "embarcaderos"],
        "de": ["pier", "piers", "steg", "stege", "seebrucke", "seebrucken"],
        "fr": ["jetee", "jetees", "ponton", "pontons"]},
    # food and drink
    "amenity=fast_food": {
        "en": ["fast food", "fast food restaurant", "fast food restaurants", "snack bar", "snack bars", "takeaway",
               "takeaways"],
        "es": ["comida rapida", "restaurante de comida rapida", "restaurantes de comida rapida"],
        "de": ["fast food", "imbiss", "imbisse", "schnellimbiss", "schnellrestaurant", "schnellrestaurants"],
        "fr": ["fast food", "restauration rapide", "snack", "snacks"]},
    "amenity=food_court": {
        "en": ["food court", "food courts"], "es": ["patio de comidas", "patios de comidas"],
        "de": ["food court", "food courts", "foodcourt", "foodcourts"],
        "fr": ["food court", "food courts", "aire de restauration", "aires de restauration"]},
    "amenity=ice_cream": {
        "en": ["ice cream", "ice cream shop", "ice cream shops", "ice cream parlour", "ice cream parlor", "gelato"],
        "es": ["heladeria", "heladerias", "helado", "helados"],
        "de": ["eisdiele", "eisdielen", "eiscafe", "eiscafes", "eis"],
        "fr": ["glacier", "glaciers", "glace", "glaces"]},
    "amenity=biergarten": {
        "en": ["beer garden", "beer gardens", "biergarten", "biergartens"],
        "es": ["biergarten", "jardin de cerveza", "jardines de cerveza"],
        "de": ["biergarten", "biergarten"], "fr": ["biergarten", "jardin a biere", "jardins a biere"]},
    # health
    "amenity=clinic": {
        "en": ["clinic", "clinics", "medical centre", "medical centres", "medical center", "medical centers"],
        "es": ["clinica", "clinicas", "centro medico", "centros medicos"],
        "de": ["klinik", "kliniken", "medizinisches versorgungszentrum", "mvz"],
        "fr": ["clinique", "cliniques", "centre medical", "centres medicaux"]},
    "amenity=doctors": {
        "en": ["doctor", "doctors", "doctor s office", "doctors office", "gp", "physician", "physicians"],
        "es": ["medico", "medicos", "doctor", "doctores", "consulta medica"],
        "de": ["arzt", "arzte", "arztpraxis", "arztpraxen", "praxis", "praxen"],
        "fr": ["medecin", "medecins", "docteur", "docteurs", "cabinet medical", "cabinets medicaux"]},
    "amenity=dentist": {
        "en": ["dentist", "dentists", "dental practice", "dental practices"],
        "es": ["dentista", "dentistas", "clinica dental", "clinicas dentales"],
        "de": ["zahnarzt", "zahnarzte", "zahnarztpraxis", "zahnarztpraxen"],
        "fr": ["dentiste", "dentistes", "cabinet dentaire", "cabinets dentaires"]},
    "amenity=veterinary": {
        "en": ["vet", "vets", "veterinary", "veterinarian", "veterinarians", "animal hospital"],
        "es": ["veterinario", "veterinarios", "clinica veterinaria", "clinicas veterinarias"],
        "de": ["tierarzt", "tierarzte", "tierarztpraxis", "tierarztpraxen", "tierklinik", "tierkliniken"],
        "fr": ["veterinaire", "veterinaires", "clinique veterinaire", "cliniques veterinaires"]},
    "amenity=nursing_home": {
        "en": ["nursing home", "nursing homes", "care home", "care homes"],
        "es": ["residencia de ancianos", "residencias de ancianos", "residencia de mayores"],
        "de": ["pflegeheim", "pflegeheime", "altenheim", "altenheime", "seniorenheim", "seniorenheime"],
        "fr": ["maison de retraite", "maisons de retraite", "ehpad"]},
    # education
    "amenity=research_institute": {
        "en": ["research institute", "research institutes"],
        "es": ["instituto de investigacion", "institutos de investigacion"],
        "de": ["forschungsinstitut", "forschungsinstitute"],
        "fr": ["institut de recherche", "instituts de recherche"]},
    "amenity=kindergarten": {
        "en": ["kindergarten", "kindergartens", "nursery", "nurseries", "preschool", "preschools", "daycare",
               "day care"],
        "es": ["guarderia", "guarderias", "jardin de infancia", "jardines de infancia", "jardin de ninos"],
        "de": ["kindergarten", "kindergarten", "kita", "kitas", "kindertagesstatte", "kindertagesstatten"],
        "fr": ["ecole maternelle", "ecoles maternelles", "creche", "creches", "jardin d enfants"]},
    "amenity=music_school": {
        "en": ["music school", "music schools"], "es": ["escuela de musica", "escuelas de musica", "conservatorio"],
        "de": ["musikschule", "musikschulen", "konservatorium"],
        "fr": ["ecole de musique", "ecoles de musique", "conservatoire", "conservatoires"]},
    "amenity=language_school": {
        "en": ["language school", "language schools"],
        "es": ["escuela de idiomas", "escuelas de idiomas", "academia de idiomas"],
        "de": ["sprachschule", "sprachschulen"], "fr": ["ecole de langues", "ecoles de langues"]},
    # culture, events and entertainment
    "amenity=conference_centre": {
        "en": ["conference centre", "conference centres", "conference center", "conference centers",
               "convention centre", "convention center"],
        "es": ["centro de conferencias", "centros de conferencias", "centro de congresos", "centros de congresos",
               "palacio de congresos"],
        "de": ["kongresszentrum", "kongresszentren", "tagungszentrum", "tagungszentren", "kongresshalle"],
        "fr": ["centre de congres", "centres de congres", "palais des congres", "centre de conferences"]},
    "amenity=exhibition_centre": {
        "en": ["exhibition centre", "exhibition centres", "exhibition center", "exhibition centers",
               "exhibition hall", "exhibition halls", "fairground", "fairgrounds"],
        "es": ["centro de exposiciones", "centros de exposiciones", "recinto ferial", "recintos feriales"],
        "de": ["messe", "messen", "messegelande", "ausstellungszentrum", "ausstellungszentren"],
        "fr": ["centre d exposition", "centres d exposition", "parc des expositions", "palais des expositions"]},
    "amenity=planetarium": {
        "en": ["planetarium", "planetariums", "planetaria"], "es": ["planetario", "planetarios"],
        "de": ["planetarium", "planetarien"], "fr": ["planetarium", "planetariums"]},
    "amenity=casino": {
        "en": ["casino", "casinos"], "es": ["casino", "casinos"],
        "de": ["casino", "casinos", "spielbank", "spielbanken"], "fr": ["casino", "casinos"]},
    "amenity=music_venue": {
        "en": ["music venue", "music venues", "live music", "concert hall", "concert halls"],
        "es": ["sala de conciertos", "salas de conciertos", "sala de musica en vivo"],
        "de": ["konzerthalle", "konzerthallen", "konzertsaal", "livemusik", "musikclub", "musikclubs"],
        "fr": ["salle de concert", "salles de concert", "salle de spectacle", "salles de spectacle"]},
    "amenity=events_venue": {
        "en": ["event venue", "event venues", "events venue", "events venues", "function room", "banquet hall"],
        "es": ["salon de eventos", "salones de eventos", "local de eventos", "locales de eventos"],
        "de": ["veranstaltungsort", "veranstaltungsorte", "eventlocation", "eventlocations", "festsaal", "festsale"],
        "fr": ["salle des fetes", "salle de reception", "salles de reception", "lieu d evenements"]},
    "amenity=nightclub": {
        "en": ["nightclub", "nightclubs", "night club", "night clubs", "disco", "discos"],
        "es": ["club nocturno", "clubes nocturnos", "discoteca", "discotecas"],
        "de": ["nachtclub", "nachtclubs", "diskothek", "diskotheken", "disco", "discos"],
        "fr": ["boite de nuit", "boites de nuit", "discotheque", "discotheques"]},
    "amenity=community_centre": {
        "en": ["community centre", "community centres", "community center", "community centers"],
        "es": ["centro comunitario", "centros comunitarios", "centro civico", "centros civicos"],
        "de": ["gemeindezentrum", "gemeindezentren", "burgerhaus", "burgerhauser", "stadtteilzentrum",
               "nachbarschaftszentrum"],
        "fr": ["centre communautaire", "centres communautaires", "maison de quartier", "maisons de quartier"]},
    # public services
    "amenity=courthouse": {
        "en": ["courthouse", "courthouses", "court", "courts", "law court", "law courts"],
        "es": ["juzgado", "juzgados", "tribunal", "tribunales"],
        "de": ["gericht", "gerichte", "amtsgericht", "landgericht"],
        "fr": ["tribunal", "tribunaux", "palais de justice"]},
    "amenity=police": {
        "en": ["police", "police station", "police stations"],
        "es": ["policia", "comisaria", "comisarias", "comisaria de policia"],
        "de": ["polizei", "polizeiwache", "polizeiwachen", "polizeistation", "polizeirevier"],
        "fr": ["police", "commissariat", "commissariats", "gendarmerie", "gendarmeries"]},
    "amenity=fire_station": {
        "en": ["fire station", "fire stations", "fire department", "fire brigade"],
        "es": ["estacion de bomberos", "estaciones de bomberos", "parque de bomberos", "bomberos"],
        "de": ["feuerwehr", "feuerwehren", "feuerwache", "feuerwachen"],
        "fr": ["caserne de pompiers", "casernes de pompiers", "pompiers"]},
    "amenity=prison": {
        "en": ["prison", "prisons", "jail", "jails"], "es": ["prision", "prisiones", "carcel", "carceles"],
        "de": ["gefangnis", "gefangnisse", "justizvollzugsanstalt", "jva"], "fr": ["prison", "prisons"]},
    "amenity=ranger_station": {
        "en": ["ranger station", "ranger stations", "visitor station", "visitor stations"],
        "es": ["estacion de guardabosques", "estaciones de guardabosques", "puesto de guardaparques"],
        "de": ["rangerstation", "rangerstationen", "nationalparkhaus", "nationalparkhauser"],
        "fr": ["maison du parc", "maisons du parc", "poste de garde forestier"]},
    # transport and mobility
    "amenity=bus_station": {
        "en": ["bus station", "bus stations", "coach station", "coach stations", "bus terminal", "bus terminals"],
        "es": ["estacion de autobuses", "estaciones de autobuses", "terminal de autobuses", "estacion de buses"],
        "de": ["busbahnhof", "busbahnhofe", "omnibusbahnhof", "zob"],
        "fr": ["gare routiere", "gares routieres"]},
    "amenity=ferry_terminal": {
        "en": ["ferry terminal", "ferry terminals", "ferry port", "ferry ports"],
        "es": ["terminal de ferris", "terminales de ferris", "terminal de transbordadores"],
        "de": ["fahrhafen", "fahranleger", "fahrterminal", "fahrterminals"],
        "fr": ["terminal de ferry", "terminaux de ferry", "gare maritime", "gares maritimes"]},
    "amenity=fuel": {
        "en": ["gas station", "gas stations", "petrol station", "petrol stations", "filling station",
               "filling stations", "fuel station", "fuel stations"],
        "es": ["gasolinera", "gasolineras", "estacion de servicio", "estaciones de servicio"],
        "de": ["tankstelle", "tankstellen"],
        "fr": ["station service", "stations service", "station essence", "stations essence"]},
    "amenity=car_rental": {
        "en": ["car rental", "car rentals", "car hire", "rental car", "rental cars"],
        "es": ["alquiler de coches", "alquiler de autos", "alquiler de vehiculos", "alquiler de carros"],
        "de": ["autovermietung", "autovermietungen", "mietwagen"],
        "fr": ["location de voitures", "location de voiture", "loueur de voitures"]},
    # money
    "amenity=bank": {
        "en": ["bank", "banks"], "es": ["banco", "bancos"], "de": ["bank", "banken"], "fr": ["banque", "banques"]},
    # other destinations
    "amenity=monastery": {
        "en": ["monastery", "monasteries", "abbey", "abbeys", "convent", "convents"],
        "es": ["monasterio", "monasterios", "abadia", "abadias", "convento", "conventos"],
        "de": ["kloster", "kloster", "abtei", "abteien"],
        "fr": ["monastere", "monasteres", "abbaye", "abbayes", "couvent", "couvents"]},
    "amenity=public_bath": {
        "en": ["public bath", "public baths", "thermal bath", "thermal baths", "spa", "spas"],
        "es": ["banos publicos", "balneario", "balnearios", "termas"],
        "de": ["therme", "thermen", "thermalbad", "thermalbader", "kurbad", "kurbader"],
        "fr": ["bains publics", "thermes", "bain thermal", "bains thermaux", "spa", "spas"]},
    "amenity=marketplace": {
        "en": ["market", "markets", "marketplace", "marketplaces", "farmers market", "farmers markets"],
        "es": ["mercado", "mercados", "mercadillo", "mercadillos"],
        "de": ["markt", "markte", "wochenmarkt", "wochenmarkte", "marktplatz", "marktplatze"],
        "fr": ["marche", "marches", "marche couvert", "marches couverts"]},
    "amenity=animal_shelter": {
        "en": ["animal shelter", "animal shelters", "pet shelter", "dog pound"],
        "es": ["refugio de animales", "refugios de animales", "protectora de animales"],
        "de": ["tierheim", "tierheime"], "fr": ["refuge pour animaux", "refuges pour animaux"]},
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
