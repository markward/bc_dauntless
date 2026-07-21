"""SP1 — faithful CS_* flag bitfield + ctor state model (CharacterClass.md)."""
from engine.appc.characters import CharacterClass


def test_cs_flags_are_real_bit_values():
    # Values extracted from stbc_constants.csv (tier 1; tier-0 doc gives the
    # bit MEANINGS in CharacterClass.md §3, not the public value table).
    assert CharacterClass.CS_IDLE == 0x0
    assert CharacterClass.CS_STANDING == 0x1
    assert CharacterClass.CS_GLANCING == 0x2
    assert CharacterClass.CS_TURNED == 0x4
    assert CharacterClass.CS_UI_DISABLED == 0x8
    assert CharacterClass.CS_HIDDEN == 0x10
    assert CharacterClass.CS_INITIATIVE == 0x20
    assert CharacterClass.CS_MIDDLE == 0x40
    assert CharacterClass.CS_SEATED == 0x80
    assert CharacterClass.CS_VISIBLE == 0x100
    assert CharacterClass.CS_CLEAR_GLANCE == 0x200
    assert CharacterClass.CS_CLEAR_TURNED == 0x400
    assert CharacterClass.CS_UI_ENABLED == 0x800
    assert CharacterClass.CS_STOP_INITIATIVE == 0xFD8


def test_cpt_phoneme_channels_are_corrected():
    assert CharacterClass.CPT_DEFAULT == -1
    assert CharacterClass.CPT_BLINK == 0
    assert CharacterClass.CPT_SPEAK == 1
    assert CharacterClass.CPT_EYEBROW == 2
