"""SelectTarget's candidate rating, native for stock instances (phase 6 AI
part 2, Task 3).

The SDK's SelectTarget.GetTargetRating (AI/Preprocessors.py:1481-1608) rates
one candidate from nine factors; the popularity factor walks every ship in the
set. ai_optimized registers SelectTarget with an engine subclass whose
GetTargetRating calls the host's ``combat_ai_target_rating`` for a stock
instance: the vector maths and the weighted sum in C++
(dauntless/combat/ai_rating.h), popularity from the native set index, the
other factors read as the SDK reads them. A call it cannot answer exactly runs
the SDK body itself.

Pinned here: the native rating against the SDK body, float.hex() for
float.hex(), on seeded scenes covering every factor (Review Focus 3: shields
off / absent / max 0, a ship with no weapons); FindGoodTarget's pick with the
sensor gate installed and uninstalled, the gate's own fallback included
(Review Focus 2); that registering SelectTarget changes nothing else about the
node; a candidate class overriding GetWorldLocation taking the SDK path
(Review Focus 1); a missing damage ledger raising as the SDK does."""
import math
import random

import pytest

import App
import AI.Preprocessors as pp

from engine.appc import ai_native
from engine.appc import ai_optimized
from engine.appc import ai_sensor_gate
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectGroup
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(_h is None, reason="native host not built")


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    _reset_app_state()
    ai_native.reset_stats()
    yield
    _reset_app_state()


# ── Scene ────────────────────────────────────────────────────────────────────

_WEAPON_SLOTS = ("_torpedo_system", "_phaser_system", "_pulse_weapon_system",
                 "_tractor_beam_system")


