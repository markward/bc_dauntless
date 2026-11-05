"""The weapon half of the native combat mirror, written through from Python
(native combat phase 1b, Task 1; engine/appc/native_combat.py).

K1 (the held-weapons fire decision) reads weapon systems, banks, tubes,
torpedo ammo and the firing chains from the C++ mirror, so every field it
reads must equal the Python on every write. Each test drives a field through
its PUBLIC API and reads the row back with combat_dump; floats compare by
float.hex(), never with a tolerance.
"""
import importlib
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


def _ship(name, hardpoint, at=(0.0, 0.0, 0.0)):
    ship = App.ShipClass_Create(name)
    _load_hardpoint(ship, hardpoint)
    ship.SetTranslateXYZ(*at)
    return ship


@pytest.fixture
def arena():
    """A Galaxy (phasers, tubes, tractors), a Klingon Vorcha (pulse
    disruptors) and a Warbird, in one set, native combat on."""
    nc.configure(ON)
    assert nc.enabled()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "native_weapons_mirror")
    galaxy = _ship("Galaxy1", "galaxy")
    vorcha = _ship("Vorcha1", "vorcha", at=(0.0, 400.0, 0.0))
    warbird = _ship("Warbird1", "warbird", at=(0.0, 600.0, 0.0))
    for ship in (galaxy, vorcha, warbird):
        pSet.AddObjectToSet(ship, ship.GetName())
    try:
        yield galaxy, vorcha, warbird
    finally:
        App.g_kSetManager.DeleteSet("native_weapons_mirror")


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _py(value, none=-1):
    """What the mirror holds for a Python value."""
    if value is None:
        return none
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, int):
        return value
    if isinstance(value, TGPoint3):
        return tuple(float(c).hex() for c in (value.x, value.y, value.z))
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            out += [k, _py(v)]
        return out
    if isinstance(value, (list, tuple)):
        return [_py(v) for v in value]
    return getattr(value, "__dict__", {}).get("_nslot", -2)


def _native(value):
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return tuple(float(c).hex() for c in value)
    if isinstance(value, list):
        return [_native(v) for v in value]
    return value


def _assert_field(obj, field, none=-1):
    got = _native(_dump(obj)[field])
    want = _py(obj.__dict__[field], none)
    assert got == want, (
        f"{type(obj).__name__}.{field}: mirror {got!r} != python {want!r}")


SYSTEM_FIELDS = ("_fire_held", "_held_target", "_target_list", "_force_update",
                 "_last_weapon_idx", "_last_group_fired", "_firing_chain_mode",
                 "_group_fire_mode", "_single_fire", "_children", "_is_on")
TORPEDO_SYSTEM_FIELDS = ("_last_system_fire_time", "_selected_slot",
                         "_ammo_by_slot")
LEAF_FIELDS = ("_fire_timer", "_firing", "_target", "_position", "_direction",
               "_up", "_right", "_arc_width_lo", "_arc_width_hi",
               "_arc_height_lo", "_arc_height_hi", "_arc_set")
BANK_FIELDS = ("_charge_level", "_max_charge", "_min_firing_charge",
               "_depleted", "_normal_discharge_rate", "_power_setting")
PULSE_FIELDS = ("_cooldown_remaining", "_cooldown_time")
TUBE_FIELDS = ("_num_ready", "_max_ready", "_last_fire_time",
               "_immediate_delay", "_skew_fire")
AMMO_FIELDS = ("_unlimited", "_available")
SHIP_FIELDS = ("_velocity", "_phaser_system", "_pulse_weapon_system",
               "_tractor_beam_system", "_torpedo_system")
PROPERTY_FIELDS = ("_groups",)


def _check_system(system):
    for f in SYSTEM_FIELDS:
        _assert_field(system, f)
    _assert_field(system, "_held_offset", none=None)
    if "_ammo_by_slot" in system.__dict__:
        for f in TORPEDO_SYSTEM_FIELDS:
            _assert_field(system, f)


