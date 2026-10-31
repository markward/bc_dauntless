"""Native can_detect is bit-identical to the Python in real missions
(native combat phase 1a, Task 7; spec
docs/superpowers/specs/2026-10-30-native-combat-step-design.md §3.2, §5).

Each sweep loads a real SDK mission headless three times -- the Python
reference (``DAUNTLESS_NATIVE_COMBAT=0``), native (``=1``) and native under
the audit (``DAUNTLESS_NATIVE_AUDIT=1``) -- moves ships through it with
public SDK calls only (``SetTranslateXYZ``, ``StartCloaking``,
``SetCondition``, ``RemoveObjectFromSet`` / ``AddObjectToSet``), and at every
step records, for the moving ship against every other ship in its set, in
both directions: can_detect, the lock-break latch, concealment_at,
effective_sensor_range (floats by ``float.hex()``), in_reach, jammed,
is_hidden_by_cloak and occlusion. The three traces must be equal with
``==``; the audit must record nothing (per call, and the whole mirror every
few steps); the native arm must have answered natively with no fallback.

Determinism: no GameLoop tick (AI draws on the unseeded module ``random``);
the game clock and module ``random`` reset before each load; the native
switch is configured AFTER the load, because constructing a GameLoop
re-reads the environment.

Two clocks, deliberately as today: the nebula drift reads
``App.g_kTimerManager.GetGameTime()``, which the shim's TGTimerManager does
not have, so drift is always 0.0 (a latent Python bug the native port copies,
not fixed here); occlusion reads the real game time.
"""
import math
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import contact_index
from engine.appc import native_combat as nc
from engine.appc import sensor_contacts
from engine.appc import sensor_detection as sd
from engine.appc import sensor_occlusion as occ
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, headless_mission

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_can_detect"),
    reason="native combat bindings not built")

OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
AUDIT = {"DAUNTLESS_NATIVE_AUDIT": "1"}
ARMS = (("off", OFF), ("on", ON), ("audit", AUDIT))

STEPS = 500
MIRROR_AUDIT_EVERY = 25

E3M2 = "Maelstrom.Episode3.E3M2.E3M2"
E1M2 = "Maelstrom.Episode1.E1M2.E1M2"

# can-detect-inputs.md §4.6: the two profile bands where the `sensors` column
# is not constant, so math.dist's exact rounding reaches the answer.
VESUVI_BAND = (116366.0, 130634.0)
BELARUZ_BAND = (124385.500214, 133303.891758)


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


def _hex(v) -> str:
    return float(v).hex()


def _load(mp, mission, env):
    """A fresh load of `mission`, native configured per `env` after it."""
    mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    nc.reset()
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.load(mission)
    host_loop._reset_sensor_state()      # the mission-swap sensor resets
    step_memo.forget()
    nc.configure(env)
    assert nc.enabled() is (env is not OFF)
    assert nc.audit_enabled() is (env is AUDIT)


def _move_to_set(obj, dest):
    """engine/systems/handoff.py's set change: the ordinary SDK pair."""
    src = obj.GetContainingSet()
    name = obj.GetName()
    if src is not None:
        src.RemoveObjectFromSet(name)
    dest.AddObjectToSet(obj, name)


def _create(ship_type, pSet, name, x, y, z):
    import loadspacehelper
    ship = loadspacehelper.CreateShip(ship_type, pSet, name, None)
    assert ship is not None, name
    ship.SetTranslateXYZ(x, y, z)
    ship.UpdateNodeOnly()
    return ship


def _pair(observer, target) -> tuple:
    """Every public sensor answer for one ordered pair. can_detect first:
    it is the call that moves the latch."""
    return (sd.can_detect(observer, target),
            sd._latched(observer, target),
            _hex(sd.concealment_at(target)),
            _hex(sd.effective_sensor_range(observer)),
            sd.in_reach(observer, target),
            sd.jammed(observer, target),
            sd.is_hidden_by_cloak(target),
            occ.blocked(observer, target))


def _row(mover, others) -> tuple:
    row = []
    for other in others:
        row.append(_pair(mover, other))
        row.append(_pair(other, mover))
    return tuple(row)


def _others(mover):
    return [s for s in contact_index.ships_in(mover.GetContainingSet())
            if s is not mover]


def _tick_clock(player=None) -> None:
    """One sim tick of game time; the host's per-frame contact pass for the
    player (it begins the occlusion tick)."""
    App.g_kTimerManager._time += TICK_DELTA
    if player is not None:
        sensor_contacts.tick(player, App.g_kUtopiaModule.GetGameTime())


def _maybe_audit_mirror(step) -> None:
    if nc.audit_enabled() and step % MIRROR_AUDIT_EVERY == 0:
        nc.audit_mirror()


