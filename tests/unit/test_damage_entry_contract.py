"""The damage kinds' frozen entry contract (native damage fix round after
the Task 1-2 review, ruling I4).

Task 3 reproduces this Python reference natively and compares the two arms'
entries kind by kind, in order, so the entries must encode natively:

* every operand is an object reference (a mirror handle natively), a
  double, an int code or a bool -- with the same Python types in both arms
  once delivered, so the comparison is exact without a normalisation layer;
* each kind has ONE layout (effect_queue.OPERANDS, the C++
  effect_kind_operands), and the code operands are named constants shared
  with C++ (combat_effect_codes);
* HIT_PRESENT carries no instances dict (delivery looks the map up), an int
  weapon code and points spelled as xyz, with a flag for the hit point
  standing in for the shield point (DM H14);
* ONE gone-object rule: an entry whose subject (its ship, a subsystem's
  ship) is gone at delivery is skipped the same way in both arms.
"""
import App
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_effect_post_typed"),
    reason="combat effect queue bindings not built")

from engine.appc import effect_queue as eq  # noqa: E402
from engine.appc import hit_feedback  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import ship_death, subsystem_cascade  # noqa: E402
from engine.appc.combat import apply_hit  # noqa: E402
from engine.appc.events import WeaponHitEvent  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass, ShipClass_Create  # noqa: E402
from engine.appc.subsystems import (HullSubsystem, RepairSubsystem,  # noqa: E402
                                    SensorSubsystem, ShieldSubsystem)
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402

_PY_TYPES = {"D": float, "I": int, "B": bool}


@pytest.fixture(autouse=True)
def _clean():
    eq.reset()
    subsystem_cascade.reset()
    yield
    eq.reset()
    subsystem_cascade.reset()
    ship_death.reset()


@pytest.fixture
def scratch_set():
    name = "DamageContractTest"
    pset = App.SetClass_Create()
    App.g_kSetManager.AddSet(pset, name)
    yield pset
    App.g_kSetManager.DeleteSet(name)


@pytest.fixture
def presented(monkeypatch):
    """Every hit_feedback.present call's keyword arguments, in order."""
    log = []
    monkeypatch.setattr(hit_feedback, "present", lambda **kw: log.append(kw))
    return log


@pytest.fixture
def weapon_hits(monkeypatch):
    """Every combat.post_weapon_hit call's keyword arguments, in order."""
    from engine.appc import combat
    log = []
    monkeypatch.setattr(combat, "post_weapon_hit",
                        lambda **kw: log.append(kw))
    return log