def _check_leaf(leaf):
    for f in LEAF_FIELDS:
        _assert_field(leaf, f)
    _assert_field(leaf, "_target_offset", none=None)
    for f in BANK_FIELDS + PULSE_FIELDS + TUBE_FIELDS:
        if f in leaf.__dict__:
            _assert_field(leaf, f)


def _check_all(ship):
    for f in SHIP_FIELDS:
        _assert_field(ship, f)
    for system in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                   ship.GetTractorBeamSystem(), ship.GetTorpedoSystem()):
        if system is None:
            continue
        _check_system(system)
        for i in range(system.GetNumWeapons()):
            _check_leaf(system.GetWeapon(i))
        for ammo in system.__dict__.get("_ammo_by_slot", {}).values():
            for f in AMMO_FIELDS:
                assert _native(_h.combat_dump(_slot(ammo))[f]) == _py(
                    ammo.__dict__[f]), f
        prop = system.GetProperty()
        row = _h.combat_dump(_slot(prop))
        assert row["_groups"] == int(prop.GetGroups() or 0)
        want_chains = [list(g) for _, g in system.GetFiringChains()]
        assert row["_firing_chains"] == want_chains


# ── Registration: class flags ────────────────────────────────────────────────

def test_class_flags_name_each_weapon_kind(arena):
    galaxy, vorcha, _ = arena
    from engine.appc import weapon_subsystems as ws
    kinds = {
        ws.PhaserSystem: 1, ws.PulseWeaponSystem: 2, ws.TractorBeamSystem: 3,
        ws.TorpedoSystem: 4, ws.PhaserBank: 5, ws.PulseWeapon: 6,
        ws.TractorBeam: 7, ws.TorpedoTube: 8}
    seen = set()
    for ship in (galaxy, vorcha):
        for system in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                       ship.GetTractorBeamSystem(), ship.GetTorpedoSystem()):
            if system is None:
                continue
            members = [system] + [system.GetWeapon(i)
                                  for i in range(system.GetNumWeapons())]
            for obj in members:
                row = _dump(obj)
                assert row["weapon_kind"] == kinds[type(obj)], type(obj)
                # No self-managed flag: a tractor's walk is K1's own (fire
                # control native only, M4).
                assert "pump_self_managed" not in row
                seen.add(type(obj))
    assert seen == set(kinds)
    assert _dump(galaxy.GetSensorSubsystem())["weapon_kind"] == 0
    assert _dump(galaxy)["has_real_is_dead"] == 1
    # A plain object has no real IsDead (its stub would record telemetry).
    from engine.appc.objects import ObjectClass
    from engine.core.ids import implements
    plain = ObjectClass()
    assert _dump(plain)["has_real_is_dead"] == int(implements(plain, "IsDead"))


# ── Write-through ────────────────────────────────────────────────────────────