def _set(name="Rate"):
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def _armed(name):
    """A ShipClass_Create ship with a hull and every subsystem given a max."""
    s = ShipClass_Create(name)
    s.SetName(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(1000.0)
    s.SetHull(hull)
    for slot in _WEAPON_SLOTS:
        getattr(s, slot).SetMaxCondition(400.0)
    # Working sensors, so the sensor gate (when installed) sees the scene.
    sen = s.GetSensorSubsystem()
    sen.SetMaxCondition(100.0)
    sen.SetBaseSensorRange(2000.0)
    return s


def _node(ship, group, damage=None):
    """A real SDK SelectTarget bound the way the engine binds it; returns
    the BOUND instance (the engine's alias), as the driver calls it."""
    node = PreprocessingAI_Create(ship, "Select")
    node.SetPreprocessingMethod(pp.SelectTarget(group), "Update")
    inst = node.GetPreprocessingInstance()
    inst.dDamageReceived = {} if damage is None else damage
    return inst


def _outcome(fn):
    """(kind, type, value) of a call: a float by its hex, so a rating that
    differs in the last bit (or by sign of zero, or NaN) is a difference."""
    try:
        v = fn()
    except Exception as exc:                   # noqa: BLE001 -- compared
        return ("raise", type(exc).__name__, str(exc))
    if isinstance(v, float):
        return ("ok", "float", v.hex())
    return ("ok", type(v).__name__, repr(v))


def _sdk(inst, target):
    return pp.SelectTarget.GetTargetRating(inst, target)


def _num(rng):
    """A factor value of every shape the SDK sums: floats, small ints, a
    big int (multiplied exactly only by Python), signed zero, inf, NaN."""
    roll = rng.random()
    if roll < 0.55:
        return rng.uniform(-3.0, 3.0)
    if roll < 0.75:
        return rng.randint(-4, 4)
    if roll < 0.82:
        return rng.choice((0.0, -0.0))
    if roll < 0.88:
        return rng.choice((1 << 40, -(1 << 31) - 7, 3 ** 30))
    if roll < 0.94:
        return rng.choice((math.inf, -math.inf))
    if roll < 0.97:
        return rng.choice((math.nan, 1.0e300, 5.0e-324, True))
    # Past 2**53 an int no longer converts exactly: the SDK's own call.
    return rng.choice((1 << 60, -(3 ** 40)))


class _Scene:
    def __init__(self, rng):
        self.rng = rng
        self.pSet = _set()
        self.ships = []
        for i in range(10):
            s = _armed("Ship%d" % i)
            self.pSet.AddObjectToSet(s, "Ship%d" % i)
            self.ships.append(s)
        # A ship with no weapon systems (fWeaponsGood stays 0.0) and a
        # station: hull and shields only.
        for s in self.ships[8:]:
            for slot in _WEAPON_SLOTS:
                setattr(s, slot, None)
        # Shields absent: the SDK's GetShields().GetShieldPercentage()
        # raises AttributeError on None, and so must the native call.
        self.shieldless = _armed("Shieldless")
        self.shieldless._shield_subsystem = None
        self.pSet.AddObjectToSet(self.shieldless, "Shieldless")
        self.planet = Planet_Create(170.0, "")
        self.pSet.AddObjectToSet(self.planet, "Planet")
        # A rater in no set: fPopularity stays 0.0.
        self.loner = _armed("Loner")
        self.candidates = self.ships + [self.shieldless, self.planet,
                                        self.loner]
        names = [o.GetName() for o in self.candidates]
        plain = ObjectGroup()
        info = App.ObjectGroupWithInfo()
        for n in names:
            plain.AddName(n)
            if rng.random() < 0.7:
                info[n] = {"Priority": _num(rng)} if rng.random() < 0.8 else {}
            else:
                info.AddName(n)
        self.groups = (plain, info)
        self.raters = {}

    def inst_for(self, ship, group):
        key = (id(ship), id(group))
        inst = self.raters.get(key)
        if inst is None:
            inst = self.raters[key] = _node(ship, group)
        return inst

    def shuffle(self):
        rng = self.rng
        for s in self.ships + [self.shieldless, self.loner]:
            if rng.random() < 0.1:
                s.SetTranslateXYZ(0.0, 0.0, 0.0)
            else:
                s.SetTranslateXYZ(*(rng.choice((rng.uniform(-90.0, 90.0),
                                                float(rng.randint(-40, 40))))
                                    for _ in range(3)))
            axis = TGPoint3(*(rng.uniform(-1.0, 1.0) for _ in range(3)))
            if axis.Length() > 1e-6:
                axis.Unitize()
                s.SetAngleAxisRotation(rng.uniform(-math.pi, math.pi), axis)
            hull = s.GetHull()
            hull.SetCondition(rng.choice((1000.0, rng.uniform(0.0, 1000.0),
                                          0.0)))
            for slot in _WEAPON_SLOTS:
                w = getattr(s, slot)
                if w is not None:
                    w.SetCondition(rng.choice((400.0, rng.uniform(0.0, 400.0))))
            sh = s.GetShields()
            if sh is not None:
                mode = rng.random()
                if mode < 0.15:                      # max 0: 1.0
                    sh = ShieldSubsystem("Shield Generator")
                    s._shield_subsystem = sh
                else:
                    for f in range(6):
                        sh.SetMaxShields(f, 100.0)
                        sh.SetCurrentShields(f, rng.uniform(0.0, 100.0))
                    if mode < 0.35:                  # off: 0.0
                        sh.TurnOff()
                    else:
                        sh.TurnOn()
        self.planet.SetTranslateXYZ(rng.uniform(-200, 200), 0.0,
                                    rng.uniform(-200, 200))
        # Ships targeting candidates: the popularity factor.
        for s in self.ships + [self.shieldless, self.loner]:
            if rng.random() < 0.6:
                s.SetTarget(rng.choice(self.candidates))
            else:
                s.SetTarget(None)

    def tune(self, inst):
        rng = self.rng
        inst.bSetShipTarget = rng.choice((0, 1))
        inst.sCurrentTarget = rng.choice(
            [None] + [o.GetName() for o in self.candidates])
        if rng.random() < 0.5:
            inst.SetRelativeImportance()
        else:
            inst.SetRelativeImportance(*(_num(rng) for _ in range(9)))
        if rng.random() < 0.2:
            inst.fMinimumFullGoodDistance = rng.choice((30, 12.5, 0.0))
        damage = {}
        for o in self.candidates:
            if rng.random() < 0.3:
                damage[o.GetObjID()] = _num(rng)
        inst.dDamageReceived = damage


def test_native_rating_equals_the_sdk_bit_for_bit():
    rng = random.Random(20261107)
    scene = _Scene(rng)
    rows = raised = 0
    for pair in range(300):
        if pair % 10 == 0:
            scene.shuffle()
        rater = rng.choice(scene.ships + [scene.loner, scene.shieldless])
        inst = scene.inst_for(rater, rng.choice(scene.groups))
        scene.tune(inst)
        cand = rng.choice(scene.candidates)
        want = _outcome(lambda: _sdk(inst, cand))
        got = _outcome(lambda: inst.GetTargetRating(cand))
        assert got == want, (pair, rater.GetName(), cand.GetName())
        rows += 1
        raised += want[0] == "raise"
    s = ai_native.stats()["select"]
    # The comparison was native against the SDK, not the SDK twice: every
    # call that did not raise and needs no inexact int product ran native.
    assert s["native"] > 200, s
    assert s["native"] + s["python"] == rows, s
    assert 0 < raised < 60, raised        # the shieldless rows


def test_every_factor_moves_the_native_rating():
    """The differential above is only as good as its spread: each factor,
    alone, changes the native answer (so none is silently dropped)."""
    pSet = _set()
    ours = _armed("Ours")
    pSet.AddObjectToSet(ours, "Ours")
    them = _armed("Them")
    them.SetTranslateXYZ(10.0, 50.0, 0.0)
    pSet.AddObjectToSet(them, "Them")
    other = _armed("Other")
    pSet.AddObjectToSet(other, "Other")
    info = App.ObjectGroupWithInfo()
    info["Them"] = {"Priority": 0.0}
    inst = _node(ours, info)
    inst.bSetShipTarget = 0

    def rating():
        r = inst.GetTargetRating(them)
        assert r.hex() == _sdk(inst, them).hex()
        return r

    base = rating()
    steps = [
        lambda: them.SetTranslateXYZ(10.0, 80.0, 0.0),        # distance
        lambda: ours.SetAngleAxisRotation(1.0, TGPoint3(0.0, 0.0, 1.0)),
        lambda: setattr(inst, "sCurrentTarget", "Them"),      # is target
        lambda: them.GetShields().SetCurrentShields(0, 10.0),  # shields
        lambda: them._phaser_system.SetCondition(100.0),       # weapons
        lambda: them.GetHull().SetCondition(300.0),            # hull
        lambda: inst.dDamageReceived.__setitem__(them.GetObjID(), 0.25),
        lambda: info.__setitem__("Them", {"Priority": 2.0}),   # priority
        lambda: other.SetTarget(them),                         # popularity
    ]
    for f in range(6):
        them.GetShields().SetMaxShields(f, 100.0)
        them.GetShields().SetCurrentShields(f, 100.0)
    base = rating()
    for i, step in enumerate(steps):
        step()
        now = rating()
        assert now != base, i
        base = now
    assert ai_native.stats()["select"]["python"] == 0


# ── FindGoodTarget, gated and ungated (Review Focus 2) ───────────────────────

def _fight(rng):
    pSet = _set()
    ours = _armed("Ours")
    pSet.AddObjectToSet(ours, "Ours")
    group = App.ObjectGroupWithInfo()
    foes = []
    for i in range(8):
        f = _armed("Foe%d" % i)
        f.SetTranslateXYZ(rng.uniform(-60, 60), rng.uniform(-60, 60),
                          rng.uniform(-60, 60))
        for k in range(6):
            f.GetShields().SetMaxShields(k, 100.0)
            f.GetShields().SetCurrentShields(k, rng.uniform(0.0, 100.0))
        f.GetHull().SetCondition(rng.uniform(100.0, 1000.0))
        pSet.AddObjectToSet(f, "Foe%d" % i)
        group["Foe%d" % i] = {"Priority": rng.choice((0.0, 0.5, 1.0))}
        foes.append(f)
    for f in foes[:4]:
        f.SetTarget(rng.choice(foes[4:]))
    inst = _node(ours, group)
    inst.dDamageReceived = {foes[2].GetObjID(): 0.3}
    return inst, foes


def _pick(monkeypatch, native):
    if native:
        monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
    else:
        monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "0")
    picks = []
    rng = random.Random(7)
    for _ in range(12):
        _reset_app_state()
        inst, _foes = _fight(rng)
        picks.append(inst.FindGoodTarget())
    return picks


