# tests/unit/test_phoneme_map.py
from engine.appc.phoneme_map import PhonemeMap, default_phoneme_map, Viseme


def test_bilabials_and_silence_are_closed():
    pm = default_phoneme_map()
    for code in (0, 1, 40, 29, 43):            # sil, closure, M, B, P
        v = pm.viseme_for(code)
        assert v.name == "closed"
        assert v.openness == 0.0
        assert v.texture == "neutral"


def test_open_vowels_are_open():
    pm = default_phoneme_map()
    for code in (56, 64, 115, 139, 59):        # AA, AH x3, AO
        v = pm.viseme_for(code)
        assert v.name == "open" and v.openness == 1.0 and v.texture == "a"


def test_rounded_uses_u_texture_partly_open_jaw():
    pm = default_phoneme_map()
    for code in (50, 42, 48):                   # W, OW, UW
        v = pm.viseme_for(code)
        assert v.name == "rounded" and v.texture == "u"
        assert abs(v.openness - 0.286) < 1e-6


def test_unknown_code_is_closed():
    assert default_phoneme_map().viseme_for(9999).name == "closed"


def test_every_recovered_code_resolves():
    pm = default_phoneme_map()
    codes = [0,1,29,31,32,33,35,36,37,38,39,40,41,42,43,46,47,48,49,50,
             53,54,56,59,64,65,66,81,96,106,113,115,121,139,142]
    assert len(codes) == 35
    for c in codes:
        assert pm.viseme_for(c).name in ("closed", "partly", "open", "rounded")