def test_every_weapon_field_writes_through(arena):
    galaxy, vorcha, warbird = arena
    phasers = galaxy.GetPhaserSystem()
    torps = galaxy.GetTorpedoSystem()
    pulse = vorcha.GetPulseWeaponSystem()
    assert phasers and torps and pulse
    _check_all(galaxy)
    _check_all(vorcha)

    # TurnOn / TurnOff
    phasers.TurnOn()
    _assert_field(phasers, "_is_on")
    phasers.TurnOff()
    _assert_field(phasers, "_is_on")
    assert _dump(phasers)["_is_on"] == 0
    phasers.TurnOn()
    torps.TurnOn()
    pulse.TurnOn()
    assert _dump(pulse)["_is_on"] == 1

    # StartFiring arms the held state and runs update_weapons(0.0).
    phasers.StartFiring(vorcha)
    assert phasers.__dict__["_fire_held"] is True
    _check_all(galaxy)
    assert _dump(phasers)["_held_target"] == _slot(vorcha)
    phasers.StopFiring()
    _check_all(galaxy)
    assert _dump(phasers)["_fire_held"] == 0
    assert _dump(phasers)["_target_list"] == []

    # Offsets, with and without.
    offset = TGPoint3(0.25, -0.5, 1.5)
    phasers.StartFiring(warbird, offset)
    assert _dump(phasers)["_held_offset"] is not None
    _check_all(galaxy)
    phasers.StopFiring()
    assert _dump(phasers)["_held_offset"] is None

    # Single fire and the chain mode.
    phasers.SetSingleFire(1)
    _assert_field(phasers, "_single_fire")
    torps.SetFiringChainMode(1)
    _assert_field(torps, "_firing_chain_mode")
    phasers.SetForceUpdate(1)
    _assert_field(phasers, "_force_update")
    phasers.SetGroupFireMode(2)
    _assert_field(phasers, "_group_fire_mode")

    # Banks: charge and power setting.
    bank = phasers.GetWeapon(0)
    bank.SetChargeLevel(1.25)
    _assert_field(bank, "_charge_level")
    bank.SetPowerSetting(2)
    _assert_field(bank, "_power_setting")
    bank.SetPowerSetting(0)
    assert _dump(bank)["_power_setting"] == 0

    # Pulse emitters: a shot starts the cooldown and spends charge.
    cannon = pulse.GetWeapon(0)
    cannon.SetChargeLevel(cannon._max_charge)
    pulse.StartFiring(warbird)
    _check_all(vorcha)

    # Torpedo tubes: fire, reload, skew.
    torps.StartFiring(vorcha)
    _check_all(galaxy)
    tube = torps.GetWeapon(0)
    tube.ReloadTorpedo()
    _check_all(galaxy)
    tube.SetSkewFire(1)
    _assert_field(tube, "_skew_fire")
    torps.SetSkewFire(0)
    _assert_field(tube, "_skew_fire")
    tube.SetLastFireTime(12.5)
    _assert_field(tube, "_last_fire_time")
    torps.StopFiring()
    _check_all(galaxy)

    # Ammo: the type table, the selection, and each type's count.
    from engine.appc.weapon_subsystems import TorpedoAmmoType
    ammo = torps.GetAmmoType(0)
    ammo.SetAvailable(3)
    _check_all(galaxy)
    ammo.AddAvailable(-1)
    _check_all(galaxy)
    extra = TorpedoAmmoType("Quantum", launch_speed=1.0, power_cost=30.0,
                            max_torpedoes=5)
    assert "_nslot" in extra.__dict__
    torps.AddAmmoType(extra)
    _check_all(galaxy)
    assert _dump(torps)["_ammo_by_slot"] == [0, _slot(ammo), 1, _slot(extra)]
    torps.SetCurrentAmmoSlot(1)
    _assert_field(torps, "_selected_slot")
    assert _dump(torps)["_selected_slot"] == 1
    extra.SetMaxTorpedoes(2)
    _check_all(galaxy)
    torps.RemoveAmmoType(1)
    _check_all(galaxy)
    assert _dump(torps)["_selected_slot"] == -1
    assert _dump(torps)["_ammo_by_slot"] == [0, _slot(ammo)]

    # The ship's velocity is rebound on every SetVelocity.
    galaxy.SetVelocity(TGPoint3(1.5, -2.25, 0.125))
    _assert_field(galaxy, "_velocity")
    assert _dump(galaxy)["_velocity"] == (1.5, -2.25, 0.125)

    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_children_follow_add_child_subsystem(arena):
    galaxy, _, _ = arena
    from engine.appc.weapon_subsystems import PhaserBank
    phasers = galaxy.GetPhaserSystem()
    before = list(phasers._children)
    extra = PhaserBank("Extra")
    phasers.AddChildSubsystem(extra)
    assert phasers._children == before + [extra]
    assert _dump(phasers)["_children"] == [_slot(c) for c in before] + [
        _slot(extra)]
    assert _dump(extra)["_parent_subsystem"] == _slot(phasers)


