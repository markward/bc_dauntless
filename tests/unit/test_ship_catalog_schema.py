"""engine.ship_catalog.schema.parse_dauntless -- one merged dict in, values,
missing keys and readable errors out. Never raises."""
import pytest

from engine.ship_catalog.schema import Variant, parse_dauntless

FULL = {"title": "Galaxy", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}


def test_full_dict_is_complete():
    p = parse_dauntless(FULL)
    assert p.missing == () and p.errors == ()
    assert p.values == {"title": "Galaxy", "species": "Federation",
                        "era": ("DS9", "DS9"), "role": "tactical",
                        "playable": True}
    assert p.variants == ()


def test_none_means_everything_missing_without_errors():
    p = parse_dauntless(None)
    assert p.missing == ("era", "role", "playable", "title", "species")
    assert p.errors == ()


def test_non_dict_is_an_error_and_everything_missing():
    p = parse_dauntless("Federation")
    assert p.missing == ("era", "role", "playable", "title", "species")
    assert len(p.errors) == 1 and "must be a dict" in p.errors[0]


@pytest.mark.parametrize("era, want", [
    ("DS9", ("DS9", "DS9")),
    ("ds9", ("DS9", "DS9")),                 # ids fold
    (("MOV", "DS9"), ("MOV", "DS9")),
    (["tng", "PIC"], ("TNG", "PIC")),        # list accepted
    ("all", ("all",)),
    ("ALL", ("all",)),
])
def test_era_forms(era, want):
    assert parse_dauntless(dict(FULL, era=era)).values["era"] == want


@pytest.mark.parametrize("era", [
    ("DS9", "MOV"),          # from after to
    "VOY",                   # not an id
    ("DS9",),                # wrong arity
    ("DS9", "PIC", "DISC"),
    2370, None, "",
])
def test_invalid_era_is_missing_with_an_error(era):
    p = parse_dauntless(dict(FULL, era=era))
    assert p.missing == ("era",)
    assert len(p.errors) == 1 and p.errors[0].startswith("era:")


@pytest.mark.parametrize("playable, want", [(1, True), (0, False),
                                             (True, True), (False, False)])
def test_playable_accepts_0_1_and_bools(playable, want):
    assert parse_dauntless(dict(FULL, playable=playable)).values["playable"] is want


@pytest.mark.parametrize("playable", [2, -1, "yes", None, 1.0])
def test_playable_rejects_anything_else(playable):
    assert parse_dauntless(dict(FULL, playable=playable)).missing == ("playable",)


def test_role_folds_and_rejects_labels_and_unknowns():
    assert parse_dauntless(dict(FULL, role="Station")).values["role"] == "station"
    assert parse_dauntless(dict(FULL, role="Automated / Unmanned")).missing == ("role",)
    assert parse_dauntless(dict(FULL, role="carrier")).missing == ("role",)


def test_species_canonicalises_stock_spelling_and_keeps_new_ones():
    assert parse_dauntless(dict(FULL, species="klingon")).values["species"] == "Klingon"
    assert parse_dauntless(dict(FULL, species=" Borg ")).values["species"] == "Borg"
    assert parse_dauntless(dict(FULL, species="  ")).missing == ("species",)


def test_title_is_stripped_and_must_be_non_empty():
    assert parse_dauntless(dict(FULL, title=" Defiant ")).values["title"] == "Defiant"
    assert parse_dauntless(dict(FULL, title="")).missing == ("title",)
    assert parse_dauntless(dict(FULL, title=7)).missing == ("title",)


def test_missing_keys_come_out_in_mandatory_order():
    p = parse_dauntless({"title": "X", "role": "tactical"})
    assert p.missing == ("era", "playable", "species")
    assert p.errors == ()


def test_variants_kept_in_order():
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Sovereign", "registry": "Sovereign"},
        {"name": "USS Enterprise", "script": "Enterprise", "registry": "Enterprise"},
    ]))
    assert p.variants == (Variant("USS Sovereign", None, "Sovereign"),
                          Variant("USS Enterprise", "Enterprise", "Enterprise"))
    assert p.errors == ()


@pytest.mark.parametrize("bad, fragment", [
    ({"registry": "X"}, "needs a non-empty 'name'"),
    ({"name": "USS Nameless"}, "needs a 'script' or a 'registry'"),
    ("USS Venture", "must be a dict"),
])
def test_invalid_variant_is_dropped_with_an_error_and_never_makes_incomplete(bad, fragment):
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Dauntless", "registry": "Dauntless"}, bad]))
    assert p.variants == (Variant("USS Dauntless", None, "Dauntless"),)
    assert p.missing == ()
    assert len(p.errors) == 1 and fragment in p.errors[0]


def test_duplicate_variant_name_is_dropped():
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS A", "registry": "A"}, {"name": "USS A", "registry": "B"}]))
    assert p.variants == (Variant("USS A", None, "A"),)
    assert "duplicate" in p.errors[0]


def test_class_default_must_not_carry_a_script():
    """variants[0] IS the definition: it spawns the definition's own script."""
    p = parse_dauntless(dict(FULL, variants=[
        {"name": "USS Geronimo", "script": "Geronimo", "registry": "Geronimo"},
        {"name": "USS Devore", "registry": "Devore"}]))
    assert p.variants == (Variant("USS Devore", None, "Devore"),)
    assert "class default" in p.errors[0]


def test_variants_not_a_list_is_an_error():
    p = parse_dauntless(dict(FULL, variants="USS Venture"))
    assert p.variants == () and "variants: must be a list" in p.errors[0]
