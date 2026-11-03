"""Native fire gates vs the Python they port (native combat phase 1b, Task 3;
native/src/combat/src/fire_gates.cc).

Each test builds real ships with native combat on, drives the state of real
banks, cannons, tractor beams and tubes through their setters (charge,
condition, parent condition, disabled percentage, TurnOff, power setting,
cooldown, ready count, last fire time, ammo, skew) from a seeded
random.Random(20261031), and compares `combat_test_can_fire(leaf, now)` with
Python's own `CanFire()` run on the same state: `ok` against the answer,
`clear_depleted` against whether Python's CanFire flipped `_depleted` True ->
False (native never writes it; Task 4 logs the write). Floats are compared by
.hex(). K1M section 1.4 / 3 (F3-F6) is the specification.

`now` is `weapon_subsystems._game_time()` (App.g_kUtopiaModule.GetGameTime()),
the clock Python's tube CanFire reads twice; the tests pin it with a
monkeypatch so both arms read the same value.
"""
import importlib
import math
import random
import sys

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_test_can_fire"),
    reason="native fire gate bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SEED = 20261031
CASES = 1000
NAN = float("nan")
INF = float("inf")


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


def _ship(name, hardpoint):
    ship = App.ShipClass_Create(name)
    _load_hardpoint(ship, hardpoint)
    return ship


class World:
    pass


@pytest.fixture
def world(monkeypatch):
    nc.configure(ON)
    assert nc.enabled()
    w = World()
    w.clock = [0.0]
    monkeypatch.setattr(ws, "_game_time", lambda: w.clock[0])
    w.set = App.SetClass_Create()
    App.g_kSetManager.AddSet(w.set, "native_gates")
    w.galaxy = _ship("Galaxy1", "galaxy")
    w.vorcha = _ship("Vorcha1", "vorcha")
    for ship in (w.galaxy, w.vorcha):
        w.set.AddObjectToSet(ship, ship.GetName())
    w.phasers = list(w.galaxy._phaser_system._children)
    w.tubes = list(w.galaxy._torpedo_system._children)
    w.tractors = list(w.galaxy._tractor_beam_system._children)
    w.cannons = list(w.vorcha._pulse_weapon_system._children)
    assert w.phasers and w.tubes and w.tractors and w.cannons
    w.systems = [w.galaxy._phaser_system, w.galaxy._torpedo_system,
                 w.galaxy._tractor_beam_system, w.vorcha._pulse_weapon_system]
    try:
        yield w
    finally:
        App.g_kSetManager.DeleteSet("native_gates")


def _slot(obj):
    return obj.__dict__["_nslot"] if obj is not None else -1


def _ship_of(w, leaf):
    return w.vorcha if leaf in w.cannons else w.galaxy


def _native(leaf, now):
    return _h.combat_test_can_fire(_slot(leaf), now)


def _python(leaf, now, w):
    """(ok, flipped) from Python's CanFire on the current state. `_depleted`
    is restored, so the two arms see one state."""
    w.clock[0] = now
    energy = leaf in w.phasers or leaf in w.tractors or leaf in w.cannons
    before = leaf._depleted if energy else False
    ok = bool(leaf.CanFire())
    flipped = bool(before) and not leaf._depleted if energy else False
    if energy:
        leaf._depleted = before
    return ok, flipped


def _same(w, leaf, now, why=""):
    got = _native(leaf, now)
    want = _python(leaf, now, w)
    assert tuple(got) == want, (why, got, want)
    return want


def _heal(*subs):
    """Full health by GetMaxCondition (the property max wins over
    _max_condition), so the percentages are exactly 1.0."""
    for sub in subs:
        sub._condition = sub.GetMaxCondition()


def _rand_charge(rng, hi):
    r = rng.random()
    if r < 0.15:
        return 0.0
    if r < 0.2:
        return NAN
    if r < 0.25:
        return hi
    return rng.uniform(0.0, hi)


def _rand_cond(rng, mx):
    r = rng.random()
    if r < 0.1:
        return 0.0
    if r < 0.15:
        return NAN
    if r < 0.2:
        return mx
    return rng.uniform(0.0, mx * 1.1)


