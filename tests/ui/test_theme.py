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
