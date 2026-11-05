"""subsystem_tree.build_families on hand-built subsystems (spec §4)."""
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, SensorSubsystem, ShipSubsystem,
)
from engine.appc.weapon_subsystems import PhaserSystem, TorpedoSystem
from engine.ui import subsystem_tree as st


def _sub(cls, name, maxc=100.0, cond=None, targetable=1, pos=(0.0, 0.0)):
    s = cls(name)
    s.SetMaxCondition(maxc)
    s.SetCondition(maxc if cond is None else cond)
    s.SetDisabledPercentage(0.5)
    s.SetTargetable(targetable)
    s._position_2d = pos
    return s


def _ship(*, impulse=None, sensor=None, phaser=None, torp=None):
    ship = ShipClass()
    ship.SetName("S")
    ship.SetHull(_sub(HullSubsystem, "Hull"))
    if impulse is not None:
        ship.SetImpulseEngineSubsystem(impulse)
    if sensor is not None:
        ship.SetSensorSubsystem(sensor)
    if phaser is not None:
        ship.SetPhaserSystem(phaser)
    if torp is not None:
        ship.SetTorpedoSystem(torp)
    return ship


def _names(fams):
    return [f.name for f in fams]


def test_hull_is_never_a_family():
    ship = _ship(sensor=_sub(SensorSubsystem, "Sensors"))
    assert _names(st.build_families(ship)) == ["Sensors"]


def test_group_header_kept_only_with_a_targetable_member():
    parent = _sub(PhaserSystem, "Phasers", targetable=0)
    child = _sub(ShipSubsystem, "Bank 1")
    parent.AddChildSubsystem(child)
    torp = _sub(TorpedoSystem, "Torps", targetable=0)
    torp.AddChildSubsystem(_sub(ShipSubsystem, "Tube", targetable=0))
    fams = st.build_families(_ship(phaser=parent, torp=torp))
    assert _names(fams) == ["Phasers"]
    assert fams[0].lockable is False
    assert [m.name for m in fams[0].members] == ["Bank 1"]


def test_destroyed_members_drop_and_an_emptied_family_drops():
    ph = _sub(PhaserSystem, "Phasers")
    ph.AddChildSubsystem(_sub(ShipSubsystem, "A"))
    ph.AddChildSubsystem(_sub(ShipSubsystem, "B", cond=0.0))
    tp = _sub(TorpedoSystem, "Torps")
    tp.AddChildSubsystem(_sub(ShipSubsystem, "T1", cond=0.0))
    fams = st.build_families(_ship(phaser=ph, torp=tp))
    assert _names(fams) == ["Phasers"]
    assert [m.name for m in fams[0].members] == ["A"]


def test_destroyed_single_subsystem_drops():
    ship = _ship(sensor=_sub(SensorSubsystem, "Sensors", cond=0.0),
                 impulse=_sub(ImpulseEngineSubsystem, "Impulse"))
    assert _names(st.build_families(ship)) == ["Impulse"]


def test_family_state_is_its_own_condition_not_its_members():
    ph = _sub(PhaserSystem, "Phasers")
    ph.AddChildSubsystem(_sub(ShipSubsystem, "A", cond=10.0))
    ph.AddChildSubsystem(_sub(ShipSubsystem, "B"))
    fam = st.build_families(_ship(phaser=ph))[0]
    assert fam.state == "healthy"
    assert [m.state for m in fam.members] == ["disabled", "healthy"]


def test_state_ladder():
    def state(cond):
        return st.subsystem_state(_sub(ShipSubsystem, "X", cond=cond))
    assert state(0.0) == "destroyed"
    assert state(50.0) == "disabled"
    assert state(75.0) == "damaged"
    assert state(100.0) == "healthy"


def test_position_and_order_follow_the_ship():
    ph = _sub(PhaserSystem, "Phasers", pos=(10.0, 20.0))
    ph.AddChildSubsystem(_sub(ShipSubsystem, "A", pos=(1.0, 2.0)))
    ph.AddChildSubsystem(_sub(ShipSubsystem, "B", pos=(3.0, 4.0)))
    ship = _ship(sensor=_sub(SensorSubsystem, "Sensors"), phaser=ph)
    fams = st.build_families(ship)
    assert _names(fams) == ["Sensors", "Phasers"]
    assert (fams[1].x_px, fams[1].y_px) == (10.0, 20.0)
    assert [(m.name, m.x_px, m.y_px) for m in fams[1].members] == [
        ("A", 1.0, 2.0), ("B", 3.0, 4.0)]


def test_targetable_subsystem_with_only_untargetable_children_is_a_lockable_leaf():
    ph = _sub(PhaserSystem, "Phasers")
    ph.AddChildSubsystem(_sub(ShipSubsystem, "Hidden", targetable=0))
    fams = st.build_families(_ship(phaser=ph))
    assert _names(fams) == ["Phasers"]
    assert fams[0].lockable is True
    assert fams[0].members == ()


def test_grandchild_only_family_lists_its_targetable_descendants():
    ph = _sub(PhaserSystem, "Phasers", targetable=0)
    mid = _sub(ShipSubsystem, "Ring", targetable=0)
    mid.AddChildSubsystem(_sub(ShipSubsystem, "Bank A", pos=(1.0, 2.0)))
    mid.AddChildSubsystem(_sub(ShipSubsystem, "Bank B", cond=0.0))
    ph.AddChildSubsystem(mid)
    ph.AddChildSubsystem(_sub(ShipSubsystem, "Bank C"))
    fams = st.build_families(_ship(phaser=ph))
    assert _names(fams) == ["Phasers"]
    assert [m.name for m in fams[0].members] == ["Bank A", "Bank C"]