@pytest.mark.parametrize("gated", (False, True))
def test_find_good_target_picks_the_same_name_gated_and_ungated(
        monkeypatch, gated):
    if gated:
        ai_sensor_gate.install_ai_sensor_gate()
        assert getattr(pp.SelectTarget.FindGoodTarget, "_sensor_gated", False)
    else:
        ai_sensor_gate.uninstall_ai_sensor_gate()
        assert not getattr(pp.SelectTarget.FindGoodTarget, "_sensor_gated",
                           False)
    try:
        sdk = _pick(monkeypatch, native=False)
        assert ai_native.stats()["select"]["native"] == 0
        ai_native.reset_stats()
        native = _pick(monkeypatch, native=True)
    finally:
        ai_sensor_gate.uninstall_ai_sensor_gate()
    assert native == sdk
    assert len(set(sdk)) > 1, sdk                     # the scenes differ
    s = ai_native.stats()["select"]
    assert s["native"] == 12 * 8 and s["python"] == 0, s


def test_the_sensor_gates_own_fallback_rates_natively(monkeypatch):
    """_best_detectable_candidate scores with select_target.GetTargetRating:
    on the bound node that is the native rating."""
    picks = {}
    for native in (False, True):
        if native:
            monkeypatch.delenv("DAUNTLESS_NATIVE_AI", raising=False)
        else:
            monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "0")
        _reset_app_state()
        ai_native.reset_stats()
        inst, _foes = _fight(random.Random(11))
        ship = inst.pCodeAI.GetShip()
        picks[native] = ai_sensor_gate._best_detectable_candidate(inst, ship)
        counts = ai_native.stats()["select"]
        assert counts["native"] == (8 if native else 0), counts
    assert picks[True] == picks[False] is not None