def _randomize_common(rng, w, leaf):
    parent = leaf._parent_subsystem
    ship = _ship_of(w, leaf)
    ship._dead = rng.random() < 0.08
    if rng.random() < 0.8:
        parent.TurnOn()
    else:
        parent.TurnOff()
    leaf._condition = _rand_cond(rng, leaf._max_condition)
    parent._condition = _rand_cond(rng, parent._max_condition)
    leaf.SetDisabledPercentage(rng.choice((0.0, 0.25, 0.5, 0.9, 1.0,
                                           rng.random())))
    return parent


def _randomize_energy(rng, w, leaf):
    _randomize_common(rng, w, leaf)
    leaf.SetPowerSetting(rng.choice((0, 1, 2)))
    leaf._max_charge = rng.choice((5.0, 8.0, 10.0))
    leaf.SetChargeLevel(_rand_charge(rng, leaf._max_charge))
    leaf._min_firing_charge = rng.choice((0.0, 0.45, 1.2, 3.6,
                                          rng.uniform(0, 5)))
    leaf._normal_discharge_rate = rng.choice((0.5, 1.0, 2.0, rng.uniform(0, 3)))
    leaf._depleted = rng.random() < 0.5
    leaf._cooldown_remaining = rng.choice((0.0, 0.0, 0.1, NAN, -1.0))


def _randomize_tube(rng, w, leaf):
    parent = _randomize_common(rng, w, leaf)
    base = rng.uniform(0.0, 100.0)
    parent._last_system_fire_time = rng.choice(
        (-1000.0, base, base - 0.5, base - 0.4, base - 0.6, NAN))
    w.clock[0] = base
    leaf._skew_fire = rng.random() < 0.3
    leaf._num_ready = rng.choice((0, 0, 1, 2, 3))
    leaf._last_fire_time = rng.choice((base, base - 1.0, base - 5.0, -1000.0))
    leaf._immediate_delay = rng.choice((0.0, 0.25, 1.0, 5.0, NAN))
    ammo = parent.GetCurrentAmmoType()
    if ammo is not None:
        ammo._unlimited = rng.random() < 0.4
        ammo._available = rng.choice((0, 0, 1, 5))
        slots = sorted(parent._ammo_by_slot)
        parent._selected_slot = rng.choice([None] + slots + [99])
    return base


# ── The depleted latch (Review Focus 3) ──────────────────────────────────────

def test_charge_gate_depleted_latch(world):
    w, rng = world, random.Random(SEED)
    seen = set()
    for i in range(CASES):
        leaf = rng.choice(w.phasers + w.tractors)
        _randomize_energy(rng, w, leaf)
        now = rng.uniform(0, 100)
        ok, flipped = _same(w, leaf, now, i)
        seen.add((ok, flipped))
    assert seen == {(True, False), (False, False), (True, True), (False, True)}


def test_depleted_latch_exact_boundaries(world):
    w = world
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    bank._condition = bank._max_condition
    parent._condition = parent._max_condition
    bank.SetDisabledPercentage(0.0)
    bank._max_charge = 10.0
    bank._min_firing_charge = 3.0
    for level in (0.0, 2.999999, 3.0, math.nextafter(3.0, 0.0),
                  math.nextafter(3.0, 9.0), NAN):
        for depleted in (False, True):
            bank.SetChargeLevel(level)
            bank._depleted = depleted
            _same(w, bank, 1.0, (level, depleted))
    # level == min, depleted: restarts (the compare is `<`) and flips.
    bank.SetChargeLevel(3.0)
    bank._depleted = True
    assert tuple(_native(bank, 1.0)) == (True, True)
    # MinFiringCharge 0 with an empty bank: clears the latch yet cannot fire.
    bank._min_firing_charge = 0.0
    bank.SetChargeLevel(0.0)
    bank._depleted = True
    assert tuple(_native(bank, 1.0)) == (False, True)
    _same(w, bank, 1.0)


def test_latch_is_untouched_when_an_earlier_gate_refuses(world):
    """Parent off, ship dead: Python returns before _charge_gate, so the latch
    stays set and the native answer must not report a clear."""
    w = world
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    bank._max_charge = 10.0
    bank._min_firing_charge = 1.0
    bank.SetChargeLevel(5.0)
    bank._depleted = True
    parent.TurnOff()
    assert tuple(_native(bank, 1.0)) == (False, False)
    _same(w, bank, 1.0, "off")
    parent.TurnOn()
    w.galaxy._dead = True
    assert tuple(_native(bank, 1.0)) == (False, False)
    _same(w, bank, 1.0, "dead")
    w.galaxy._dead = False
    _same(w, bank, 1.0, "alive")


