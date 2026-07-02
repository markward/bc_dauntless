"""End-to-end: cloak-capable AI ships run BC's real CloakAttack doctrine.

`AI.Compound.BasicAttack.CreateAI(pShip, …, UseCloaking=1)` routes a
cloak-capable ship through `CloakAttackWrapper → CloakAttack` (a BuilderAI that
should acquire a target, approach, then tactically cloak). Two driver defects
used to break this (see docs/.../cloak-attack-ai-followup.md):

1. The cloak routing path nests the target list deeper than the non-cloak path,
   and `ObjectGroup_ForceToGroup` only flattened one level — so the target group
   ended up holding the bogus name ``"['Tgt']"`` and `SelectTarget` never
   acquired a target (the ship never attacked).
2. The `CloakShip` preprocessor lives deep behind looping `SequenceAI`s gated by
   range/timer `ConditionalAI`s; our `_tick_sequence` didn't refresh conditional
   children or loop, so the sequence never advanced to the cloak branch.

With both fixed, a fully-equipped attacker acquires its target immediately and
engages the cloak once the ~15 s approach timer expires and the sequence reaches
`NeedPower_OrTimeShort`(DONE, power full) → `Cloak`/`CloakShip(1)`. This drives
the real `GameLoop` (timers + proximity + cloak transitions) to pin both halves.
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.properties import CloakingSubsystemProperty
from engine.appc.subsystems import (
    SensorSubsystem, PhaserSystem, PhaserBank, ImpulseEngineSubsystem,
    PowerSubsystem,
)
from engine.core.loop import GameLoop, TICK_DELTA
import AI.Compound.BasicAttack as BA


def _bank(name):
    b = PhaserBank(name)
    b._max_charge = 5.0; b._charge_level = 5.0; b._min_firing_charge = 3.0
    b._max_damage = 1.0; b._max_damage_distance = 5000.0
    b._max_condition = 100.0; b._condition = 100.0; b._disabled_percentage = 0.25
    return b


def _equip(s):
    sen = SensorSubsystem("Sensors")
    sen._max_condition = 100.0; sen._condition = 100.0
    sen._disabled_percentage = 0.5; sen.SetBaseSensorRange(5000.0)
    s.SetSensorSubsystem(sen)
    imp = ImpulseEngineSubsystem("Impulse")
    imp._max_condition = 100.0; imp._condition = 100.0
    imp.SetMaxSpeed(6.0)
    s.SetImpulseEngineSubsystem(imp)
    ph = PhaserSystem("Phasers")
    ph._max_condition = 100.0; ph._condition = 100.0; ph._disabled_percentage = 0.75
    ph.TurnOn()
    for i in range(4):
        ph.AddChildSubsystem(_bank(f"B{i}"))
    s.SetPhaserSystem(ph)
    # Full power: ConditionPowerBelow(0.8) in the CloakAttack tree gates the
    # "need power → flee" branch; with full batteries it reports not-low so the
    # sequence advances past it to the Cloak branch.
    pw = PowerSubsystem("Power")
    pw._max_condition = 100.0; pw._condition = 100.0
    pw.GetMainBatteryPower = lambda: 100.0
    pw.GetMainBatteryLimit = lambda: 100.0
    pw.GetBackupBatteryPower = lambda: 100.0
    pw.GetBackupBatteryLimit = lambda: 100.0
    s.SetPowerSubsystem(pw)


def _cloak_ship(name, x, y):
    s = ShipClass_Create("Warbird")
    s.SetName(name); s.SetTranslateXYZ(x, y, 0.0)
    cp = CloakingSubsystemProperty("Cloaking Device"); cp.SetCloakStrength(100.0)
    s.GetPropertySet().AddToSet("Scene Root", cp)
    # A ShipProperty is present on every hardpoint-loaded ship. BasicAttack's
    # cloak recursion disables UseCloaking, so it falls to the else branch and
    # reads pShip.GetShipProperty().GetSpecies() — which now returns the real
    # ShipProperty (a Romulan warbird), not a silent _Stub.
    sp = App.ShipProperty_Create("Warbird"); sp.SetSpecies(App.SPECIES_ROMULAN_WARBIRD)
    s.GetPropertySet().AddToSet("Scene Root", sp)
    s.SetupProperties()
    _equip(s)
    return s


def _scene(target_y=40.0):
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    atk = _cloak_ship("Atk", 0, 0); pSet.AddObjectToSet(atk, "Atk")
    tgt = ShipClass_Create("Galaxy"); tgt.SetName("Tgt")
    tgt.SetTranslateXYZ(0, target_y, 0)
    _equip(tgt); pSet.AddObjectToSet(tgt, "Tgt")
    return atk


def _build_cloak_attack(atk):
    """Build the real CloakAttack doctrine and attach it to the ship."""
    ai = BA.CreateAI(atk, ["Tgt"], UseCloaking=1)
    if hasattr(atk, "SetAI"):
        atk.SetAI(ai)
    return ai


def test_cloak_attack_ship_acquires_target():
    """Fix #1: the cloak doctrine acquires a target quickly (the routing path no
    longer stringifies its target list into a bogus group name)."""
    atk = _scene()
    ai = _build_cloak_attack(atk)
    loop = GameLoop()
    acquired = False
    for _ in range(30):
        loop.tick()
        if atk.GetTarget() is not None:
            acquired = True
            break
    assert acquired, "cloak ship never acquired a target via CloakAttack"
    assert atk.GetTarget().GetName() == "Tgt"


def test_cloak_attack_ship_engages_cloak():
    """Fix #2 (and #1): driven through the real GameLoop, the CloakAttack tree
    advances to the CloakShip branch and engages the cloak."""
    atk = _scene()
    _build_cloak_attack(atk)
    clk = atk.GetCloakingSubsystem()
    assert clk is not None
    loop = GameLoop()
    engaged = False
    # ~18 s of game time (the approach timer is 15 s). 60 Hz → ~1100 ticks.
    for _ in range(1100):
        loop.tick()
        if clk.IsCloaking() or clk.IsCloaked():
            engaged = True
            break
    assert engaged, "CloakAttack ship never engaged its cloak"
    # And it acquired a target along the way (attack + tactically cloak).
    assert atk.GetTarget() is not None