# ── Registration changes nothing else ────────────────────────────────────────

def test_select_target_registration_keeps_driver_init_and_events():
    from engine.appc.events import WeaponHitEvent
    ai_sensor_gate.install_ai_sensor_gate()
    try:
        pSet = _set()
        ours = _armed("Ours")
        pSet.AddObjectToSet(ours, "Ours")
        foe = _armed("Foe")
        foe.SetTranslateXYZ(0.0, 100.0, 0.0)
        pSet.AddObjectToSet(foe, "Foe")
        group = ObjectGroup()
        group.AddName("Foe")
        sdk_inst = pp.SelectTarget(group)
        node = PreprocessingAI_Create(ours, "Select")
        node.SetPreprocessingMethod(sdk_inst, "Update")
        stay = PlainAI_Create(ours, "Stay")
        stay.SetScriptModule("Stay")
        node.SetContainedAI(stay)
        ours.SetAI(node)
        bound = node.GetPreprocessingInstance()

        # The engine's subclass, sharing the SDK instance's state.
        assert type(bound) is not pp.SelectTarget
        assert isinstance(bound, pp.SelectTarget)
        assert bound.__dict__ is sdk_inst.__dict__
        own = {k for k in type(bound).__dict__ if not k.startswith("__")}
        assert own == {"GetTargetRating"}
        assert type(bound).GetTargetRating._dauntless_native_entry is True
        # Picklable by name, as the other registered classes.
        assert getattr(ai_optimized, type(bound).__name__) is type(bound)
        # The sensor gate's patch on the SDK class is still what runs.
        assert type(bound).FindGoodTarget is pp.SelectTarget.FindGoodTarget
        assert type(bound).FindGoodTarget._sensor_gated
        # Re-binding the bound node does not wrap it twice.
        assert ai_optimized.optimized_version_of(bound) is bound

        # The driver's CodeAISet stand-in still runs on the first tick.
        tick_ai(node, 0.0)
        assert bound._dauntless_codeaiset_done
        assert bound.dDamageReceived == {}
        assert bound.sCurrentTarget == "Foe"

        # ... and registered DamageEvent: a hit lands in the ledger.
        evt = WeaponHitEvent()
        evt.SetEventType(App.ET_WEAPON_HIT)
        evt.SetSource(foe)
        evt.SetDestination(ours)
        evt.SetDamage(150.0)
        App.g_kEventManager.AddEvent(evt)
        assert bound.dDamageReceived == {
            foe.GetObjID(): 150.0 / ours.GetHull().GetMaxCondition()}

        # ... and TargetEnteredSet: a new member forces a reselect.
        group.AddName("Late")
        node._next_update_time = 99.0
        late = _armed("Late")
        pSet.AddObjectToSet(late, "Late")
        assert node._next_update_time == 0.0
    finally:
        ai_sensor_gate.uninstall_ai_sensor_gate()


