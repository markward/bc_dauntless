"""The native-vs-SDK A/B harness for the native stock preprocessors (phase 6
AI part 2; plan docs/superpowers/plans/2026-11-07-phase6-ai-p2-native-
preprocessors.md, Task 1).

``run_ab(scene, ticks)`` runs one seeded scene TWICE, each in its own
subprocess so no module state can leak from one side to the other:
``DAUNTLESS_NATIVE_AI=0`` (every preprocessor runs the SDK Python) and the
variable unset (all native). Each child is this file's ``test_child`` run by
pytest (the project's conftest is what makes the SDK importable), records every
tick with the golden-fight recorder (tests/helpers/golden_fight.py: poses,
weapon state, events, calls, presentation, stage rows) or, for the scenes that
are not a combat_stress fight, a pose / hull / target digest plus the state of
every RNG stream at the end, and writes the serialised record and the native
counters (``ai_native.stats()``) for the parent.

The A/B test asserts the two records are byte-identical. Scenes:

* ``k1_gameloop_ai``      the golden scene, as the goldens run it (ungated)
* ``combat_stress_gated`` combat_stress, 16 ships, avoidance on, sensor gate
                          INSTALLED
* ``cloak_attack``        the CloakAttack doctrine of test_cloak_attack_doctrine
* ``fed_subsystems``      combat_stress with ChooseSubsystemTargets on (the
                          difficulty row): the subsystem-rating RNG branch
* ``akira_torp_select``   the Akira's ChooseTorpType (test_akira_ai_ammo_selection)
* ``sdk_dumb_fire``       the golden scene (Difficulty 0.0: FireDumb)
* ``pursuers_converge``   tests/helpers/straight_line_chase.py: six Keldons
                          converging on a straight-line player, the one scene
                          where AvoidObstacles actually returns obstacles (the
                          fights above stand off at weapons range and never do)
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCENE_ENV = "NATIVE_AI_AB_SCENE"
TICKS_ENV = "NATIVE_AI_AB_TICKS"
OUT_ENV = "NATIVE_AI_AB_OUT"

#: scene -> default ticks (calls, for akira_torp_select)
DEFAULT_TICKS = {
    "k1_gameloop_ai": None,          # the golden's own length
    "combat_stress_gated": 1200,
    "cloak_attack": 1100,
    "fed_subsystems": 900,
    "akira_torp_select": 400,
    "sdk_dumb_fire": None,           # the golden's own length
    "pursuers_converge": 2400,
}
SCENES = tuple(DEFAULT_TICKS)

#: The golden scenes run through golden_fight.run_scene.
_GOLDEN = ("k1_gameloop_ai", "sdk_dumb_fire")


# ── The parent ───────────────────────────────────────────────────────────────

def _run_side(scene, ticks, native, out, extra_env=None):
    env = dict(os.environ)
    env.update(extra_env or {})
    env[SCENE_ENV] = scene
    env[OUT_ENV] = str(out)
    if ticks is None:
        env.pop(TICKS_ENV, None)
    else:
        env[TICKS_ENV] = str(ticks)
    if native:
        env.pop("DAUNTLESS_NATIVE_AI", None)
    else:
        env["DAUNTLESS_NATIVE_AI"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/helpers/native_ai_ab.py::test_child", "-q", "-x",
         "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("A/B child (%s, native=%s) failed:\n%s\n%s"
                           % (scene, native, proc.stdout[-3000:],
                              proc.stderr[-1500:]))
    return (Path(str(out) + ".rows").read_bytes(),
            json.loads(Path(str(out) + ".stats").read_text()),
            json.loads(Path(str(out) + ".memos").read_text()))


def run_ab_env(scene, extra_env, ticks=None):
    """`(python_record, native_record, native_stats, python_stats,
    native_memo_status)`: run_ab_full with `extra_env` set on both sides
    (e.g. DAUNTLESS_AI_MEMOS=0), and the native side's
    ``_dauntless_host.ai_memo_status()``, so a caller can prove the mode it
    asked for was the one that ran."""
    if scene not in SCENES:
        raise ValueError("unknown A/B scene %r (%r)" % (scene, SCENES))
    if ticks is None:
        ticks = DEFAULT_TICKS[scene]
    with tempfile.TemporaryDirectory() as tmp:
        py_rows, py_stats, _ = _run_side(scene, ticks, False,
                                         Path(tmp) / "py", extra_env)
        nat_rows, nat_stats, nat_memos = _run_side(
            scene, ticks, True, Path(tmp) / "native", extra_env)
    return py_rows, nat_rows, nat_stats, py_stats, nat_memos


def run_ab_full(scene, ticks=None):
    """`(python_record, native_record, native_stats, python_stats)`; see
    run_ab. The python side's counters are returned too: with the switch at 0
    they must read native == 0 for every kind."""
    return run_ab_env(scene, None, ticks)[:4]


def run_ab(scene, ticks=None):
    """`(python_record, native_record, native_stats)`: the scene run with
    DAUNTLESS_NATIVE_AI=0 and with it unset, each in a fresh subprocess, the
    serialised per-tick record of each, and the native run's
    ``ai_native.stats()``."""
    return run_ab_full(scene, ticks)[:3]


def assert_native(stats, kind, allowed_python=(), allowed_object_fallbacks=()):
    """The native run really took the native path for `kind`: native > 0, no
    call went back to the SDK Python, except for the reasons in
    `allowed_python` (a scene may legitimately hold a non-stock instance), and
    no object inside a native call did, except for `allowed_object_fallbacks`."""
    c = stats[kind]
    assert c["native"] > 0, ("%s never ran native" % kind, stats)
    objs = {r: n for r, n in c.get("object_fallbacks", {}).items()
            if r not in allowed_object_fallbacks and n}
    assert not objs, ("%s objects fell back to Python" % kind, objs, stats)
    extra = {r: n for r, n in c["reasons"].items()
             if r not in allowed_python and n}
    assert not extra, ("%s fell back to Python" % kind, extra, stats)
    assert c["python"] == sum(n for r, n in c["reasons"].items()
                              if r in allowed_python), ("%s python" % kind,
                                                        stats)


def assert_no_native(stats):
    """Nothing ran native (the DAUNTLESS_NATIVE_AI=0 side). Every kind must be
    reported: empty or partial counters would pass vacuously."""
    from engine.appc import ai_native
    missing = [k for k in ai_native.KINDS if k not in stats]
    assert not missing, ("kinds not reported", missing, stats)
    assert all(c["native"] == 0 for c in stats.values()), stats


def first_difference(a: bytes, b: bytes) -> str:
    """Where two records first differ, for an assertion message."""
    ra, rb = json.loads(a), json.loads(b)
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x != y:
            return "first differing tick row %d:\n  python: %.600s\n  native: %.600s" \
                % (i, json.dumps(x), json.dumps(y))
    return "lengths differ: %d vs %d (sha %s / %s)" % (
        len(ra), len(rb), hashlib.sha1(a).hexdigest()[:8],
        hashlib.sha1(b).hexdigest()[:8])


# ── The child ────────────────────────────────────────────────────────────────

def test_child():
    """One side of one A/B run, started by ``_run_side`` (a no-op under any
    other collection: it needs the scene variable)."""
    import pytest
    scene = os.environ.get(SCENE_ENV)
    if not scene:
        pytest.skip("only runs as an A/B child")
    ticks = os.environ.get(TICKS_ENV)
    ticks = int(ticks) if ticks else None
    out = os.environ[OUT_ENV]
    _child_setup()
    rows = _SCENE_FUNCS[scene](ticks)
    from engine.appc import ai_native
    Path(out + ".rows").write_bytes(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    Path(out + ".stats").write_text(json.dumps(ai_native.stats()))
    import _dauntless_host as _h
    Path(out + ".memos").write_text(json.dumps(_h.ai_memo_status()))


def _child_setup():
    import pytest
    from engine.appc import native_combat as nc
    from tests.helpers import bc_assets
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    import tempfile as _tf
    os.environ["DAUNTLESS_MODS_DIR"] = os.path.join(_tf.gettempdir(),
                                                    "native_ai_ab_no_mods")
    try:
        import _dauntless_host as _h
    except ImportError:
        _h = None
    if _h is None or not hasattr(_h, "combat_k1_next"):
        pytest.skip("native K1 bindings not built")
    nc.reset()
    from engine.appc import ai_native
    ai_native.reset_stats()


def _golden_scene(name):
    def run(ticks):
        from tests.helpers import golden_fight
        if ticks is not None:
            golden_fight.SCENES[name] = \
                golden_fight.SCENES[name]._replace(ticks=ticks)
        return golden_fight.run_scene(name, "native")
    return run


def _stress(ticks, ships, gate, count_subsystem_rng=False):
    """combat_stress driven like the golden k1_gameloop_ai (k1d._loop_arm)
    but with `ships` ships and, optionally, the sensor gate installed."""
    import pytest
    import App
    from engine import host_loop
    from engine.appc import native_combat as nc
    from engine.appc import sensor_contacts
    from engine.appc.ship_iter import iter_ships
    from engine.core.loop import TICK_DELTA
    from tests.helpers import golden_fight
    from tests.helpers import k1_fight as k1d

    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("DAUNTLESS_NATIVE_MOTION", raising=False)
        golden_fight._patch_records(mp)
        import random
        random.seed(k1d.SEED)
        init = k1d._Scene.__init__
        mp.setattr(k1d._Scene, "__init__",
                   lambda self, m, env, ships_="8", _o=init:
                   _o(self, m, env, ships=str(ships)))
        scene, loop = k1d._loop_setup(mp, k1d.ON)
        if gate:
            from engine.appc import ai_sensor_gate
            ai_sensor_gate.install_ai_sensor_gate()
        rng_draws = [0, 0]             # [SDK ChooseTargetSubsystem, native]
        if count_subsystem_rng:
            # Count by replacing only the wrapper's random.Random (same
            # state, same stream): no SDK or engine method is patched, so the
            # stock gate sees an unchanged surface on both sides. A draw
            # counts when GetRandomNumber was called by the SDK's
            # ChooseTargetSubsystem or, natively, straight from the binding
            # under FireScript's engine Update (_fire_update: no Python frame
            # in between, so the native ChooseTargetSubsystem drew it).
            import random as _random
            import sys as _sys

            class CountingRandom(_random.Random):
                def randrange(self, *a, **kw):
                    f = _sys._getframe(1)             # GetRandomNumber
                    caller = f.f_back.f_code.co_name if f.f_back else None
                    if caller == "ChooseTargetSubsystem":
                        rng_draws[0] += 1
                    elif caller == "_fire_update":
                        rng_draws[1] += 1
                    return super().randrange(*a, **kw)
            old = App.g_kSystemWrapper._rng
            counting = CountingRandom()
            counting.setstate(old.getstate())
            mp.setattr(App.g_kSystemWrapper, "_rng", counting)
        while scene.tick < ticks:
            scene.tick += 1
            loop.tick()
            ship_list = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ship_list, TICK_DELTA)
                host_loop._advance_combat(ship_list, TICK_DELTA,
                                          player=scene.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()
            scene.record()
            sensor_contacts.tick(scene.player,
                                 App.g_kUtopiaModule.GetGameTime())
        nc.audit_mirror()
        assert list(nc.audit_failures()) == []
        if count_subsystem_rng:
            assert sum(rng_draws) > 0, "the subsystem-rating RNG branch never ran"
            from engine.appc import ai_native
            # Each side drew from its own ChooseTargetSubsystem only.
            if ai_native.enabled("fire"):
                assert rng_draws[0] == 0 and rng_draws[1] > 0, rng_draws
            else:
                assert rng_draws[1] == 0 and rng_draws[0] > 0, rng_draws
        rows = golden_fight._canonical(golden_fight._k1_take(scene))
    return rows


def _digest(ships, loop_time):
    from tests.helpers import golden_fight
    rows = [["time", float(loop_time).hex()]]
    rows += golden_fight._pose_rows(ships)
    for s in ships:
        tgt = s.GetTarget()
        hull = s.GetHull()
        cloak = s.GetCloakingSubsystem()
        rows.append(["ship", s.GetName(),
                     float(hull.GetCondition()).hex() if hull else None,
                     tgt.GetName() if tgt is not None else None,
                     [bool(cloak.IsCloaking()), bool(cloak.IsCloaked())]
                     if cloak is not None else None])
    return rows


def _rng_tail():
    """The state of every RNG stream a preprocessor can draw on: a divergence
    in the NUMBER of draws shows here even if no row did."""
    import random
    import App
    from engine.appc import collision_avoidance
    from engine.appc.math import TGPoint3_GetRandomUnitVector
    vec = TGPoint3_GetRandomUnitVector()
    return ["rng", random.random().hex(),
            App.g_kSystemWrapper.GetRandomNumber(1 << 30),
            collision_avoidance._rng.random().hex(),
            [float(c).hex() for c in (vec.x, vec.y, vec.z)]]


def _cloak_attack(ticks):
    import App
    from engine.appc.ship_iter import iter_ships
    from engine.core.loop import GameLoop
    from tests.helpers import k1_fight as k1d
    from tests.unit import test_cloak_attack_doctrine as cad
    k1d._seed_every_rng(k1d.SEED)
    atk = cad._scene()
    cad._build_cloak_attack(atk)
    loop = GameLoop()
    rows = []
    for _ in range(ticks):
        loop.tick()
        rows.append(_digest(list(iter_ships()),
                            App.g_kUtopiaModule.GetGameTime()))
    rows.append(_rng_tail())
    return rows


def _akira_torp_select(ticks):
    import App
    import loadspacehelper
    from engine.appc.ai import PreprocessingAI_Create
    from tests.helpers import k1_fight as k1d
    from AI.Preprocessors import FireScript
    k1d._seed_every_rng(k1d.SEED)
    App.g_kSetManager._sets.clear()
    pset = App.SetClass_Create()
    pset.SetName("S")
    App.g_kSetManager._sets["S"] = pset
    ship = loadspacehelper.CreateShip("Akira", pset, "Akira", None, 0, 0)
    ts = ship.GetTorpedoSystem()
    fs = FireScript("Target")
    fs.pCodeAI = PreprocessingAI_Create(None, "FirePP")
    rows = []
    for i in range(ticks):
        loc = App.TGPoint3()
        loc.SetXYZ(0.0, 20.0 + (i * 37) % 400, (i % 7) * 3.0)
        ts.SetCurrentAmmoSlot(i % ts.GetNumAmmoTypes())
        if i % 5 == 0:                      # drain one type now and then
            ts.LoadAmmoType(i % 2, -ts.GetNumAvailableTorpsToType(i % 2))
        fs.ChooseTorpType(ts, loc, float((i * 11) % 31))
        rows.append(["choice", i, ts.GetAmmoTypeNumber(),
                     [ts.GetNumAvailableTorpsToType(s)
                      for s in range(ts.GetNumAmmoTypes())]])
    rows.append(_rng_tail())
    return rows


def _pursuers_converge(ticks):
    """The straight-line chase, digested every tick, then the RNG tails."""
    import pytest
    import App
    from engine.core.game import _set_current_game
    from tests.helpers import k1_fight as k1d
    from tests.helpers import straight_line_chase as chase
    k1d._seed_every_rng(k1d.SEED)
    with pytest.MonkeyPatch.context() as mp:
        loop, player, pursuers = chase.build(mp)
        ships = [player] + pursuers
        rows = []
        try:
            for _ in range(ticks):
                chase.fly_player(player)
                loop.tick()
                rows.append(_digest(ships, App.g_kUtopiaModule.GetGameTime()))
        finally:
            _set_current_game(None)
    rows.append(_rng_tail())
    return rows


_SCENE_FUNCS = {
    "k1_gameloop_ai": _golden_scene("k1_gameloop_ai"),
    "sdk_dumb_fire": _golden_scene("sdk_dumb_fire"),
    "combat_stress_gated": lambda t: _stress(t, 16, gate=True),
    "fed_subsystems": lambda t: _stress(t, 12, gate=False,
                                        count_subsystem_rng=True),
    "cloak_attack": _cloak_attack,
    "akira_torp_select": _akira_torp_select,
    "pursuers_converge": _pursuers_converge,
}
