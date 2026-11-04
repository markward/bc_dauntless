"""Native K3 torpedoes are bit-identical to the Python `cb.projectiles` step
in a fight with REAL render instances (native combat phase 3, Task 6; spec
docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md §7).

The headless differential (tests/integration/test_native_k3_differential.py)
has no instances, so every torpedo hit lands on its fallback tier. This one
boots the headless host (a real `g_world`), loads combat_stress and realizes
every ship through host_loop's own `realize_set_objects`, as
tests/host/test_native_k2_differential.py does: each ship's radius comes from
its model and its shield hull box is cached, and `session.ship_instances` is
the session's TrackedInstances, so K3's narrow phase traces the hull meshes
natively through the renderer's compiled trace -- the mesh tier, the sphere
tier when the ray misses the mesh but crosses the hull sphere, and the
shield bubble on real boxes.

Two fresh loads -- Python (``DAUNTLESS_NATIVE_COMBAT=0``) and native
(``=1``) -- get the same seeded torpedo schedule (hand launches at close
range from both sides, aimed at points scattered over each target's hull
sphere, so some rays meet the mesh and some only the sphere; guided shots at
the hull and at subsystems) and the same seeded op stream (the ships' real
tubes, shields off and on, turns, moves). Shields go down on half the fleet
for a stretch, so hits meet hulls as well as bubbles; one ship sits in a
dense MetaNebula for a stretch with guided shots at it, so the can_detect
lock-break latch the record compares is set.

RENDER SYNC, as the K2 file: at the top of each frame every realized ship's
instance is set to host_loop's `_ship_world_matrix`; ops later in the frame
are seen by the trace only at the next frame's sync.

Per tick both arms record everything tests/helpers/k3_fight.py lists, and the
full call and event logs; they must be equal. The native arm's kernel records
are tallied: the mesh, sphere and bubble branches must have happened IN THE
KERNEL.
"""
import math
import os
import random
import time

import pytest

import App
from tests.helpers import bc_assets

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k3_begin"),
    reason="native K3 bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc import sensor_contacts  # noqa: E402
from engine.appc.math import TGMatrix3  # noqa: E402
from engine.appc.ship_iter import iter_ships  # noqa: E402
from engine.core import loop as game_loop  # noqa: E402
from engine.core import step_memo  # noqa: E402
from engine.core.loop import TICK_DELTA  # noqa: E402
from engine.core.tracked_instances import TrackedInstances  # noqa: E402
from tests.helpers import headless_mission  # noqa: E402
from tests.helpers.fight_audio import isolate_fight_audio  # noqa: E402
from tests.helpers.k3_fight import (K3Tally, Recorder, aim_velocity,  # noqa: E402
                                    check_guide_asks,
                                    check_native_attributions,
                                    check_weapon_state_paths, compare, face,
                                    fire, nebula_around, presented,
                                    round_trips, seed_every_rng,
                                    subsystems, xyz)

GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")

TICKS = 600
SEED = 20261102
OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
VOLLEY_FROM, VOLLEY_TO, VOLLEY_EVERY = 70, 560, 5
# Shields down on half the fleet for a stretch: hulls, not bubbles.
BARE = ("Player", "Friend-1", "Friend-2", "Enemy-1", "Enemy-2")
BARE_FROM, BARE_TO = 200, 420
# A target inside a dense MetaNebula (twice its hull radius), with guided
# shots at it: every can_detect at it breaks its lock (the latch the record
# compares).
NEB_SHIP, NEB_FROM, NEB_TO = "Enemy-3", 120, 200
NEB_NAME = "K3HostNebula"