# ── The SDK path, per call (Review Focus 1) ──────────────────────────────────

def _pair():
    pSet = _set()
    ours = _armed("Ours")
    pSet.AddObjectToSet(ours, "Ours")
    them = _armed("Them")
    them.SetTranslateXYZ(0.0, 40.0, 0.0)
    pSet.AddObjectToSet(them, "Them")
    group = ObjectGroup()
    group.AddName("Them")
    return pSet, ours, them, _node(ours, group)


def test_a_candidate_class_overriding_getworldlocation_takes_the_python_path():
    class Decoy(ShipClass):
        def GetWorldLocation(self):
            return TGPoint3(0.0, 5.0, 0.0)

    pSet, ours, them, inst = _pair()
    decoy = Decoy()
    decoy.SetHull(HullSubsystem("Hull"))
    decoy.GetHull().SetMaxCondition(100.0)
    decoy.SetShieldSubsystem(ShieldSubsystem("Shield"))
    decoy.SetTranslateXYZ(0.0, 400.0, 0.0)        # the store says 400
    pSet.AddObjectToSet(decoy, "Decoy")

    r = inst.GetTargetRating(decoy)
    assert r.hex() == _sdk(inst, decoy).hex()
    s = ai_native.stats()["select"]
    assert (s["native"], s["python"]) == (0, 1), s
    assert s["reasons"] == {"surface": 1}, s
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    assert ai_native.stats()["select"]["native"] == 1    # `them`: native

    # The store says 400 GU, the override 5: a native read of the store
    # would have answered differently (fDistanceGood 0.075, not 1.0). Put
    # the engine's own body back and the next call is native again.
    Decoy.GetWorldLocation = ShipClass.GetWorldLocation
    stored = inst.GetTargetRating(decoy)
    assert stored.hex() == _sdk(inst, decoy).hex()
    assert abs((r - stored) - (1.0 - 30.0 / 400.0)) < 1e-12, (r, stored)
    assert ai_native.stats()["select"]["native"] == 2

    # The same, for an instance attribute on an ordinary ship.
    them.__dict__["GetWorldLocation"] = lambda: TGPoint3(0.0, 1.0, 0.0)
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    assert ai_native.stats()["select"]["reasons"] == {"surface": 2}


def test_a_ship_in_the_set_overriding_gettarget_takes_the_python_path():
    """The popularity factor stands in for GetTarget / GetObjID on every
    ship in the set: a ship whose class overrides one is not stock."""
    class Liar(ShipClass):
        def GetTarget(self):
            return None

    pSet, ours, them, inst = _pair()
    liar = Liar()
    pSet.AddObjectToSet(liar, "Liar")
    liar.SetTarget(them)                       # the index counts this
    r = inst.GetTargetRating(them)
    assert r.hex() == _sdk(inst, them).hex()
    assert ai_native.stats()["select"]["reasons"] == {"surface": 1}


