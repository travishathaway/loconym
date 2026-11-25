from logator.normalize import normalize_key, normalize_tokens


def test_basic():
    assert normalize_tokens("Rue Grimaldi") == ["rue", "grimaldi"]


def test_german():
    assert normalize_tokens("Hauptstraße") == ["hauptstrasse"]
    assert normalize_tokens("Hauptstr.") == ["hauptstrasse"]
    assert normalize_tokens("Am Wall 12a") == ["am", "wall", "12a"]


def test_diacritics_and_punct():
    assert normalize_tokens("Église-Saint-Étienne") == ["eglise", "saint", "etienne"]
    assert normalize_key("  Ünter den  Linden ") == "unter den linden"


def test_short_str_not_expanded():
    assert normalize_tokens("str") == ["str"]
