"""The charging kernel's inputs, mirrored (native weapon state, Task 3; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.3).

K0 steps weapon charging and torpedo reloading in C++ from the mirror, so
every field it reads must equal the Python after EVERY writer: `_recharge_rate`
(energy weapons), `_reload_delay` and the two per-slot float lists
`_reload_timers` / `_reload_advanced_at` (tubes, a new FloatList field type),
the pulse watcher's check count `_watch_checks`, the phaser system's
`_power_level`, and the discharge-by-power-level table (a global). The slot
lists are mostly written IN PLACE (`list[i] = v`), which no descriptor sees:
each such writer pushes after mutating (the `_add_target` + `push_field`
precedent). Floats compare by float.hex(), -0.0 included.
"""
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
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.float_range_watcher import FloatRangeWatcher  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    PhaserBank, PhaserSystem, PulseWeapon, PulseWeaponSystem, TorpedoSystem,
    TorpedoTube,
)

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
SLOT_FIELDS = ("_reload_timers", "_reload_advanced_at")


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    nc.reset()
    passive_state.reset()


@pytest.fixture
def clock():
    """The game clock UpdateReload reads (App.g_kTimerManager._time)."""
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _tube(max_ready: int = 2, reload_delay: float = 40.0) -> TorpedoTube:
    from tests.helpers.torpedo_fixtures import arm
    system = TorpedoSystem("Torpedoes")
    arm(system)     # a ship and a slot-0 script: the tube's Fire launches
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = reload_delay
    tube._max_ready = max_ready
    tube._num_ready = max_ready
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _hexes(values):
    return [float(v).hex() for v in values]


def _assert_lists(tube):
    row = _dump(tube)
    for f in SLOT_FIELDS:
        got = row.get(f)
        want = tube.__dict__[f]
        assert got is not None and _hexes(got) == _hexes(want), (
            f"{f}: mirror {got!r} != python {want!r}")


def _assert_scalar(obj, field):
    got = _dump(obj).get(field)
    want = obj.__dict__[field]
    if isinstance(want, float):
        assert got is not None and float(got).hex() == want.hex(), (
            field, got, want)
    else:
        assert got == want, (field, got, want)


def _poison_lists(tube):
    """Write a sentinel into the mirror's slot lists, so only the writer
    under test can make them equal the Python again."""
    for f in SLOT_FIELDS:
        _h.combat_set_floats(_slot(tube), nc._fid(f), [1234.5])


def _failures_for(name, field):
    return [f for f in nc.audit_failures() if f == (name, field)]


# ── The slot-list writers ────────────────────────────────────────────────────

def _cool_both(tube, clock):
    clock(1.0)
    tube.SetNumReady(0)             # both slots cooling from t = 1


def _setup_loaded(tube, clock):
    clock(0.5)


def _setup_cooling_progress(tube, clock):
    _cool_both(tube, clock)
    clock(6.0)
    tube.UpdateReload(0.0)          # 5 s banked, nothing reloads (delay 40)


def _setup_mismatch(tube, clock):
    tube._max_ready = 3             # the slot lists are now 2 long: desynced


# (id, setup(tube, clock), write(tube, clock))
WRITERS = [
    ("_start_slot_cooldown", _setup_loaded,
     lambda t, c: t._start_slot_cooldown(12.5)),
    # (Fire is no Python writer of the lists any more: the kernel's launch
    # writes them in the mirror and logs them -- fire control native only,
    # M3; K1Launch.TubeLaunchIsLoggedWritesAndASpawnEntry and the dispatch
    # recording test_last_round_debits_like_python.)
    ("_sync_slots_to_num_ready demote", _setup_loaded,
     lambda t, c: (c(3.25), t.SetNumReady(0))),
    ("_sync_slots_to_num_ready promote", _setup_cooling_progress,
     lambda t, c: t.SetNumReady(1)),
    ("DecNumReady", _setup_loaded,
     lambda t, c: (c(4.75), t.DecNumReady())),
    ("_resize_slots", _setup_mismatch,
     lambda t, c: t._resize_slots()),
    ("ReloadTorpedo", _setup_cooling_progress,
     lambda t, c: t.ReloadTorpedo()),
    ("UpdateReload advance", _cool_both,
     lambda t, c: (c(7.5), t.UpdateReload(0.0))),
    ("UpdateReload reload", _cool_both,
     lambda t, c: (c(100.0), t.UpdateReload(0.0))),
    ("UpdateReload self-heal", _setup_mismatch,
     lambda t, c: t.UpdateReload(0.0)),
    ("UnloadTorpedo", _setup_loaded,
     lambda t, c: (c(9.5), t.UnloadTorpedo())),
]


@pytest.mark.parametrize("setup,write", [(s, w) for _, s, w in WRITERS],
                         ids=[n for n, _, _ in WRITERS])