def test_a_ship_in_the_set_with_an_instance_gettarget_takes_the_python_path():
    """The same for an instance attribute, on a ship whose class is stock
    (so its type is already remembered and the walk is the fast one)."""
    pSet, ours, them, inst = _pair()
    other = _armed("Other")
    pSet.AddObjectToSet(other, "Other")
    other.SetTarget(them)
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    assert ai_native.stats()["select"]["native"] == 1
    other.__dict__["GetTarget"] = lambda: None   # the SDK loop sees no target
    r = inst.GetTargetRating(them)
    assert r.hex() == _sdk(inst, them).hex()
    assert ai_native.stats()["select"]["reasons"] == {"surface": 1}
    del other.__dict__["GetTarget"]
    assert inst.GetTargetRating(them) != r            # counted again
    assert ai_native.stats()["select"]["native"] == 2


def test_a_class_patched_after_a_native_call_is_seen_on_the_next(
        monkeypatch):
    """Review Focus 5: the remembered verdict of a type is dropped when the
    type (or a base) changes, so a patch made after the first native call
    sends the next one to the SDK."""
    pSet, ours, them, inst = _pair()
    other = _armed("Other")
    pSet.AddObjectToSet(other, "Other")
    other.SetTarget(them)
    inst.GetTargetRating(them)
    assert ai_native.stats()["select"]["native"] == 1
    from engine.appc.objects import ObjectClass
    monkeypatch.setattr(ObjectClass, "GetWorldForwardTG",
                        lambda self: TGPoint3(0.0, -1.0, 0.0))
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    monkeypatch.undo()
    monkeypatch.setattr(ShipClass, "GetTarget", lambda self: None)
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    monkeypatch.undo()
    assert inst.GetTargetRating(them).hex() == _sdk(inst, them).hex()
    s = ai_native.stats()["select"]
    assert (s["native"], s["reasons"]) == (2, {"surface": 2}), s


def test_a_shield_class_overriding_getshieldpercentage_is_honoured():
    """The shield, weapon and hull factors are the Python methods' own
    answers, so an override is honoured on the native path itself."""
    class Fixed(ShieldSubsystem):
        def GetShieldPercentage(self):
            return 0.125

    pSet, ours, them, inst = _pair()
    them._shield_subsystem = Fixed("Shield")
    r = inst.GetTargetRating(them)
    assert r.hex() == _sdk(inst, them).hex()
    them._shield_subsystem = ShieldSubsystem("Shield")
    assert inst.GetTargetRating(them) != r          # 1.0 vs 0.125
    s = ai_native.stats()["select"]
    assert s == dict(s, native=2, python=0), s


def test_missing_damage_ledger_raises_like_the_sdk():
    pSet, ours, them, inst = _pair()
    del inst.__dict__["dDamageReceived"]
    with pytest.raises(AttributeError) as sdk_err:
        _sdk(inst, them)
    with pytest.raises(AttributeError) as native_err:
        inst.GetTargetRating(them)
    assert str(native_err.value) == str(sdk_err.value)
    assert "dDamageReceived" in str(sdk_err.value)


def test_no_ship_returns_the_sdks_int():
    pSet, ours, them, inst = _pair()
    inst.pCodeAI = type("NoShip", (), {"GetShip": lambda self: None})()
    r = inst.GetTargetRating(them)
    assert r == -1 and type(r) is int
    s = ai_native.stats()["select"]
    assert s["native"] == 0 and s["python"] == 0, s


def test_switch_and_patch_send_the_call_to_the_sdk(monkeypatch):
    pSet, ours, them, inst = _pair()
    want = _sdk(inst, them).hex()
    monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "avoid,fire")
    assert inst.GetTargetRating(them).hex() == want
    monkeypatch.setenv("DAUNTLESS_NATIVE_AI", "select")
    assert inst.GetTargetRating(them).hex() == want
    # A mod patching the SDK method after the first native call: the next
    # call runs the patch.
    monkeypatch.setattr(pp.SelectTarget, "GetTargetRating",
                        lambda self, pTarget: 42.0)
    assert inst.GetTargetRating(them) == 42.0
    s = ai_native.stats()["select"]
    assert (s["native"], s["python"]) == (1, 2), s
    assert s["reasons"] == {"switch": 1, "not_stock": 1}, s
