"""EnergyWeapon.Fire/CanFire/StopFiring — gates on (IsOn AND charge >=
MinFiringCharge).  Records target/offset, flips _firing, calls SFX.
Accepts target=None per spec (PR 2b's projectile fires forward).
"""
from unittest.mock import patch

from engine.appc.subsystems import PhaserBank, PulseWeapon, TractorBeam, PhaserSystem
from engine.appc.properties import PhaserProperty


def _charged_bank():
    bank = PhaserBank("Test")
    # Parent group provides IsOn(); attach to a turned-on system.
    parent = PhaserSystem("Phasers")
    parent.TurnOn()
    parent.AddChildSubsystem(bank)
    bank._max_charge = 5.0
    bank._min_firing_charge = 3.0
    bank._charge_level = 5.0
    return bank


def test_can_fire_true_when_charged_and_on():
    bank = _charged_bank()
    assert bank.CanFire() == 1


def test_can_fire_false_when_undercharged():
    bank = _charged_bank()
    bank._charge_level = 2.0  # below min_firing_charge
    assert bank.CanFire() == 0


def test_can_fire_false_when_parent_off():
    bank = _charged_bank()
    bank.GetParentSubsystem().TurnOff()
    assert bank.CanFire() == 0


def test_fire_sets_firing_flag():
    bank = _charged_bank()
    assert bank.IsFiring() == 0
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 1


def test_fire_records_target_and_offset():
    bank = _charged_bank()
    bank.Fire(target="enemy_ship", offset="hit_point")
    assert bank._target == "enemy_ship"
    assert bank._target_offset == "hit_point"


def test_fire_with_none_target_succeeds():
    """Spec: target=None is allowed; projectile fires along emitter +Y."""
    bank = _charged_bank()
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 1
    assert bank._target is None


def test_fire_no_ops_when_undercharged():
    bank = _charged_bank()
    bank._charge_level = 1.0
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 0


def test_fire_no_ops_when_off():
    bank = _charged_bank()
    bank.GetParentSubsystem().TurnOff()
    bank.Fire(target=None, offset=None)
    assert bank.IsFiring() == 0


def test_stop_firing_clears_flag():
    bank = _charged_bank()
    bank.Fire(target=None, offset=None)
    bank.StopFiring()
    assert bank.IsFiring() == 0


def test_fire_plays_start_sound():
    """_play_fire_sfx calls mgr.GetSound(name + ' Start') and plays it."""
    bank = _charged_bank()
    prop = PhaserProperty("Galaxy Phaser Hardpoint")
    prop.SetFireSound("Galaxy Phaser")
    bank.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        bank.Fire(target=None, offset=None)
        # _play_fire_sfx: GetSound("Galaxy Phaser Start") is called first.
        # (GetSound("Galaxy Phaser Loop") may also be called for the sustain.)
        get_sound_calls = [c.args[0] for c in mock_mgr.return_value.GetSound.call_args_list]
        assert "Galaxy Phaser Start" in get_sound_calls
        # The sound returned for the start variant should have been played.
        start_sound = mock_mgr.return_value.GetSound.return_value
        assert start_sound.Play.call_count >= 1


def test_fire_falls_back_to_bare_name_when_no_start_variant():
    """Tractor uses SetFireSound("Tractor Beam") — LoadTacticalSounds
    registers it without the " Start" suffix.  Spec: GetSound tries Start
    first (returns None), then falls back to bare name."""
    beam = TractorBeam("Aft Tractor 1")
    parent = PhaserSystem("TractorParent")  # any WeaponSystem will do for IsOn()
    parent.TurnOn()
    parent.AddChildSubsystem(beam)
    beam._max_charge = 1.0
    beam._min_firing_charge = 0.5
    beam._charge_level = 1.0
    prop = PhaserProperty("Tractor Hardpoint")
    prop.SetFireSound("Tractor Beam")
    beam.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        # GetSound("Tractor Beam Start") → None (not registered).
        # GetSound("Tractor Beam")       → a real sound object (registered).
        from unittest.mock import MagicMock
        bare_sound = MagicMock()
        def get_sound(name):
            return None if "Start" in name else bare_sound
        mock_mgr.return_value.GetSound.side_effect = get_sound

        beam.Fire(target=None, offset=None)

        get_sound_calls = [c.args[0] for c in mock_mgr.return_value.GetSound.call_args_list]
        assert "Tractor Beam Start" in get_sound_calls
        assert "Tractor Beam" in get_sound_calls
        # The bare-name sound's Play should have been called (Start was None so skipped).
        assert bare_sound.Play.call_count >= 1


def test_fire_with_empty_fire_sound_no_sfx():
    """Empty FireSound (no hardpoint setter called): no SFX call attempts."""
    bank = _charged_bank()
    prop = PhaserProperty("No-Sound Hardpoint")
    # SetFireSound never called — default empty.
    bank.SetProperty(prop)

    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        bank.Fire(target=None, offset=None)
        mock_mgr.return_value.GetSound.assert_not_called()


def test_pulse_weapon_has_fire_surface():
    """PulseWeapon shares the gating with PhaserBank."""
    pulse = PulseWeapon("Forward Pulse")
    parent = PhaserSystem("PulseSystem")
    parent.TurnOn()
    parent.AddChildSubsystem(pulse)
    pulse._max_charge = 2.0
    pulse._min_firing_charge = 1.0
    pulse._charge_level = 2.0
    assert pulse.CanFire() == 1
    pulse.Fire(None, None)
    assert pulse.IsFiring() == 1