def test_latch_clears_even_if_a_later_gate_refuses(world):
    """The condition product runs after the latch: Python has already cleared
    `_depleted` when it returns 0."""
    w = world
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    bank._max_charge = 10.0
    bank._min_firing_charge = 1.0
    bank.SetChargeLevel(5.0)
    bank._depleted = True
    bank._condition = 0.0
    assert tuple(_native(bank, 1.0)) == (False, True)
    _same(w, bank, 1.0)


# ── The condition product (F3) ───────────────────────────────────────────────

def test_condition_product_nan_passes(world):
    """GetConditionPercentage is max(0.0, min(1.0, cond / mx)); min(1.0, NaN)
    is 1.0, so a NaN condition (or max) reads as FULL health: it clears a
    threshold a condition of 0 does not."""
    w, rng = world, random.Random(SEED + 1)
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    bank._max_charge = 10.0
    bank.SetChargeLevel(5.0)
    bank._depleted = False
    bank.SetDisabledPercentage(0.5)
    for field in ("bank_cond", "parent_cond", "bank_max", "parent_max"):
        bank._max_condition = parent._max_condition = 100.0
        _heal(bank, parent)
        target = bank if field.startswith("bank") else parent
        if field.endswith("cond"):
            target._condition = NAN
        else:
            target._max_condition = NAN
        assert _same(w, bank, 1.0, field) == (True, False), field
        # ... where a real zero blocks (0 * 1.0 <= 0.5).
        if field.endswith("cond"):
            target._condition = 0.0
            assert _same(w, bank, 1.0, field + " zero") == (False, False)
    # Without the property template, _max_condition is the max; negative or
    # zero gives 0.0 (`mx <= 0`) and NaN reads as full health.
    saved = (bank._property, parent._property)
    bank._property = parent._property = None
    try:
        for bmax, pmax in ((100.0, -1.0), (0.0, 100.0), (NAN, 100.0),
                           (100.0, NAN), (100.0, 100.0)):
            bank._max_condition, parent._max_condition = bmax, pmax
            bank._condition = parent._condition = 100.0
            _same(w, bank, 1.0, ("noprop", bmax, pmax))
        # The clamp above 1.0 and every NaN mix, with and without the template.
        for _ in range(CASES):
            bank._max_condition = rng.choice((0.0, 100.0, NAN, -3.0))
            parent._max_condition = rng.choice((0.0, 100.0, 300.0, NAN))
            bank._condition = rng.choice((0.0, 50.0, 100.0, 400.0, NAN))
            parent._condition = rng.choice((0.0, 50.0, 300.0, 1000.0, NAN))
            bank.SetDisabledPercentage(rng.choice((0.0, 0.25, 0.5, 1.0, 2.0)))
            _same(w, bank, 1.0)
    finally:
        bank._property, parent._property = saved
    for _ in range(CASES):
        bank._max_condition = rng.choice((0.0, 100.0, NAN, -3.0))
        parent._max_condition = rng.choice((0.0, 100.0, 300.0, NAN))
        bank._condition = rng.choice((0.0, 50.0, 100.0, 400.0, NAN))
        parent._condition = rng.choice((0.0, 50.0, 300.0, 1000.0, NAN))
        bank.SetDisabledPercentage(rng.choice((0.0, 0.25, 0.5, 1.0, 2.0)))
        _same(w, bank, 1.0)


def test_condition_product_equal_threshold_blocks(world):
    """`disabled >= combined` is inclusive."""
    w = world
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    bank._max_charge = 10.0
    bank.SetChargeLevel(5.0)
    bank._depleted = False
    _heal(bank, parent)
    parent._condition = parent.GetMaxCondition() * 0.5   # combined = 1.0 * 0.5
    bank.SetDisabledPercentage(0.5)
    assert tuple(_native(bank, 1.0)) == (False, False)
    _same(w, bank, 1.0)
    bank.SetDisabledPercentage(math.nextafter(0.5, 0.0))
    assert tuple(_native(bank, 1.0)) == (True, False)
    _same(w, bank, 1.0)


# ── Pulse (F4) ───────────────────────────────────────────────────────────────