def _run_arms(monkeypatch, scenario):
    """(trace per arm, counts per arm); asserts all three traces are equal,
    the audit is clean and the native arm really answered natively."""
    traces, counts = {}, {}
    failures = None
    for name, env in ARMS:
        with monkeypatch.context() as mp:
            traces[name] = scenario(mp, env)
            if env is AUDIT:
                nc.audit_mirror()
                failures = list(nc.audit_failures())
            counts[name] = nc.counts()
    ref = traces["off"]
    assert len(ref) > 0
    for name in ("on", "audit"):
        trace = traces[name]
        assert len(trace) == len(ref), name
        for step, (row, ref_row) in enumerate(zip(trace, ref)):
            assert row == ref_row, "%s differs from the Python at step %d" % (
                name, step)
    assert failures == [], failures
    assert counts["off"]["native_calls"] == 0, counts
    assert counts["on"]["native_calls"] > 0, counts
    assert counts["on"]["fallbacks"] == 0, counts
    assert counts["audit"]["native_calls"] > 0, counts
    assert counts["audit"]["fallbacks"] == 0, counts
    print("native-can-detect counts:", counts)
    return ref, counts


def _flat(trace):
    for row in trace:
        for pair in row:
            yield pair


# ── Profile bands (CDM §4.6) ─────────────────────────────────────────────────

def _vesuvi_scene(mp, env):
    _load(mp, E3M2, env)
    pSet = App.g_kSetManager.GetSet("Vesuvi4")
    return pSet, 122000.0, VESUVI_BAND


def _belaruz_scene(mp, env):
    # No SDK mission has ships in Belaruz 1 at load (E8M1 builds the set but
    # starts in Starbase 12), so the set is built by its own SDK module inside
    # E3M2's world and given three ships through loadspacehelper.
    _load(mp, E3M2, env)
    import Systems.Belaruz.Belaruz1 as belaruz1
    belaruz1.Initialize()
    pSet = belaruz1.GetSet()
    _create("Galaxy", pSet, "Belaruz Watch 1", 12.5, 0.0, 3.25)
    _create("Akira", pSet, "Belaruz Watch 2", -17.1, 844.7, -30.3)  # nebula core
    _create("Galor", pSet, "Belaruz Watch 3", 40.0, -3000.0, 0.0)
    return pSet, 128000.0, BELARUZ_BAND


def _band_steps(anchor_y, band):
    """STEPS set-local y values crossing the band with 500 GU either side,
    plus the band's three breakpoints exactly."""
    lo, hi = band[0] - 500.0 - anchor_y, band[1] + 500.0 - anchor_y
    ys = [lo + (hi - lo) * k / (STEPS - 1) for k in range(STEPS)]
    for r in (band[0], (band[0] + band[1]) / 2.0, band[1]):
        ys.append(r - anchor_y)
    return ys


@pytest.mark.parametrize("scene", ("vesuvi", "belaruz"))
def test_profile_band_sweep(monkeypatch, scene):
    build = {"vesuvi": _vesuvi_scene, "belaruz": _belaruz_scene}[scene]

    def scenario(mp, env):
        pSet, anchor_y, band = build(mp, env)
        player = App.Game_GetCurrentPlayer()
        _move_to_set(player, pSet)
        trace = []
        for step, y in enumerate(_band_steps(anchor_y, band)):
            # Off-axis x and z, so the profile radius is a real 3-term
            # math.dist, not |y|.
            player.SetTranslateXYZ(37.3, y, -12.9)
            _tick_clock(player)
            trace.append(_row(player, _others(player)))
            _maybe_audit_mirror(step)
        return trace

    trace, _ = _run_arms(monkeypatch, scenario)
    # The sweep reached the band: the player's concealment took many values
    # (the profile term is interpolated, not a constant row).
    player_conceal = {row[1][2] for row in trace}
    assert len(player_conceal) > 50, len(player_conceal)
    latches = {pair[1] for pair in _flat(trace)}
    if scene == "vesuvi":
        # Vesuvi 4's MetaNebula breaks locks on the debris: both latch states.
        assert latches == {False, True}


# ── A MetaNebula set (Multi5) ────────────────────────────────────────────────

def test_metanebula_sweep(monkeypatch):
    """Systems/Multi5: four MetaNebulae. The player crosses them on two
    lines; watchers sit outside, inside and beyond them, two of them far
    enough that the shrunk range decides. The latch must take both values
    (the hysteresis band is crossed)."""
    def scenario(mp, env):
        _load(mp, E1M2, env)
        import Systems.Multi5.Multi5 as multi5
        multi5.Initialize()
        pSet = multi5.GetSet()
        player = App.Game_GetCurrentPlayer()
        _move_to_set(player, pSet)
        _create("Galaxy", pSet, "Watch A", -300.0, 0.0, 0.0)
        _create("Akira", pSet, "Watch B", 250.0, 0.0, 0.0)
        _create("BirdOfPrey", pSet, "Watch C", 600.0, 125.0, 0.0)
        # Far watchers: the player's distance to them crosses their range
        # as the nebula shrinks it (r * (1 - CONCEAL_K * concealment)).
        _create("Galaxy", pSet, "Watch D", -1700.0, 0.0, 0.0)
        _create("Akira", pSet, "Watch E", 300.0, 1700.0, 0.0)
        half = STEPS // 2
        path = ([(-400.0 + 1300.0 * k / (half - 1), 0.0, 0.0)
                 for k in range(half)]
                + [(900.0 - 1300.0 * k / (half - 1), 125.0, 125.0)
                   for k in range(half)])
        trace = []
        for step, (x, y, z) in enumerate(path):
            player.SetTranslateXYZ(x, y, z)
            _tick_clock(player)
            trace.append(_row(player, _others(player)))
            _maybe_audit_mirror(step)
        return trace

    trace, _ = _run_arms(monkeypatch, scenario)
    pairs = list(_flat(trace))
    assert {p[1] for p in pairs} == {False, True}
    assert {p[0] for p in pairs} == {False, True}
    assert {p[5] for p in pairs} == {False, True}          # jammed
    assert max(float.fromhex(p[2]) for p in pairs) >= sd.LOCK_BREAK_T


