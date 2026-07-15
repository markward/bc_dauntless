"""Audited BC event ids — weapon-firing-mechanics.md §1.5, §2.4."""


def test_weapon_event_ids_match_audited_values():
    from engine.appc import events
    assert events.ET_WEAPON_FIRED == 0x0080007C
    assert events.ET_WEAPON_FIRE_FAILED == 0x00800037
    assert events.ET_TORPEDO_AMMO_CONSUMED == 0x00800067


def test_app_shim_reexports_weapon_fired():
    import App
    assert App.ET_WEAPON_FIRED == 0x0080007C