def test_pulse_affordability_1e9_boundary(world):
    w, rng = world, random.Random(SEED + 2)
    cannon = w.cannons[0]
    parent = cannon._parent_subsystem
    parent.TurnOn()
    w.vorcha._dead = False
    cannon._condition = cannon._max_condition
    parent._condition = parent._max_condition
    cannon.SetDisabledPercentage(0.0)
    cannon._max_charge = 100.0
    cannon._cooldown_remaining = 0.0
    results = set()
    for setting in (0, 1, 2):
        cannon.SetPowerSetting(setting)
        for rate in (0.5, 1.0, 1.2, 3.6, 0.1, rng.uniform(0.1, 3.0)):
            cannon._normal_discharge_rate = rate
            cost = cannon._shot_cost()
            edge = cost - 1e-9
            for level in (edge, math.nextafter(edge, 0.0),
                          math.nextafter(edge, 1e9), cost, 0.0, NAN,
                          cost - 2e-9):
                cannon.SetChargeLevel(level)
                results.add(_same(w, cannon, 1.0, (setting, rate, level)))
    assert (True, False) in results and (False, False) in results
    # The pulse gate has no latch: a set `_depleted` is neither read nor cleared.
    cannon.SetPowerSetting(1)
    cannon._normal_discharge_rate = 1.0
    cannon.SetChargeLevel(5.0)
    cannon._depleted = True
    assert tuple(_native(cannon, 1.0)) == (True, False)
    _same(w, cannon, 1.0)
    # Cooldown refuses first.
    for cd in (1e-300, 0.1, NAN, 0.0, -0.0, -1.0):
        cannon._cooldown_remaining = cd
        _same(w, cannon, 1.0, cd)


def test_pulse_random_states_match(world):
    w, rng = world, random.Random(SEED + 3)
    seen = set()
    for i in range(CASES):
        leaf = rng.choice(w.cannons)
        _randomize_energy(rng, w, leaf)
        seen.add(_same(w, leaf, rng.uniform(0, 100), i))
    assert (True, False) in seen and (False, False) in seen


# ── Torpedo tube (F6) ────────────────────────────────────────────────────────

def test_tube_stagger_exclusive_boundary(world):
    w = world
    tube = w.tubes[0]
    parent = tube._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    tube._condition = tube._max_condition
    tube.SetDisabledPercentage(0.0)
    tube._num_ready = 1
    tube._last_fire_time = -1000.0
    tube._immediate_delay = 0.0
    ammo = parent.GetCurrentAmmoType()
    if ammo is not None:
        ammo._unlimited = True
    parent._last_system_fire_time = 10.0
    tube._skew_fire = False
    # now - last == 0.5 exactly: blocked (`<= 0.5`).
    assert tuple(_native(tube, 10.5)) == (False, False)
    _same(w, tube, 10.5, "exactly 0.5")
    # The next double above: allowed.
    above = math.nextafter(10.5, 100.0)
    assert tuple(_native(tube, above)) == (True, False)
    _same(w, tube, above, "just above")
    below = math.nextafter(10.5, 0.0)
    assert tuple(_native(tube, below)) == (False, False)
    _same(w, tube, below, "just below")
    # Skew-fire tubes are exempt, at the boundary and inside it.
    tube._skew_fire = True
    for now in (10.0, 10.25, 10.5, below):
        assert tuple(_native(tube, now)) == (True, False)
        _same(w, tube, now, ("skew", now))
    # A NaN stamp never blocks.
    tube._skew_fire = False
    parent._last_system_fire_time = NAN
    assert tuple(_native(tube, 10.5)) == (True, False)
    _same(w, tube, 10.5, "nan stamp")
    # No stamp at all: -1000.0.
    parent._last_system_fire_time = -1000.0
    _same(w, tube, 0.0, "default stamp")