# ── SetScale rocks (E1M2) ────────────────────────────────────────────────────

def test_rock_field_sweep(monkeypatch):
    """E1M2's Vesuvi 6: six SetScale(3) debris rocks, four of them major
    occluders, beside the Facility. The player flies lines out from the
    Facility through each major rock and beyond, weaving across it, so its
    line of sight to the Facility and the rocks goes in and out of shadow."""
    def scenario(mp, env):
        _load(mp, E1M2, env)
        player = App.Game_GetCurrentPlayer()
        pSet = player.GetContainingSet()
        facility = App.ShipClass_GetObject(pSet, "Facility")
        rocks = [App.ShipClass_GetObject(pSet, "Debris%d" % i)
                 for i in (1, 3, 4, 5)]
        fx, fy, fz = _xyz(facility)
        per = STEPS // len(rocks)
        trace = []
        step = 0
        for rock in rocks:
            rx, ry, rz = _xyz(rock)
            dx, dy, dz = rx - fx, ry - fy, rz - fz
            # A unit vector across the line, for the weave.
            px, py, pz = _unit(_cross((dx, dy, dz), (0.0, 0.0, 1.0)))
            for k in range(per):
                t = 1.2 + 5.0 * k / (per - 1)
                w = 12.0 * math.sin(k * 0.37)
                player.SetTranslateXYZ(fx + t * dx + w * px,
                                       fy + t * dy + w * py,
                                       fz + t * dz + w * pz)
                _tick_clock(player)
                trace.append(_row(player, _others(player)))
                _maybe_audit_mirror(step)
                step += 1
        return trace

    trace, _ = _run_arms(monkeypatch, scenario)
    blocked = {p[7] for p in _flat(trace)}
    assert blocked == {False, True}


def _xyz(obj):
    loc = obj.GetWorldLocation()
    return loc.x, loc.y, loc.z


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


# ── The cloak bubble ─────────────────────────────────────────────────────────

def test_cloak_bubble_sweep(monkeypatch):
    """E3M2's two Warbirds in deep space. Chairo cloaks (recorded through
    the transition), T'Awsun sweeps out across the bubble, again with its
    sensors at 37% condition (a smaller bubble), then Chairo decloaks."""
    def scenario(mp, env):
        _load(mp, E3M2, env)
        pSet = App.g_kSetManager.GetSet("DeepSpace")
        chairo = App.ShipClass_GetObject(pSet, "Chairo")
        tawsun = App.ShipClass_GetObject(pSet, "T'Awsun")
        cloak = chairo.GetCloakingSubsystem()
        cx, cy, cz = _xyz(chairo)
        ux, uy, uz = _unit((0.6, -0.7, 0.3))
        trace = []
        step = [0]

        def at(d):
            tawsun.SetTranslateXYZ(cx + d * ux, cy + d * uy, cz + d * uz)

        def record():
            App.g_kTimerManager._time += TICK_DELTA
            game_loop._update_ship_subsystems()
            trace.append(_row(tawsun, [chairo]) + (cloak.IsCloaked(),
                                                   cloak.IsCloaking()))
            _maybe_audit_mirror(step[0])
            step[0] += 1

        at(10.0)
        cloak.StartCloaking()
        for _ in range(STEPS):
            record()
            if cloak.IsCloaked():
                break
        assert cloak.IsCloaked()
        for k in range(250):
            at(0.5 + 49.5 * k / 249)
            record()
        sensors = tawsun.GetSensorSubsystem()
        sensors.SetCondition(sensors.GetMaxCondition() * 0.37)
        for k in range(125):
            at(50.0 - 49.5 * k / 124)
            record()
        at(25.0)
        cloak.StopCloaking()
        for _ in range(STEPS):
            record()
            if not cloak.IsCloaked() and not cloak.IsCloaking() \
                    and not cloak.IsDecloaking():
                break
        return trace

    trace, _ = _run_arms(monkeypatch, scenario)
    cloaked_answers = {row[0][0] for row in trace if row[-2]}
    assert cloaked_answers == {False, True}     # the sweep crossed the bubble