def test_target_list_order_follows_append_and_prune(arena):
    galaxy, vorcha, warbird = arena
    phasers = galaxy.GetPhaserSystem()
    # The bare in-place append (update_weapons' prune would re-push it).
    phasers._add_target(vorcha)
    assert _dump(phasers)["_target_list"] == [_slot(vorcha)]
    phasers._target_list = []
    phasers.TurnOn()
    phasers.StartFiring(vorcha)
    phasers.StartFiring(warbird)        # no stop in between
    assert phasers._target_list == [vorcha, warbird]
    assert _dump(phasers)["_target_list"] == [_slot(vorcha), _slot(warbird)]
    # A duplicate does not append again.
    phasers.StartFiring(vorcha)
    assert _dump(phasers)["_target_list"] == [_slot(vorcha), _slot(warbird)]
    # Pruning (the walk's, native: fire control native only, M3) rebinds
    # the list without the dead.
    vorcha.SetDead(1)
    nc.k1_system(phasers, 0.0)
    assert phasers._target_list == [warbird]
    assert _dump(phasers)["_target_list"] == [_slot(warbird)]
    phasers.StopFiring()
    assert _dump(phasers)["_target_list"] == []


def test_unregistered_target_is_unrepresentable(arena):
    galaxy, _, _ = arena
    phasers = galaxy.GetPhaserSystem()

    class Fake:
        pass
    fake = Fake()
    phasers._held_target = fake
    assert _dump(phasers)["_held_target"] == nc.REF_UNREPRESENTABLE
    phasers._target_list = [fake]
    assert _dump(phasers)["_target_list"] == [nc.REF_UNREPRESENTABLE]
    phasers._held_target = None
    phasers._target_list = []


def test_firing_chains_and_groups_are_pushed(arena):
    galaxy, _, _ = arena
    torps = galaxy.GetTorpedoSystem()
    prop = torps.GetProperty()
    chains = [list(g) for _, g in prop.GetFiringChains()]
    assert chains, "the Galaxy authors firing chains"
    assert _h.combat_dump(_slot(prop))["_firing_chains"] == chains
    prop.SetFiringChainString("01;Dual;0123;Quad")
    assert _h.combat_dump(_slot(prop))["_firing_chains"] == [
        [0, 1], [0, 1, 2, 3]]
    # Groups live on the banks' and tubes' properties (WeaponProperty).
    bank_prop = galaxy.GetPhaserSystem().GetWeapon(0).GetProperty()
    assert _h.combat_dump(_slot(bank_prop))["_firing_chains"] == []
    assert _h.combat_dump(_slot(bank_prop))["_groups"] == int(
        bank_prop.GetGroups())
    bank_prop.SetGroups(5)
    assert _h.combat_dump(_slot(bank_prop))["_groups"] == 5


def test_pulse_module_params_pushed(arena):
    vorcha = arena[1]
    cannon = vorcha.GetPulseWeaponSystem().GetWeapon(0)
    prop = cannon.GetProperty()
    mod = importlib.import_module(prop.GetModuleName())
    row = _dump(cannon)
    assert row["module_ok"] == 1
    assert float(row["launch_speed"]).hex() == float(mod.GetLaunchSpeed()).hex()
    want_life = float(mod.GetLifetime()) if hasattr(mod, "GetLifetime") else 8.0
    assert float(row["lifetime"]).hex() == want_life.hex()
    # A module that does not resolve: the bank reads module_ok 0.
    prop.SetModuleName("Tactical.Projectiles.NoSuchBolt")
    cannon.SetProperty(prop)
    assert _dump(cannon)["module_ok"] == 0
    # The mission-swap cache reset refreshes banks already built.
    prop.SetModuleName(importlib.import_module(
        "Tactical.Projectiles.PulseDisruptor").__name__)
    from engine.appc.weapon_subsystems import _reset_projectile_module_cache
    _reset_projectile_module_cache()
    assert _dump(cannon)["module_ok"] == 0      # lazy: not re-resolved yet
    nc.refresh_stale_pulse_params()
    assert _dump(cannon)["module_ok"] == 1
    # Other emitters carry no module.
    galaxy_bank = arena[0].GetPhaserSystem().GetWeapon(0)
    assert _dump(galaxy_bank)["module_ok"] == 0


