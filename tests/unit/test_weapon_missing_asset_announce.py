"""A weapon whose projectile module or fire sound is missing says so, once.

Sideloaded mods routinely depend on packs the player never installed: DCMPv2's
pulse cannons and quantum torpedoes name `Tactical.Projectiles.blackelm*`
modules from Elminster's Common Weapons Pack, and the LC Intrepid's phasers
fire a sound ("LCIFederation Phaser") that nothing registers. Before this, a
pulse cannon with no module simply never fired, a phaser with no sound fired
mute, and a torpedo's photon substitution was logged only under --developer --
so the player saw a dead or silent weapon with no explanation.

Each case now prints ONE `[weapons]` line naming the missing thing, the first
time it bites. Behaviour is otherwise unchanged: the cannon still does not
fire, the torpedo still launches the stock photon, the phaser still fires.
"""
import pytest

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc import projectiles, weapon_subsystems
from engine.appc.math import TGPoint3
from engine.appc.properties import PulseWeaponProperty, WeaponSystemProperty
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    PulseWeapon, PulseWeaponSystem, TorpedoSystem, TorpedoTube,
    _EnergyWeaponFireMixin,
)

MISSING_PULSE = "Tactical.Projectiles._DauntlessNoSuchPulse"
MISSING_TORPEDO = "Tactical.Projectiles._DauntlessNoSuchTorpedo"


@pytest.fixture(autouse=True)
def _fresh():
    weapon_subsystems._announced.clear()
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()
    yield
    weapon_subsystems._announced.clear()
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()


def _weapon_lines(capsys):
    return [l for l in capsys.readouterr().out.splitlines()
            if l.startswith("[weapons]")]


# ── pulse cannon with no module ─────────────────────────────────────────────

def _pulse_cannon(module_name):
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    parent = PulseWeaponSystem("Pulse")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Pulse"))
    parent._parent_ship = ship
    ship._pulse_weapon_system = parent

    cannon = PulseWeapon("Port Cannon")
    prop = PulseWeaponProperty("Port Cannon")
    prop.SetMaxCharge(3.8)
    prop.SetMinFiringCharge(3.6)
    prop.SetNormalDischargeRate(1.0)
    prop.SetCooldownTime(0.2)
    prop.SetModuleName(module_name)
    cannon.SetProperty(prop)
    cannon._max_charge = 3.8
    cannon._min_firing_charge = 3.6
    cannon._normal_discharge_rate = 1.0
    cannon._cooldown_time = 0.2
    cannon._charge_level = 3.8
    parent.AddChildSubsystem(cannon)
    return cannon


def test_a_pulse_cannon_with_no_module_says_so_once(capsys):
    cannon = _pulse_cannon(MISSING_PULSE)
    assert cannon.Fire() is False
    assert cannon.Fire() is False

    lines = _weapon_lines(capsys)
    assert len(lines) == 1
    assert MISSING_PULSE in lines[0]
    assert "will not fire" in lines[0]


def test_a_pulse_cannon_with_its_module_says_nothing(capsys):
    cannon = _pulse_cannon("Tactical.Projectiles.PulseDisruptor")
    assert cannon.Fire() is True
    assert _weapon_lines(capsys) == []


# ── torpedo with no module ──────────────────────────────────────────────────

def _armed_tube(script):
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship._target = None
    ship._target_subsystem = None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, script)
    system.SetProperty(prop)
    system._parent_ship = ship
    ship._torpedo_system = system

    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 2
    tube._num_ready = 2
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


def test_a_torpedo_with_no_module_says_it_fires_photons_once(capsys):
    tube = _armed_tube(MISSING_TORPEDO)
    assert tube.Fire(target=None, offset=None) is True
    weapon_subsystems._reset_projectile_module_cache()   # a later mission
    tube._num_ready = 1
    tube.Fire(target=None, offset=None)

    lines = _weapon_lines(capsys)
    assert len(lines) == 1
    assert MISSING_TORPEDO in lines[0]
    assert weapon_subsystems._FALLBACK_PROJECTILE in lines[0]
    assert len(projectiles._active) >= 1      # the photon still launches


# ── fire sound that nothing registered ──────────────────────────────────────

class _Snd:
    def SetLooping(self, v): pass
    def SetPriority(self, v): pass
    def Play(self, attach_node=None, position=None):
        class _Handle:
            def Stop(self): pass
        return _Handle()


class _Mgr:
    """GetSound returns None for anything not registered, like the real one."""
    def __init__(self, registered=()):
        self._sounds = {name: _Snd() for name in registered}

    def GetSound(self, name):
        return self._sounds.get(name)


class _Prop:
    def __init__(self, sound):
        self._sound = sound

    def GetFireSound(self):
        return self._sound


class _SystemWithoutShip:
    def GetParentShip(self):
        return None


class _Bank(_EnergyWeaponFireMixin):
    """Just enough of a phaser bank for _play_fire_sfx (same shape as
    tests/unit/test_phaser_fire_sfx_attach.py's no-ship fake)."""
    def __init__(self, sound):
        self._prop = _Prop(sound)
        self._loop_handle = None

    def GetParentSubsystem(self):
        return _SystemWithoutShip()

    def GetProperty(self):
        return self._prop


@pytest.fixture
def sound_manager(monkeypatch):
    def install(*registered):
        mgr = _Mgr(registered)
        monkeypatch.setattr("engine.audio.tg_sound.TGSoundManager.instance",
                            classmethod(lambda cls: mgr))
        return mgr
    return install


def test_an_unregistered_fire_sound_says_so_once(sound_manager, capsys):
    sound_manager()
    bank = _Bank("_Dauntless No Such Phaser")
    bank._play_fire_sfx()
    bank._play_fire_sfx()

    lines = _weapon_lines(capsys)
    assert len(lines) == 1
    assert "'_Dauntless No Such Phaser'" in lines[0]
    assert "silently" in lines[0]


@pytest.mark.parametrize("registered", [
    ("Galaxy Phaser Start", "Galaxy Phaser Loop"),   # phaser convention
    ("Galaxy Phaser",),                              # tractor convention
])
def test_a_registered_fire_sound_says_nothing(sound_manager, capsys, registered):
    sound_manager(*registered)
    _Bank("Galaxy Phaser")._play_fire_sfx()
    assert _weapon_lines(capsys) == []


@pytest.mark.parametrize("authored_silence", ["", "(null)", "(NULL)"])
def test_an_authored_no_sound_says_nothing(sound_manager, capsys,
                                           authored_silence):
    """'' and '(null)' are what hardpoint editors write for "no sound";
    DCMPv2 ships both. They are silent on purpose, not missing."""
    sound_manager()
    _Bank(authored_silence)._play_fire_sfx()
    assert _weapon_lines(capsys) == []