@pytest.fixture(scope="module")
def host():
    """The headless host (a real g_world), booted once for the module."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    from engine import renderer as r
    saved = os.environ.get("OPEN_STBC_HOST_HEADLESS")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        try:
            r.init(256, 256, "native-k3-differential")
        except RuntimeError as e:
            pytest.skip(f"no GL context: {e}")
        try:
            yield r
        finally:
            r.shutdown()
    finally:
        if saved is None:
            os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
        else:
            os.environ["OPEN_STBC_HOST_HEADLESS"] = saved


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    nc.reset()


class _Scene:
    def __init__(self, mp, r, env):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        # Radii come from the models (realize), as live.
        mp.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
        self.r = r
        nc.reset()
        App.g_kTimerManager._time = 0.0
        seed_every_rng(0)
        headless_mission.clear_in_flight()
        isolate_fight_audio(mp)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        self.player = App.Game_GetCurrentPlayer()
        self.set = self.player.GetContainingSet()
        self.session = host_loop.MissionSession(mission_name="k3_diff")
        assert type(self.session.ship_instances) is TrackedInstances
        host_loop.realize_set_objects(self.session, self.set, r,
                                      include_planets=False)
        self.ships = list(iter_ships())
        assert len(self.ships) == 9
        assert all(s in self.session.ship_instances for s in self.ships)
        assert all(getattr(s, "_shield_hull_box", None) is not None
                   for s in self.ships)
        assert all(s.GetRadius() > 0.0 for s in self.ships)
        self.by_name = {s.GetName(): s for s in self.ships}
        face_rng = random.Random(SEED + 2)
        for ship in self.ships:
            face(ship, self.foe(face_rng, ship))
        step_memo.forget()
        nc.configure(env)
        assert nc.enabled() is (env is ON)
        self.native = env is ON
        self.torpedo_systems = [s.GetTorpedoSystem() for s in self.ships
                                if s.GetTorpedoSystem() is not None]
        self.tick = 0
        self.rec = Recorder(mp, self.ships, self.by_name["Enemy-4"],
                            ship_instances=self.session.ship_instances,
                            native=self.native)
        if self.native:
            self.rec.tally = K3Tally(_h.combat_k3_next)
            mp.setattr(_h, "combat_k3_next", self.rec.tally)

    def close(self):
        projectiles._active.clear()
        host_loop.teardown_set_objects(self.session, self.set, self.r)

    def foes(self, ship):
        side = ship.GetName().startswith("Enemy")
        return [s for s in self.ships
                if s.GetName().startswith("Enemy") != side and not s.IsDead()]

    def foe(self, rng, ship):
        foes = self.foes(ship)
        return rng.choice(foes) if foes else None

    def launch(self, rng, src=None, target=None):
        """A shot from a random ship (or `src`) at a random foe (or `target`),
        aimed at a point scattered over the foe's hull sphere: the mesh
        catches some rays, only the sphere others."""
        if src is None:
            alive = [s for s in self.ships if not s.IsDead()]
            src = rng.choice(alive)
            target = self.foe(rng, src)
        if target is None or src.IsDead():
            return
        here = xyz(src.GetWorldLocation())
        there = xyz(target.GetWorldLocation())
        r = target.GetRadius()
        point = tuple(c + rng.uniform(-0.9, 0.9) * r for c in there)
        start = [here[i] + c for i, c in enumerate(
            aim_velocity(here, there, src.GetRadius() + 1.0))]
        speed = rng.uniform(22.0, 34.0)
        kind = rng.choice(("dumb", "dumb", "dumb", "centre", "offset"))
        vel = aim_velocity(start, point, speed)
        ttl = rng.choice((2.0, 4.0))
        if kind == "dumb":
            fire(src, start, vel, ttl=ttl)
            return
        offset = None
        if kind == "offset":
            offset = rng.choice(subsystems(target)).GetPosition()
        fire(src, start, vel, target=target, offset=offset, ttl=ttl,
             guidance=rng.choice((0.5, 3.0)), accel=rng.choice((1.0, 2.5)))

    def beats(self, rng):
        t = self.tick
        if VOLLEY_FROM <= t <= VOLLEY_TO and t % VOLLEY_EVERY == 0:
            for _ in range(3):
                self.launch(rng)
        if t == NEB_FROM:
            target = self.by_name[NEB_SHIP]
            nebula_around(target, NEB_NAME,
                          2.0 * target.GetRadius())
        elif NEB_FROM < t < NEB_TO and t % 20 == 0:
            target = self.by_name[NEB_SHIP]
            for src in self.foes(target)[:2]:
                self.launch(rng, src, target)
        elif t == NEB_TO:
            self.set.RemoveObjectFromSet(NEB_NAME)
        if t in (BARE_FROM, BARE_TO):
            for name in BARE:
                shields = self.by_name[name].GetShields()
                if t == BARE_FROM:
                    shields.TurnOff()
                else:
                    shields.TurnOn()

    def op(self, rng):
        kind = rng.choice(("tubes", "tubes", "shields_off", "shields_on",
                           "turn", "move"))
        if kind == "tubes":
            torps = rng.choice(self.torpedo_systems)
            ship = torps.GetParentShip()
            target = self.foe(rng, ship)
            if target is None or ship.IsDead():
                return
            face(ship, target)
            ammo = torps.GetCurrentAmmoType()
            if ammo is not None:
                ammo.SetAvailable(ammo.GetMaxTorpedoes())
            for i in range(torps.GetNumWeapons()):
                torps.GetWeapon(i).SetNumReady(1)
            torps.TurnOn()
            torps.StartFiring(target, rng.choice(
                (None, rng.choice(subsystems(target)).GetPosition())))
        elif kind in ("shields_off", "shields_on"):
            shields = rng.choice(self.ships).GetShields()
            if shields is not None:
                (shields.TurnOff if kind == "shields_off"
                 else shields.TurnOn)()
        elif kind == "turn":
            m = TGMatrix3()
            m.MakeZRotation(rng.uniform(-math.pi, math.pi))
            rng.choice(self.ships).SetMatrixRotation(m)
        elif kind == "move":
            ship = rng.choice(self.ships)
            p = ship.GetTranslate()
            ship.SetTranslateXYZ(p.x + rng.uniform(-3.0, 3.0),
                                 p.y + rng.uniform(-3.0, 3.0),
                                 p.z + rng.uniform(-1.0, 1.0))

    def sync_render(self):
        for ship, iid in self.session.ship_instances.items():
            self.r.set_world_transform(
                iid, host_loop._ship_world_matrix(ship,
                                                  host_loop.BC_MODEL_SCALE))

    def run(self, ticks_per_frame, ticks=TICKS):
        rng = random.Random(SEED)
        beat_rng = random.Random(SEED + 1)
        instances = self.session.ship_instances
        p_op = 0.05 * ticks_per_frame
        while self.tick < ticks:
            if rng.random() < p_op:
                self.op(rng)
            self.sync_render()
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            # After the sync: the trace sees these only next frame.
            if rng.random() < p_op:
                self.op(rng)
            for _ in range(ticks_per_frame):
                self.tick += 1
                self.rec.tick = self.tick
                self.beats(beat_rng)
                ships = list(iter_ships())
                with host_loop._combat_effect_scope():
                    host_loop._advance_weapons(ships, TICK_DELTA)
                    host_loop._advance_combat(ships, TICK_DELTA,
                                              ship_instances=instances,
                                              player=self.player,
                                              push_render_data=False)
                host_loop._combat_tick_boundary()   # as the host does (native damage)
                self.rec.record()
                if rng.random() < 0.03:
                    self.op(rng)
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        self.audit = []
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert not _h.combat_k3_open()
        self.counts = nc.counts()
        return self


def _both(monkeypatch, r, ticks_per_frame, ticks=TICKS):
    runs = []
    for env in (OFF, ON):
        with monkeypatch.context() as mp:
            scene = _Scene(mp, r, env)
            try:
                runs.append(scene.run(ticks_per_frame, ticks=ticks))
            finally:
                scene.close()
    ref, nat = runs
    compare(ref.rec, nat.rec)
    assert nat.audit == [], nat.audit
    assert ref.counts.get("k3_runs", 0) == 0, ref.counts
    assert ref.counts.get("k4_runs", 0) == 0, ref.counts
    return ref, nat


@pytest.mark.parametrize("ticks_per_frame", (1, 4))
def test_k3_matches_python_with_real_instances(monkeypatch, host,
                                               ticks_per_frame):
    t0 = time.perf_counter()
    ref, nat = _both(monkeypatch, host, ticks_per_frame)
    elapsed = time.perf_counter() - t0
    n = nat.rec.tally.n
    k3_why = {k: v for k, v in nat.counts["k3_python_reasons"].items() if v}
    k4_why = {k: v for k, v in nat.counts["k4_python_reasons"].items() if v}
    print("\nk3 host differential (tpf=%d): %.1f s for 2 x %d ticks;\n  "
          "kernel records %r\n  k3_runs %d k3_asks %r k3_guide_reasons %r\n"
          "  k4_runs %d k4 %r\n  k3 python reasons %r\n  k4 python reasons "
          "%r\n  hits %d, presented %d, events %d"
          % (ticks_per_frame, elapsed, TICKS, dict(sorted(n.items())),
             nat.counts["k3_runs"], nat.counts["k3_asks"],
             nat.counts["k3_guide_reasons"], nat.counts["k4_runs"],
             nat.rec.k4, k3_why, k4_why,
             len([c for c in ref.rec.calls if c[0] == "hit"]),
             len([c for c in ref.rec.calls if c[0] == "hit_present"]),
             len(ref.rec.events)))
    print("  latched (pair x tick) %d" % nat.rec.latched)
    print("  round trips %r, presentation calls %d"
          % (round_trips(nat.counts), presented(ref.rec.calls)))
    # Round trips Task 4: the mounts were attributed natively; and K1
    # walked the ships' tubes with no WALK_START record (Task 1). A torpedo
    # fight: no beam sustains or batched contacts (measured 0).
    check_native_attributions(nat.counts, nat.rec.tally)
    # K0 charged and reloaded every weapon, writes were C-applied and
    # scalar pushes made in one call (native weapon state).
    check_weapon_state_paths(nat.counts)
    assert nat.counts["k1_logged"]["walk_start"] > 0, round_trips(
        nat.counts)
    # Native damage Task 4: K3 applies every hit itself, none handed back.
    assert nat.counts["k3_native_hits"] > 0, nat.counts
    assert nat.counts["k3_hit_python"] == 0, nat.counts["k3_hit_python_reasons"]
    assert nat.counts["k3_runs"] > 0 and nat.counts["k3_python_steps"] == 0, \
        nat.counts
    assert nat.counts["k4_runs"] == TICKS and not k4_why, nat.counts
    # Every torpedo's target and source is a scanned ship of one set: no
    # _guide is ever handed to Python.
    check_guide_asks(nat.counts, nat.rec.tally, expected=())
    # The latch row compared something: a can_detect lock broke.
    assert nat.rec.latched > 0
    # The narrow phase on real instances: the mesh and sphere tiers, the
    # bubble on real hull boxes. (A bubble hit's own point -- the fallback
    # tier -- is the headless file's: on a realized hull the ray from the
    # bubble always meets the mesh or the sphere.)
    for key in ("tier:mesh", "tier:sphere", "bubble", "normal",
                "guided_visible", "steer_point:native_mount", "ttl"):
        assert n.get(key, 0) > 0, (key, n)
    # A mesh hit through the bubble, and one with the shields down.
    hits = [c for c in ref.rec.calls if c[0] == "hit"]
    assert any(c[5] is not None and c[6] is not None for c in hits), \
        "no mesh hit behind a bubble entry"
    assert any(c[5] is not None and c[6] is None for c in hits), \
        "no bare-hull mesh hit"
    events = [e for e in ref.rec.events if e[0] == App.ET_WEAPON_HIT]
    assert events and all(e[4] is not None for e in events)