def test_posed_parts_flag_follows_force_pose(arena):
    """has_posed_parts is 1 only while a part is OFF its NIF pose (Task 6b;
    tests/unit/test_native_posed_flag.py covers the rigged Bird of Prey)."""
    galaxy, _, _ = arena
    from engine.appc import articulated_part, articulation, part_pose
    hinge = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
    assert _dump(galaxy)["has_posed_parts"] == 0
    articulation.force_part_pose(galaxy, "TestPart", part_pose.IDENTITY)
    assert "TestPart" in galaxy._articulation_poses
    assert _dump(galaxy)["has_posed_parts"] == 0    # named, at identity
    articulation.force_part_pose(galaxy, "TestPart", hinge)
    assert _dump(galaxy)["has_posed_parts"] == 1
    articulation.force_pose(galaxy, None)           # no rig: drops the pose
    assert _dump(galaxy)["has_posed_parts"] == 0

    # A rig appearing (the leaf's snapshot) moves nothing by itself; the
    # flag rises when tick_ship swings its part off identity (no target:
    # cruise), and a rig going leaves the swung pose, which still counts.
    saved = dict(articulated_part._BY_LEAF)
    try:
        part = articulated_part.ArticulatedPartProperty("rigpart")
        part.SetStatePose("cruise", 0.0, 0.0, 0.1, 0.0, 0.0, 10.0)
        galaxy._articulation_leaf = "rigtest_leaf"
        articulated_part.restore({"rigtest_leaf": (part,)})
        assert _dump(galaxy)["has_posed_parts"] == 0
        articulation.tick_ship(galaxy, 1.0 / 60.0)
        assert _dump(galaxy)["has_posed_parts"] == 1
        articulated_part.restore({})
        articulation.tick_ship(galaxy, 1.0 / 60.0)
        assert _dump(galaxy)["has_posed_parts"] == 1
        articulation.force_pose(galaxy, None)
        assert _dump(galaxy)["has_posed_parts"] == 0
    finally:
        articulated_part.restore(saved)
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_reclassify_repushes_the_flags(arena):
    galaxy, _, _ = arena
    _h.combat_set_i(_slot(galaxy), nc._fid("has_real_is_dead"), 0)
    nc.reclassify(galaxy)
    assert _dump(galaxy)["has_real_is_dead"] == 1


def test_wake_and_thaw_unchanged(arena):
    galaxy, _, _ = arena
    passive_state.reset()
    bank = galaxy.GetPhaserSystem().GetWeapon(0)
    # Asleep by the flag alone: the weapons registry is not under test.
    bank.__dict__["_passive_asleep"] = True
    assert passive_state.is_asleep(bank)
    bank.SetChargeLevel(bank._max_charge - 0.5)      # a _charge_level write
    assert not passive_state.is_asleep(bank)
    _assert_field(bank, "_charge_level")
    bank.__dict__["_passive_asleep"] = True
    bank._firing = True                              # a _firing write wakes too
    assert not passive_state.is_asleep(bank)
    _assert_field(bank, "_firing")
    bank._firing = False

    tube = galaxy.GetTorpedoSystem().GetWeapon(0)
    tube.__dict__["_passive_asleep"] = True
    tube._num_ready = 0
    assert not passive_state.is_asleep(tube)
    _assert_field(tube, "_num_ready")

    # A consumer's _is_on pushes.
    phasers = galaxy.GetPhaserSystem()
    phasers.TurnOn()
    phasers.TurnOff()
    _assert_field(phasers, "_is_on")
    passive_state.reset()