def test_tube_immediate_delay_boundary_and_ammo(world):
    w = world
    tube = w.tubes[0]
    parent = tube._parent_subsystem
    parent.TurnOn()
    w.galaxy._dead = False
    tube._condition = tube._max_condition
    tube.SetDisabledPercentage(0.0)
    tube._num_ready = 1
    tube._skew_fire = True
    parent._last_system_fire_time = -1000.0
    tube._last_fire_time = 20.0
    tube._immediate_delay = 2.5
    ammo = parent.GetCurrentAmmoType()
    assert ammo is not None
    ammo._unlimited = True
    # now - last == delay: allowed (`<` is strict).
    assert tuple(_native(tube, 22.5)) == (True, False)
    _same(w, tube, 22.5, "== delay")
    below = math.nextafter(22.5, 0.0)
    assert tuple(_native(tube, below)) == (False, False)
    _same(w, tube, below, "< delay")
    # Finite magazines: empty blocks, one round passes; unlimited never gates.
    ammo._unlimited = False
    for avail in (0, 1, 3):
        ammo._available = avail
        _same(w, tube, 30.0, avail)
    assert tuple(_native(tube, 30.0)) == (True, False)
    ammo._available = 0
    assert tuple(_native(tube, 30.0)) == (False, False)
    ammo._unlimited = True
    assert tuple(_native(tube, 30.0)) == (True, False)
    # Disabled tube, no rounds ready.
    tube._num_ready = 0
    _same(w, tube, 30.0, "none ready")
    tube._num_ready = 1
    tube._condition = 0.0
    _same(w, tube, 30.0, "disabled")


def test_tube_with_no_ammo_types_is_not_gated(world):
    w = world
    tube = w.tubes[0]
    parent = tube._parent_subsystem
    saved = dict(parent._ammo_by_slot)
    parent._ammo_by_slot.clear()
    nc.push_field(parent, "_ammo_by_slot")
    try:
        parent.TurnOn()
        w.galaxy._dead = False
        tube._condition = tube._max_condition
        tube._num_ready = 1
        tube._skew_fire = True
        tube._immediate_delay = 0.0
        _same(w, tube, 5.0, "no ammo")
        assert tuple(_native(tube, 5.0)) == (True, False)
    finally:
        parent._ammo_by_slot.update(saved)
        nc.push_field(parent, "_ammo_by_slot")


def test_tube_with_a_none_ammo_slot_is_not_gated(world):
    """A slot holding None: GetCurrentAmmoType() is None, so Python's
    _ammo_exhausted is False (no ammo configured never gates). The mirror
    holds it as -1 (None), and the native gate answers the same, never
    falling back."""
    w = world
    tube = w.tubes[0]
    parent = tube._parent_subsystem
    saved = dict(parent._ammo_by_slot)
    parent._ammo_by_slot.clear()
    parent._ammo_by_slot[0] = None
    nc.push_field(parent, "_ammo_by_slot")
    try:
        assert _h.combat_dump(_slot(parent))["_ammo_by_slot"] == [0, -1]
        parent.TurnOn()
        w.galaxy._dead = False
        tube._condition = tube._max_condition
        tube._num_ready = 1
        tube._skew_fire = True
        tube._immediate_delay = 0.0
        _same(w, tube, 5.0, "None slot")
        assert tuple(_native(tube, 5.0)) == (True, False)
        nc.audit_mirror()
        assert nc.audit_failures() == []
    finally:
        parent._ammo_by_slot.clear()
        parent._ammo_by_slot.update(saved)
        nc.push_field(parent, "_ammo_by_slot")


def test_tube_random_states_match(world):
    w, rng = world, random.Random(SEED + 4)
    seen = set()
    for i in range(CASES):
        tube = rng.choice(w.tubes)
        base = _randomize_tube(rng, w, tube)
        now = base + rng.choice((0.0, 0.25, 0.5, 0.75, 1.0, 5.0))
        seen.add(_same(w, tube, now, i))
    assert (True, False) in seen and (False, False) in seen


def test_tractor_random_states_match(world):
    w, rng = world, random.Random(SEED + 5)
    seen = set()
    for i in range(CASES):
        leaf = rng.choice(w.tractors)
        _randomize_energy(rng, w, leaf)
        seen.add(_same(w, leaf, 1.0, i))
    assert (True, False) in seen and (False, False) in seen


# ── Fallbacks ────────────────────────────────────────────────────────────────

def test_stub_is_dead_ship_falls_back(world):
    w = world
    bank = w.phasers[0]
    parent = bank._parent_subsystem
    parent.TurnOn()
    _h.combat_set_i(_slot(w.galaxy), nc._fid("has_real_is_dead"), 0)
    with pytest.raises(ValueError):
        _native(bank, 1.0)
    # Parent off returns before the ship is read, as in Python.
    parent.TurnOff()
    assert tuple(_native(bank, 1.0)) == (False, False)
    _h.combat_set_i(_slot(w.galaxy), nc._fid("has_real_is_dead"), 1)
    parent.TurnOn()
    _native(bank, 1.0)