def test_each_writer_pushes(clock, setup, write):
    nc.configure(ON)
    assert nc.enabled()
    tube = _tube()
    setup(tube, clock)
    _assert_lists(tube)
    before = {f: _hexes(tube.__dict__[f]) for f in SLOT_FIELDS}
    _poison_lists(tube)
    write(tube, clock)
    # Every list the writer changed must have been pushed (a list it left
    # alone still holds the sentinel: it had nothing to push).
    changed = [f for f in SLOT_FIELDS
               if _hexes(tube.__dict__[f]) != before[f]]
    assert changed, "the writer wrote nothing"
    row = _dump(tube)
    for f in changed:
        assert _hexes(row[f]) == _hexes(tube.__dict__[f]), (
            f"{f}: mirror {row[f]!r} != python {tube.__dict__[f]!r}")
    _assert_scalar(tube, "_num_ready")


def test_scalar_inputs_push(clock):
    nc.configure(ON)
    tube = _tube(reload_delay=33.25)
    _assert_scalar(tube, "_reload_delay")
    tube._reload_delay = -0.0
    _assert_scalar(tube, "_reload_delay")
    system = PhaserSystem("Phasers")
    bank = PhaserBank("Phaser 1")
    system.AddChildSubsystem(bank)
    _assert_scalar(bank, "_recharge_rate")
    bank._recharge_rate = 0.3
    _assert_scalar(bank, "_recharge_rate")
    _assert_scalar(system, "_power_level")
    assert _dump(system)["_power_level"] == PhaserSystem.PP_HIGH
    for level in (0, 1, 7, -3):
        system.SetPowerLevel(level)
        _assert_scalar(system, "_power_level")
    pulse = PulseWeapon("Disruptor 1")
    pulse._recharge_rate = 1.5
    _assert_scalar(pulse, "_recharge_rate")


def test_power_level_is_an_index(clock):
    """PHASER_DISCHARGE_BY_POWER_LEVEL[level] indexes a tuple: a float level
    raises TypeError in Python (rate 0.0), so the mirror must not read it as
    an int. It drops the row (the kernel hands that system to Python)."""
    nc.configure(ON)
    system = PhaserSystem("Phasers")
    system._power_level = True                  # a bool indexes: 1
    assert _dump(system)["_power_level"] == 1
    system._power_level = 1.0
    assert "_nslot" not in system.__dict__


def test_ship_property_copy_pushes():
    """ships.py copies RechargeRate / ReloadDelay off the hardpoint."""
    import importlib
    import sys
    nc.configure(ON)
    ship = App.ShipClass_Create("Galaxy K0")
    App.g_kModelPropertyManager.ClearLocalTemplates()
    try:
        mod = "ships.Hardpoints.galaxy"
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
        sys.modules[mod].LoadPropertySet(ship.GetPropertySet())
        ship.SetupProperties()
        banks = ship.GetPhaserSystem()
        tubes = ship.GetTorpedoSystem()
        assert banks.GetNumWeapons() and tubes.GetNumWeapons()
        for i in range(banks.GetNumWeapons()):
            bank = banks.GetWeapon(i)
            assert bank.__dict__["_recharge_rate"] > 0.0
            _assert_scalar(bank, "_recharge_rate")
        for i in range(tubes.GetNumWeapons()):
            tube = tubes.GetWeapon(i)
            assert tube.__dict__["_reload_delay"] > 0.0
            _assert_scalar(tube, "_reload_delay")
            _assert_lists(tube)
        _assert_scalar(banks, "_power_level")
    finally:
        App.g_kModelPropertyManager.ClearLocalTemplates()


# ── Review Focus 5: the switch turned on after in-place writes ───────────────

def test_resync_pushes_in_place_slot_lists(clock):
    assert not nc.enabled()
    tube = _tube(max_ready=3)
    clock(2.0)
    tube.UnloadTorpedo()                        # in place, switch off
    tube._reload_timers[1] = 0.0
    tube._reload_advanced_at[1] = -0.0          # sign must survive
    clock(5.0)
    tube.UpdateReload(0.0)
    tube._reload_delay = 17.5
    nc.configure(ON)                            # -> resync
    assert nc.enabled()
    _assert_lists(tube)
    _assert_scalar(tube, "_reload_delay")
    nc.audit_mirror()
    assert not [f for f in nc.audit_failures() if f[0] == "TorpedoTube"]


# ── The audit sees a missed push ─────────────────────────────────────────────

def test_audit_flags_missing_slot_push(clock):
    nc.configure(ON)
    tube = _tube()
    clock(3.0)
    tube.UnloadTorpedo()
    nc.audit_mirror()
    assert not _failures_for("TorpedoTube", "_reload_timers")
    assert not _failures_for("TorpedoTube", "_reload_advanced_at")
    tube._reload_timers[1] = 5.0                # in place, no push
    nc.audit_mirror()
    assert _failures_for("TorpedoTube", "_reload_timers")
    assert not _failures_for("TorpedoTube", "_reload_advanced_at")
    nc.audit_failures().clear()
    nc.push_field(tube, "_reload_timers")
    # -0.0 vs 0.0: equal by ==, different by hex.
    tube._reload_advanced_at[1] = -0.0
    nc.audit_mirror()
    assert not _failures_for("TorpedoTube", "_reload_timers")
    assert _failures_for("TorpedoTube", "_reload_advanced_at")


