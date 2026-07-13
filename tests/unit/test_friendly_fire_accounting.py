"""BC's friendly-fire accumulator, driven through the real SDK handler.

MissionLib.FriendlyFireHandler (sdk/.../MissionLib.py:3688-3740) is the whole
of BC's friendly-fire accounting: when the PLAYER hits a ship in the mission's
friendly group, the hit's damage is added to g_kUtopiaModule's friendly-fire
total, and crossing the warning / tolerance thresholds raises
ET_FRIENDLY_FIRE_REPORT / ET_FRIENDLY_FIRE_GAME_OVER.

    if not (pEvent.GetWeaponType() == pEvent.TRACTOR_BEAM):   # :3718
        ...accumulate...

The tractor exclusion is deliberate — you tow friendlies — so these tests pin
both halves: a phaser hit on a friendly DOES accumulate, a tractor hit does
NOT.  Before WeaponHitEvent.GetWeaponType() existed, both sides of that
comparison were _Stub objects that compared EQUAL, so the block never ran on
any weapon and the accumulator stayed at zero forever.
"""
import pytest

import App
from engine.appc import combat
from engine.appc.events import ET_FRIENDLY_FIRE_GAME_OVER
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.weapon_subsystems import TractorBeamSystem


class _NullHandlerObject:
    """Stands in for the mission the SDK binds as the broadcast handler's
    pObject. FriendlyFireHandler calls CallNextHandler on every bail-out path."""
    def CallNextHandler(self, evt): pass


class _FriendlyGroup:
    def __init__(self, names): self._names = names
    def IsNameInGroup(self, name): return name in self._names


class _Mission:
    """The tractor group is the mission's list of ships the player is SUPPOSED
    to tractor. A tractor hit on a friendly outside it takes MissionLib's other
    branch (:3750) — it accrues tractor TIME, never friendly-fire damage."""
    def __init__(self, friendly_names, tractor_names=()):
        self._friendly = _FriendlyGroup(friendly_names)
        self._tractor = _FriendlyGroup(set(tractor_names))
    def GetFriendlyGroup(self): return self._friendly
    def GetTractorGroup(self): return self._tractor


@pytest.fixture
def firing_range(monkeypatch):
    """Player ship + a friendly target, with MissionLib wired to see both."""
    import MissionLib

    player = ShipClass()
    player.SetName("Player")
    player._containing_set = object()          # FriendlyFireHandler bails on None
    # MissionLib's tractor branch (AddTractorTime:3851) reads the player's
    # tractor system; a ship without one is not a shape BC ever hands it.
    player.SetTractorBeamSystem(TractorBeamSystem("Tractors"))
    target = ShipClass()
    target.SetName("Friendly")
    mission = _Mission({"Friendly"})

    monkeypatch.setattr(MissionLib, "GetPlayer", lambda: player)
    monkeypatch.setattr(MissionLib, "GetMission", lambda: mission)

    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)
    App.g_kUtopiaModule.SetFriendlyFireWarningPoints(500.0)
    App.g_kUtopiaModule.SetMaxFriendlyFire(1000.0)

    # Run the real SDK handler on every WeaponHitEvent apply_hit broadcasts,
    # and record everything the handler itself raises.
    real_add = App.g_kEventManager.AddEvent
    raised = []

    def spy(evt, *a, **k):
        raised.append(evt)
        if evt.GetEventType() == App.ET_WEAPON_HIT:
            MissionLib.FriendlyFireHandler(_NullHandlerObject(), evt)
        return real_add(evt, *a, **k)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)

    yield player, target, raised
    App.g_kUtopiaModule.SetCurrentFriendlyFire(0.0)


def _hit(player, target, weapon_type, damage=100.0):
    combat.apply_hit(target, damage=damage,
                     hit_point=TGPoint3(0.0, 1.0, 0.0), source=player,
                     weapon_type=weapon_type)


def test_phaser_hit_on_friendly_accumulates_friendly_fire(firing_range):
    player, target, _ = firing_range
    _hit(player, target, "phaser", damage=100.0)
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 100.0


def test_torpedo_hit_on_friendly_accumulates_friendly_fire(firing_range):
    player, target, _ = firing_range
    _hit(player, target, "torpedo", damage=250.0)
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 250.0


def test_tractor_hit_on_friendly_does_not_accumulate(firing_range):
    """BC excludes tractor beams from the damage accumulator: you tow
    friendlies (MissionLib:3718). The hit takes the tractor-time branch
    instead."""
    player, target, _ = firing_range
    _hit(player, target, "tractor", damage=100.0)
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 0.0


def test_hit_on_non_friendly_does_not_accumulate(firing_range):
    player, target, _ = firing_range
    target.SetName("Hostile")
    _hit(player, target, "phaser", damage=100.0)
    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 0.0


def test_crossing_the_tolerance_raises_friendly_fire_game_over(firing_range):
    """The accumulator's payoff. MissionLib reads the ceiling back via
    GetFriendlyFireTolerance() — the SWIG getter (sdk/.../App.py:3259) for the
    value it sets with SetMaxFriendlyFire — then raises
    ET_FRIENDLY_FIRE_GAME_OVER once the total crosses it."""
    player, target, raised = firing_range
    assert App.g_kUtopiaModule.GetFriendlyFireTolerance() == 1000.0

    _hit(player, target, "phaser", damage=1200.0)

    assert App.g_kUtopiaModule.GetCurrentFriendlyFire() == 1200.0
    assert any(e.GetEventType() == ET_FRIENDLY_FIRE_GAME_OVER for e in raised)