def _ship(name="Keldon"):
    """A critical hull disabled below 50%, a sensor at the hit point
    (0, 10, 0), a repair bay, shields down."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(1000.0)
    hull.SetCritical(1)
    hull.SetDisabledPercentage(0.5)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensor Array")
    sensor.SetMaxCondition(100.0)
    sensor.SetRadius(1.0)
    sensor._position = TGPoint3(0.0, 10.0, 0.0)
    ship.SetSensorSubsystem(sensor)
    ship.SetRepairSubsystem(RepairSubsystem("Engineering"))
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 1000.0)
        ss.SetCurrentShields(f, 0.0)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def _taken():
    return [(k, ops) for k, _native, ops in _h.combat_effect_take()]


def _check(watcher):
    evt = App.TGFloatEvent_Create()
    evt.SetEventType(App.ET_AI_SYSTEM_STATUS_WATCHER)
    watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, evt)


def _assert_fits(kind, ops):
    layout = eq.OPERANDS[kind]
    assert len(ops) == len(layout), (eq.KIND_NAMES[kind], ops)
    for i, (letter, v) in enumerate(zip(layout, ops)):
        want = _PY_TYPES.get(letter)
        where = (eq.KIND_NAMES[kind], i, letter, v)
        if want is None:            # R / H: an object or None
            assert type(v) not in (float, int, bool, str, tuple, dict), where
        else:
            assert type(v) is want, where


# ── One layout, one set of codes, in both languages ──────────────────────────

def test_the_layouts_are_the_native_ones():
    native = _h.combat_effect_operands()
    assert native == {eq.KIND_NAMES[k]: layout
                      for k, layout in eq.OPERANDS.items()}
    assert len(eq.HIT_PRESENT_FIELDS) == len(eq.OPERANDS[eq.HIT_PRESENT])
    assert len(eq.WEAPON_HIT_FIELDS) == len(eq.OPERANDS[eq.WEAPON_HIT])
    assert set(eq.OPERANDS) == set(eq.DAMAGE_KINDS)


def test_the_code_operands_are_the_native_constants():
    assert _h.combat_effect_codes() == {
        name: getattr(eq, name) for name in eq.CODE_NAMES}
    assert eq.WEAPON_HIT_PHASER == WeaponHitEvent.PHASER
    assert eq.WEAPON_HIT_TORPEDO == WeaponHitEvent.TORPEDO
    assert eq.WEAPON_HIT_TRACTOR_BEAM == WeaponHitEvent.TRACTOR_BEAM
    assert eq.WEAPON_HIT_NON_WEAPON == WeaponHitEvent.NON_WEAPON


# ── Python's entries fit the layout exactly (types included) ─────────────────

def test_a_hits_entries_fit_their_layouts_with_exact_types(scratch_set):
    # PYTHON's entries: the Python damage arm, which only
    # DAUNTLESS_NATIVE_COMBAT=0 runs now the switch defaults on (a native
    # entry carries mirror handles, not objects).
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "0"})
    assert not nc.enabled()
    ship = _ship()
    scratch_set.AddObjectToSet(ship, "Keldon")
    ship.SetSplashDamage(10.0, 1.0)
    _check(ship.GetHull().GetCombinedPercentageWatcher())
    _check(ship.GetSensorSubsystem().GetConditionWatcher())
    # An int damage, int coordinates: the entries still carry doubles.
    apply_hit(ship, 5000, TGPoint3(0, 10, 0), source=None,
              weapon_type="torpedo", normal=TGPoint3(0, 1, 0))
    entries = _taken()
    kinds = {k for k, _ in entries}
    assert kinds == {eq.COND_WATCH, eq.SUBSYS_EVENT, eq.REPAIR_ADD,
                     eq.ZERO_CROSS, eq.HIT_PRESENT, eq.WEAPON_HIT}
    for kind, ops in entries:
        _assert_fits(kind, ops)
        eq.post(kind, *ops)
    taken_splash = []
    real = eq._DELIVER[eq.SPLASH]
    deliver = list(eq._DELIVER)
    deliver[eq.SPLASH] = lambda *ops: (taken_splash.append(ops), real(*ops))
    eq._DELIVER, saved = tuple(deliver), eq._DELIVER
    try:
        eq.boundary()
    finally:
        eq._DELIVER = saved
    assert taken_splash == [(ship,)]
    _assert_fits(eq.SPLASH, taken_splash[0])


def test_an_unknown_weapon_type_is_presented_as_none(presented):
    """dispatch compares the weapon type only with "phaser", "torpedo" and
    "collision": any other string acts as None, so it encodes as
    HIT_WEAPON_NONE (WEAPON_HIT's id is NON_WEAPON for it already)."""
    apply_hit(_ship(), 10.0, TGPoint3(0, 10, 0), source=None,
              weapon_type="photonic_death_ray")
    (kind, ops), = [e for e in _taken() if e[0] == eq.HIT_PRESENT]
    fields = dict(zip(eq.HIT_PRESENT_FIELDS, ops))
    assert fields["weapon_type"] == eq.HIT_WEAPON_NONE


# ── HIT_PRESENT: spelled points, the alias, the instances map ────────────────

def test_hit_present_rebuilds_its_points_and_keeps_the_alias(presented):
    ship = _ship()
    instances = {ship: 7}
    point = TGPoint3(0.0, 10.0, 0.0)
    apply_hit(ship, 50.0, point, source=None, weapon_type="collision",
              normal=TGPoint3(0.0, 1.0, 0.0), ship_instances=instances,
              shield_point=point, hit_tangent=TGPoint3(1.0, 0.0, 0.0),
              decal_radius=0.25, decal_dent=1.0, single_impact=True,
              shield_radius=2.0)
    eq.boundary()
    (kw,) = presented
    assert isinstance(kw["point"], TGPoint3)
    assert (kw["point"].x, kw["point"].y, kw["point"].z) == (0.0, 10.0, 0.0)
    assert kw["shield_point"] is kw["point"]           # the alias (DM H14)
    assert (kw["normal"].x, kw["normal"].y, kw["normal"].z) == (0.0, 1.0, 0.0)
    assert (kw["tangent"].x, kw["tangent"].y) == (1.0, 0.0)
    assert kw["ship_instances"] is instances           # looked up at delivery
    assert kw["weapon_type"] == "collision"
    assert kw["decal_radius"] == 0.25 and kw["shield_radius"] == 2.0
    assert kw["single_impact"] is True and kw["decal_dent"] == 1.0


def test_hit_present_without_the_optional_inputs_delivers_none(presented):
    ship = _ship()
    apply_hit(ship, 150.0, TGPoint3(0.0, 10.0, 0.0), source=None,
              shield_point=TGPoint3(0.0, 12.0, 0.0))    # the sensor dies
    eq.boundary()
    (kw,) = presented
    assert kw["normal"] is None and kw["tangent"] is None
    assert kw["ship_instances"] is None
    assert kw["weapon_type"] is None and kw["sub_transition"] == "destroyed"
    assert kw["decal_radius"] is None and kw["shield_radius"] is None
    assert kw["shield_point"] is not kw["point"]
    assert kw["shield_point"].y == 12.0


# ── The native arm delivers the same values ──────────────────────────────────

def _as_native(kind, ops):
    """`ops` (Python's entry) posted as a kernel would: subjects by handle."""
    layout = eq.OPERANDS[kind]
    out = []
    for letter, v in zip(layout, ops):
        if letter == "R":
            out.append(-1 if v is None else v.__dict__["_nslot"])
        elif letter == "H":
            out.append(-1 if v is None else v)
        else:
            out.append(v)
    _h.combat_effect_post_typed(kind, layout, *out)


def test_a_native_entry_delivers_what_the_python_one_does(presented,
                                                          weapon_hits):
    ship, shooter = _ship(), _ship("Shooter")
    point = TGPoint3(0.0, 10.0, 0.0)
    apply_hit(ship, 50.0, point, source=shooter, weapon_type="phaser",
              normal=TGPoint3(0.0, 1.0, 0.0), ship_instances={ship: 3},
              shield_point=point)
    entries = [(k, ops) for k, ops in _taken()
               if k in (eq.HIT_PRESENT, eq.WEAPON_HIT)]
    for kind, ops in entries:
        eq.post(kind, *ops)
    eq.boundary()
    for kind, ops in entries:
        _as_native(kind, ops)
    eq.boundary()
    ref_p, nat_p = presented
    ref_w, nat_w = weapon_hits

    def plain(kw):
        return {k: ((v.x, v.y, v.z) if isinstance(v, TGPoint3) else v)
                for k, v in kw.items()}
    assert plain(nat_p) == plain(ref_p)
    assert nat_p["shield_point"] is nat_p["point"]
    assert plain(nat_w) == plain(ref_w)
    assert nat_w["source"] is shooter and nat_w["subsystem"] is not None
    # The same Python types, so the comparison needs no normalisation.
    assert {k: type(v) for k, v in nat_p.items()} == {
        k: type(v) for k, v in ref_p.items()}
    assert {k: type(v) for k, v in nat_w.items()} == {
        k: type(v) for k, v in ref_w.items()}


# ── One gone-object rule ─────────────────────────────────────────────────────

def _held_kill(ship):
    """A script's hull 0 and a hit: every damage kind held for the ship."""
    ship.GetHull().SetCondition(0.0)
    apply_hit(ship, 50.0, TGPoint3(0.0, 10.0, 0.0), source=None)


@pytest.mark.parametrize("native", [False, True])
def test_an_entry_whose_ship_was_deleted_is_skipped_in_both_arms(
        native, scratch_set, presented, weapon_hits):
    ship = _ship()
    scratch_set.AddObjectToSet(ship, "Keldon")
    _held_kill(ship)
    entries = _taken()
    assert {k for k, _ in entries} >= {eq.SUBSYS_EVENT, eq.REPAIR_ADD,
                                        eq.ZERO_CROSS, eq.HIT_PRESENT,
                                        eq.WEAPON_HIT}
    for kind, ops in entries:
        if native:
            _as_native(kind, ops)
        else:
            eq.post(kind, *ops)
    scratch_set.DeleteObjectFromSet("Keldon")    # leaves the world
    eq.boundary()
    assert not ship.IsDying()
    assert presented == [] and weapon_hits == []
    assert ship.GetRepairSubsystem()._queue == []
    assert eq.counts()["skipped_gone"] == len(entries)
    assert eq.counts()["damage"] == 0


def test_an_entry_whose_ship_still_lives_is_delivered_in_both_arms(
        scratch_set):
    """The rule's other half: a ship merely moved between sets (warp) is
    not gone."""
    ship = _ship()
    scratch_set.AddObjectToSet(ship, "Keldon")
    ship.GetHull().SetCondition(0.0)
    entries = _taken()
    for kind, ops in entries:
        eq.post(kind, *ops)
    for kind, ops in entries:
        _as_native(kind, ops)
    scratch_set.RemoveObjectFromSet("Keldon")
    eq.boundary()
    assert ship.IsDying()
    assert eq.counts()["skipped_gone"] == 0


def test_a_kernel_entry_whose_subjects_row_was_freed_is_skipped(monkeypatch):
    """The native arm's half of the rule: a subject handle naming no live
    row resolves to nothing and the entry is skipped like a gone one. (The
    reference holds its subject, so the native arm must not let one be freed
    before delivery that the reference would deliver: see the contract.)"""
    splashed = []
    monkeypatch.setattr(ship_death, "deliver_splash", splashed.append)
    ship = _ship()
    _h.combat_effect_post_typed(eq.SPLASH, eq.OPERANDS[eq.SPLASH],
                                ship.__dict__["_nslot"])
    nc.unregister_handle(ship.__dict__.pop("_nslot"))    # its row freed
    eq.boundary()
    assert splashed == []
    assert eq.counts()["skipped_gone"] == 1