def test_unrepresentable_slot_list_drops_the_row():
    nc.configure(ON)
    tube = _tube()
    tube._reload_timers = ("not", "a list")
    assert "_nslot" not in tube.__dict__
    other = _tube()
    other._reload_advanced_at = [0.0, "1.5"]    # Python would raise on it
    assert "_nslot" not in other.__dict__


# ── The pulse watcher's check count ──────────────────────────────────────────

def test_watch_checks_follows_add_remove():
    nc.configure(ON)
    system = PulseWeaponSystem("Disruptors")
    weapon = PulseWeapon("Disruptor 1")
    system.AddChildSubsystem(weapon)
    watcher = weapon.GetChargeWatcher()
    assert _dump(weapon)["_watch_checks"] == 0
    ev = App.TGFloatEvent_Create()
    a = watcher.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BOTH, ev)
    assert _dump(weapon)["_watch_checks"] == 1
    b = watcher.AddRangeCheck(0.9, FloatRangeWatcher.FRW_ABOVE, ev)
    assert _dump(weapon)["_watch_checks"] == 2
    watcher.RemoveRangeCheck(a)
    assert _dump(weapon)["_watch_checks"] == 1
    watcher.RemoveRangeCheck(a)                 # already gone: no-op
    assert _dump(weapon)["_watch_checks"] == 1
    watcher.RemoveRangeCheck(b)
    assert _dump(weapon)["_watch_checks"] == 0
    nc.audit_mirror()
    assert not _failures_for("PulseWeapon", "_watch_checks")
    # A check added behind the watcher's back is caught by the audit.
    watcher._checks[99] = (0.25, FloatRangeWatcher.FRW_BOTH, ev)
    nc.audit_mirror()
    assert _failures_for("PulseWeapon", "_watch_checks")


def test_watcher_without_owner_unchanged():
    w = FloatRangeWatcher(0.5)
    assert "_owner" not in vars(w)
    i = w.AddRangeCheck(0.25, FloatRangeWatcher.FRW_BOTH,
                        App.TGFloatEvent_Create())
    w.RemoveRangeCheck(i)
    assert w._checks == {}


def test_switch_off_never_pushes(clock, monkeypatch):
    """Before the mirror is live (reset(), no configure()) no K0 write
    pushes. The "Fire" writer is left out: Fire is a fire-control call,
    which makes the mirror live itself (fire control native only, I1;
    test_native_switch_default.py::test_fire_control_before_configure_takes_
    the_native_path)."""
    calls = []

    def _rec(name):
        return lambda *a: calls.append((name, a))
    for name in ("combat_set_floats", "combat_push_scalar", "combat_set_f",
                 "combat_set_i"):
        monkeypatch.setattr(_h, name, _rec(name))
    assert not nc.enabled() and not nc._enabled
    tube = _tube()
    for name, setup, write in WRITERS:
        if name == "Fire":
            continue
        setup(tube, clock)
        write(tube, clock)
    tube._reload_delay = 3.0
    weapon = PulseWeapon("Disruptor 1")
    weapon._recharge_rate = 2.0
    i = weapon.GetChargeWatcher().AddRangeCheck(
        0.5, FloatRangeWatcher.FRW_BOTH, App.TGFloatEvent_Create())
    weapon.GetChargeWatcher().RemoveRangeCheck(i)
    PhaserSystem("Phasers").SetPowerLevel(0)
    assert calls == []
    assert weapon.__dict__["_watch_checks"] == 0
    assert not nc._enabled


# ── The discharge table ──────────────────────────────────────────────────────

def test_discharge_table_global(monkeypatch):
    nc.configure(ON)
    g = _h.combat_dump_globals()
    table = ws.PHASER_DISCHARGE_BY_POWER_LEVEL
    assert g["PHASER_DISCHARGE_LEN"] == len(table) == 3
    for i, v in enumerate(table):
        assert float(g["PHASER_DISCHARGE_%d" % i]).hex() == float(v).hex()
    monkeypatch.setattr(ws, "PHASER_DISCHARGE_BY_POWER_LEVEL",
                        (0.5, -0.0, 2.0, 4.0))
    nc._audit_globals()
    assert ("globals", "PHASER_DISCHARGE_0") in nc.audit_failures()
    assert ("globals", "PHASER_DISCHARGE_LEN") in nc.audit_failures()
    nc.audit_failures().clear()
    nc.push_globals()
    g = _h.combat_dump_globals()
    assert g["PHASER_DISCHARGE_LEN"] == 4
    assert float(g["PHASER_DISCHARGE_1"]).hex() == (-0.0).hex()
    nc._audit_globals()
    assert not nc.audit_failures()
    # A short table: the missing entries read 0.0, the length says so.
    monkeypatch.setattr(ws, "PHASER_DISCHARGE_BY_POWER_LEVEL", (0.75,))
    nc.push_globals()
    g = _h.combat_dump_globals()
    assert g["PHASER_DISCHARGE_LEN"] == 1
    assert g["PHASER_DISCHARGE_2"] == 0.0
