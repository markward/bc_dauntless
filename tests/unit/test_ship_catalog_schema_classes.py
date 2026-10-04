"""Sub-project 3 schema additions: a free-text class name, the class-default
flag, Variant.playable, and a name-only class default."""
from engine.ship_catalog.schema import Variant, parse_dauntless

FULL = {"title": "Avenger", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}


def test_variant_of_is_trimmed_free_text():
    p = parse_dauntless(dict(FULL, variant_of="  Defiant "))
    assert p.variant_of == "Defiant" and p.errors == ()


def test_absent_or_blank_variant_of_is_none_without_error():
    assert parse_dauntless(FULL).variant_of is None
    p = parse_dauntless(dict(FULL, variant_of="  "))
    assert p.variant_of is None and p.errors == ()


def test_non_string_variant_of_is_an_error():
    p = parse_dauntless(dict(FULL, variant_of=7))
    assert p.variant_of is None
    assert any(e.startswith("variant_of:") for e in p.errors)


def test_class_default_accepts_0_1_and_bools():
    assert parse_dauntless(dict(FULL, class_default=1)).class_default is True
    assert parse_dauntless(dict(FULL, class_default=False)).class_default is False
    assert parse_dauntless(FULL).class_default is False
    p = parse_dauntless(dict(FULL, class_default="yes"))
    assert p.class_default is False and any(e.startswith("class_default:") for e in p.errors)


def test_neither_key_affects_missing():
    assert parse_dauntless(dict(FULL, variant_of="X", class_default=1)).missing == ()


def test_variant_carries_playable_defaulting_to_none():
    assert Variant("USS X").playable is None
    assert Variant("USS X", script="X", playable=True).playable is True


def test_first_variant_may_be_name_only():
    p = parse_dauntless(dict(FULL, variants=[{"name": "USS Defiant"},
                                             {"name": "USS Valiant", "registry": "Valiant"}]))
    assert p.variants == (Variant("USS Defiant"), Variant("USS Valiant", None, "Valiant"))
    assert p.errors == ()


def test_a_later_name_only_variant_is_still_an_error():
    p = parse_dauntless(dict(FULL, variants=[{"name": "A", "registry": "A"}, {"name": "B"}]))
    assert p.variants == (Variant("A", None, "A"),)
    assert "needs a 'script' or a 'registry'" in p.errors[0]