def test_audit_mirror_clean_on_combat_stress(monkeypatch, tmp_path):
    """The whole mirror, weapon fields included, equals the Python after 120
    ticks of the busiest dev scene driven the host's way."""
    from tests.helpers import bc_assets, headless_mission
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "6")
    nc.reset()
    App.g_kTimerManager._time = 0.0
    import random
    random.seed(0)
    headless_mission.load("engine.dev_missions.combat_stress")
    from engine import host_loop
    from engine.appc.ship_iter import iter_ships
    from engine.core import loop as game_loop
    from engine.core import step_memo
    from engine.core.loop import TICK_DELTA
    host_loop._reset_sensor_state()
    step_memo.forget()
    nc.configure(ON)
    assert nc.enabled()
    player = App.Game_GetCurrentPlayer()
    ships = list(iter_ships())
    assert len(ships) == 7
    rng = random.Random(20261031)
    for tick in range(120):
        if tick % 7 == 0:
            ship = rng.choice(ships)
            foes = [s for s in ships if s is not ship]
            for system in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                           ship.GetTorpedoSystem()):
                if system is not None:
                    system.StartFiring(rng.choice(foes))
        App.g_kTimerManager._time += TICK_DELTA
        game_loop._update_ship_subsystems()
        live = list(iter_ships())
        host_loop._advance_weapons(live, TICK_DELTA)
        host_loop._advance_combat(live, TICK_DELTA, player=player,
                                  push_render_data=False)
        nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()
    assert any(_dump(s.GetPhaserSystem())["_fire_held"]
               for s in ships if s.GetPhaserSystem() is not None)


# ── Review fix round 1 ───────────────────────────────────────────────────────

def test_posed_flag_does_not_cache_a_rigless_leaf_for_a_scriptless_ship():
    """A fresh ship has _articulation_leaf = None (not yet resolved) and no
    script: computing the flag must not call leaf_for, which would cache ""
    for good."""
    nc.configure(ON)
    ship = App.ShipClass_Create("Scriptless")
    assert ship.__dict__["_articulation_leaf"] is None
    assert nc._posed_flag(ship) == 0
    nc.push_posed_parts(ship)
    nc.reclassify(ship)
    assert ship.__dict__["_articulation_leaf"] is None


def test_pulse_cache_reset_is_lazy_and_audit_resolves_independently(
        arena, monkeypatch):
    vorcha = arena[1]
    cannon = vorcha.GetPulseWeaponSystem().GetWeapon(0)
    mod = importlib.import_module(cannon.GetProperty().GetModuleName())
    real = float(mod.GetLaunchSpeed())
    nc.audit_mirror()
    assert nc.audit_failures() == []
    # The module changes under a warm cache: the audit must see it.
    monkeypatch.setattr(mod, "GetLaunchSpeed", lambda: real + 1.0)
    nc.audit_mirror()
    assert ("PulseWeapon", "launch_speed") in nc.audit_failures()
    nc.audit_failures().clear()
    # A reset only clears and marks stale: nothing is re-resolved mid-teardown.
    from engine.appc import weapon_subsystems as ws
    ws._reset_projectile_module_cache()
    assert ws._pulse_params_cache == {}
    assert float(_dump(cannon)["launch_speed"]).hex() == real.hex()
    nc.refresh_stale_pulse_params()
    assert float(_dump(cannon)["launch_speed"]).hex() == (real + 1.0).hex()
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_dropped_ammo_row_reads_unrepresentable_in_the_slot_table(arena):
    galaxy = arena[0]
    torps = galaxy.GetTorpedoSystem()
    ammo = torps.GetAmmoType(0)
    assert _dump(torps)["_ammo_by_slot"] == [0, _slot(ammo)]
    nc._drop(ammo)
    assert "_nslot" not in ammo.__dict__
    assert _dump(torps)["_ammo_by_slot"] == [0, nc.REF_UNREPRESENTABLE]
    nc.audit_mirror()
    assert nc.audit_failures() == []
