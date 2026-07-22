from engine.appc.characters import (
    CharacterClass,
    CharacterClass_GetCurrentToolTipOwner,
    CharacterClass_SetCurrentToolTipOwner,
    DropCharacterToolTips,
)


def test_owner_set_get_roundtrip():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    assert CharacterClass_GetCurrentToolTipOwner() is ch
    CharacterClass_SetCurrentToolTipOwner(None)
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_drop_clears_owner():
    ch = CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(ch)
    DropCharacterToolTips()
    assert CharacterClass_GetCurrentToolTipOwner() is None


def test_should_drop_tooltips_only_for_owner():
    a, b = CharacterClass(), CharacterClass()
    CharacterClass_SetCurrentToolTipOwner(a)
    assert a._should_drop_tooltips() is True
    assert b._should_drop_tooltips() is False
    CharacterClass_SetCurrentToolTipOwner(None)