def test_unsupported_kinds_and_stale_handles_throw(world):
    w = world
    with pytest.raises(ValueError):
        _native(w.galaxy._phaser_system, 1.0)         # a system, not a leaf
    with pytest.raises(ValueError):
        _h.combat_test_can_fire(_slot(w.galaxy), 1.0)  # an Object
    with pytest.raises(ValueError):
        _h.combat_test_weapon_system_offline(_slot(w.galaxy))


# ── _is_offline for weapon systems (F5) ──────────────────────────────────────

def test_weapon_system_offline_matches(world):
    w, rng = world, random.Random(SEED + 6)
    seen = {True: 0, False: 0}
    subjects = w.systems + w.phasers + w.tubes + w.tractors + w.cannons
    for i in range(CASES * 2):
        syst = rng.choice(w.systems)
        ship = w.galaxy if syst is not w.systems[3] else w.vorcha
        ship._dead = rng.random() < 0.1
        ship._dying = rng.random() < 0.1
        ship._life_time = rng.choice((1e9, 1e9, 1e9, 0.5, 1e6 - 1.0, 1e6))
        for obj in [syst] + list(syst._children):
            obj._condition = rng.choice((obj._max_condition, 0.0, NAN,
                                         obj._max_condition * 0.1,
                                         obj._max_condition * 0.3))
            obj._destroyed = rng.random() < 0.1
            obj._radiation_out = rng.choice((False, False, False, True, 1))
            obj.SetDisabledPercentage(rng.choice((0.0, 0.25, 0.5, 1.0)))
        if rng.random() < 0.3:                    # mostly all-children cases
            for c in syst._children:
                c._condition = 0.0 if rng.random() < 0.7 else c._condition
        syst._radiation_out = rng.choice((False, True, 1, False))
        subject = rng.choice(subjects) if i % 3 == 0 else syst
        want = bool(ss._is_offline(subject))
        got = _h.combat_test_weapon_system_offline(_slot(subject))
        assert got == want, (i, subject)
        seen[want] += 1
    assert seen[True] > 50 and seen[False] > 50


def test_weapon_system_offline_aggregate_rules(world):
    w = world
    syst = w.galaxy._phaser_system
    ship = w.galaxy
    ship._dead = ship._dying = False
    ship._life_time = 1e9
    for obj in [syst] + list(syst._children):
        obj._condition = obj._max_condition
        obj._destroyed = False
        obj._radiation_out = False
        obj.SetDisabledPercentage(0.25)
    assert _h.combat_test_weapon_system_offline(_slot(syst)) is False
    # One child healthy keeps the system online even with the others disabled.
    for c in syst._children[:-1]:
        c._condition = 0.0
    assert bool(ss._is_offline(syst)) is False
    assert _h.combat_test_weapon_system_offline(_slot(syst)) is False
    syst._children[-1]._condition = 0.0
    assert bool(ss._is_offline(syst)) is True
    assert _h.combat_test_weapon_system_offline(_slot(syst)) is True
    # A destroyed ship is out of action whatever the children say.
    for c in syst._children:
        c._condition = c._max_condition
    ship._dying = True
    assert bool(ss._is_offline(syst)) is True
    assert _h.combat_test_weapon_system_offline(_slot(syst)) is True
    ship._dying = False
    # `_radiation_out` counts only for the literal True.
    syst._radiation_out = 1
    assert _h.combat_test_weapon_system_offline(_slot(syst)) == bool(
        ss._is_offline(syst))
    syst._radiation_out = True
    assert _h.combat_test_weapon_system_offline(_slot(syst)) is True
    syst._radiation_out = False
    # A bank is offline through its parent system's radiation outage.
    bank = syst._children[0]
    syst._radiation_out = True
    assert _h.combat_test_weapon_system_offline(_slot(bank)) is True
    assert bool(ss._is_offline(bank)) is True


def test_pulse_cost_constants_are_pushed_from_python(world):
    dumped = _h.combat_dump_globals()
    for i, scale in enumerate(ws.PULSE_COST_SCALE_BY_POWER_SETTING):
        assert dumped["PULSE_COST_SCALE_%d" % i].hex() == float(scale).hex()
