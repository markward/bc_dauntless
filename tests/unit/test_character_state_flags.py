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


from engine.appc.characters import CharacterClass_Create


def test_setflags_clearflags_isstateset_roundtrip_on_stored_bit():
    c = CharacterClass_Create()
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
    c.SetFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 1
    # IsStateSet requires ALL bits of the mask set.
    c.SetFlags(CharacterClass.CS_INITIATIVE)
    assert c.IsStateSet(CharacterClass.CS_STANDING | CharacterClass.CS_INITIATIVE) == 1
    c.ClearFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
    assert c.IsStateSet(CharacterClass.CS_INITIATIVE) == 1


def test_hidden_bits_are_not_stored_in_flags():
    # CS_HIDDEN (0x10) / CS_VISIBLE (0x100) toggle the hidden-state, never the
    # flag word — so IsStateSet(CS_HIDDEN) is always 0 (CharacterClass.md §3).
    c = CharacterClass_Create()
    c.SetFlags(CharacterClass.CS_HIDDEN)
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 0
    assert c.IsHidden() == 1
    c.SetFlags(CharacterClass.CS_VISIBLE)
    assert c.IsHidden() == 0
    c.ClearFlags(CharacterClass.CS_HIDDEN)   # ClearFlags(0x10) -> show
    assert c.IsHidden() == 0
    c.ClearFlags(CharacterClass.CS_VISIBLE)  # ClearFlags(0x100) -> hide
    assert c.IsHidden() == 1


def test_setinitiative_toggles_flag():
    c = CharacterClass_Create()
    c.SetInitiative(1)
    assert c.IsInitiativeOn() == 1
    c.SetInitiative(0)
    assert c.IsInitiativeOn() == 0


def test_setstatus_string_is_separate_from_flags():
    # Character SetStatus takes a tooltip display string (SDK:
    # pMiguel.SetStatus(db.GetString("Waiting"))). It must NOT touch the flags.
    c = CharacterClass_Create()
    c.SetStatus("Waiting")
    assert c.GetStatusText() == "Waiting"
    assert c._flags == 0
    c.ClearStatus("Waiting")
    assert c.GetStatusText() in (None, "")


def test_setflags_busy_bit_drops_open_menu(monkeypatch):
    # CharacterClass.md §4.3: SetFlags, after setting bits, if 0x8 is now set
    # and the menu is up, calls MenuDown(). MoveTo relies on this.
    c = CharacterClass_Create()
    calls = {"down": 0}
    monkeypatch.setattr(c, "IsMenuUp", lambda *a: 1)
    monkeypatch.setattr(c, "MenuDown", lambda *a: calls.__setitem__("down", calls["down"] + 1))
    c.SetFlags(CharacterClass.CS_UI_DISABLED)
    assert calls["down"] == 1


def test_setflags_busy_bit_no_menu_no_drop(monkeypatch):
    c = CharacterClass_Create()
    calls = {"down": 0}
    monkeypatch.setattr(c, "IsMenuUp", lambda *a: 0)
    monkeypatch.setattr(c, "MenuDown", lambda *a: calls.__setitem__("down", calls["down"] + 1))
    c.SetFlags(CharacterClass.CS_UI_DISABLED)
    assert calls["down"] == 0
