from engine.ui import theme


def test_affiliation_defaults_match_load_interface():
    assert theme.get_affiliation("friendly") == ( 80, 112, 230)
    assert theme.get_affiliation("enemy")    == (216,  43,  43)
    assert theme.get_affiliation("neutral")  == (255, 255, 175)
    assert theme.get_affiliation("unknown")  == (127, 127, 127)


def test_menu_level_defaults_match_load_interface():
    p = theme.get_menu_palette(3)
    assert p.normal      == (207,  96, 159)
    assert p.highlighted == (246, 147, 204)
    assert p.selected    == (103,  48,  79)


def test_unknown_affiliation_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.get_affiliation("badwhatever")


def test_unknown_menu_level_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.get_menu_palette(99)


def test_set_affiliation_overrides_default():
    try:
        theme.set_affiliation("enemy", (200, 200, 200))
        assert theme.get_affiliation("enemy") == (200, 200, 200)
    finally:
        theme.reset_affiliations()


def test_reset_affiliations_restores_defaults():
    theme.set_affiliation("enemy", (1, 2, 3))
    theme.reset_affiliations()
    assert theme.get_affiliation("enemy") == (216, 43, 43)


def test_set_menu_palette_overrides_default():
    try:
        p = theme.MenuPalette(normal=(1,2,3), highlighted=(4,5,6), selected=(7,8,9))
        theme.set_menu_palette(3, p)
        assert theme.get_menu_palette(3) is p
    finally:
        theme.reset_menu_palettes()


def test_reset_menu_palettes_restores_defaults():
    p = theme.MenuPalette(normal=(1,2,3), highlighted=(4,5,6), selected=(7,8,9))
    theme.set_menu_palette(3, p)
    theme.reset_menu_palettes()
    assert theme.get_menu_palette(3).normal == (207, 96, 159)


def test_set_affiliation_unknown_name_raises():
    import pytest
    with pytest.raises(KeyError):
        theme.set_affiliation("noplease", (0, 0, 0))


def test_set_menu_palette_unknown_level_raises():
    import pytest
    p = theme.MenuPalette(normal=(0,0,0), highlighted=(0,0,0), selected=(0,0,0))
    with pytest.raises(KeyError):
        theme.set_menu_palette(99, p)
