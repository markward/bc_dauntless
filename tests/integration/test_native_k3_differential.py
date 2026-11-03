"""Native K3 torpedoes and K4 damage eligibility are bit-identical to the
Python in a real torpedo fight (native combat phase 3, Task 6; spec
docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md §7; plan
docs/superpowers/plans/2026-11-01-native-combat-k3-k4.md).

Two fresh loads of combat_stress -- the Python reference
(``DAUNTLESS_NATIVE_COMBAT=0``) and native (``=1``: K4 decides
``cb.eligibility``, K3 ``cb.projectiles``, with K1/K2 and native can_detect
under them) -- each grown into a three-frame fight:

* QuickBattleRegion: the player and 8 AI ships on combat_stress's ring
  (AI not ticked, as the K1 differential drives it);
* Ona1 and Ona2, two REAL mapped regions of one system (load_region), with a
  Galaxy pair in Ona1 and a Vor'cha in Ona2 placed 30 GU from them in
  SYSTEM coordinates: they trade guided shots across the region boundary
  (the test_frame_tripwire.py scenario);
* a plain Starbase12 set (its own frame) with two Birds of Prey.

Hits are made certain, which the earlier differentials never managed (the
K1 fight ran 4,374 K3 sessions and 0 hits: its headless ships have radius 0,
so no torpedo can touch one). Every ship gets combat_stress's nominal 4 GU,
and torpedoes are launched by hand at close range from both sides on a
seeded schedule -- guided at the hull or at a subsystem, dumbfire, wide shots
that must turn, short guidance windows, short TTLs -- on top of a seeded op
stream that fires the ships' real tubes. Scripted beats make the rare
branches certain: a shooter's sensors off with its shots in flight (guided
invisible on the frozen last-seen point), a shooter moved into another frame
with its shots in flight (``_target_visible``'s ``off is None`` can_detect),
a target moved into another frame (ballistic), a target killed (ballistic),
a target posed off its NIF pose while shots at its subsystems home (the
mount attributed and the posed steer point computed natively), a target
inside a dense MetaNebula with guided shots at it (every can_detect at it
breaks its lock: the latch the record compares). Half the ships carry a
shield hull box, so shots meet
the bubble (the fallback tier: hit point, ``_bubble_entry`` and the hit's
shield_point ONE object).

K4: ``select_eligible``'s max_count is raised to 11 (player + the 8 ring ships
+ 2), so its cut falls inside the cross-frame ships -- all prox 0, all the same
size: an exact tie every tick, which only the ``id()`` tie-break decides.

Per tick both arms record everything tests/helpers/k3_fight.py lists (every
torpedo by .hex(), every ship, ``damage_eligibility._current``, every
can_detect latch, the incoming-torpedo table) and the full call and event
logs; they must be equal. The native arm's kernel records are tallied, and
every branch spec §7 lists must have happened IN THE KERNEL.
"""
import random
import time

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import articulation
from engine.appc import damage_eligibility
from engine.appc import native_combat as nc
from engine.appc import part_pose
from engine.appc import projectiles
from engine.appc import sensor_contacts
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from engine.systems import frames
from tests.helpers import bc_assets, headless_mission
from tests.helpers.fight_audio import isolate_fight_audio
from tests.helpers.k3_fight import (K3Tally, Recorder, aim_velocity,
                                    check_guide_asks,
                                    check_native_attributions,
                                    check_weapon_state_paths, compare, face,
                                    fire, nebula_around, presented,
                                    round_trips, seed_every_rng, subsystems,
                                    xyz)
from tests.helpers.mapped_regions import load_region

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k3_begin"),
    reason="native K3 bindings not built")

TICKS = 600
SEED = 20261101
OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
RADIUS = 4.0                # combat_stress's nominal hull, on every ship
# The player + the 8 ring ships + 2 of the cross-frame tie.
MAX_ELIGIBLE = 11

# The schedule (ticks). A ship's sensors have no range until their power is
# up at ~1 s of game time: the first launches follow it.
VOLLEY_FROM, VOLLEY_TO, VOLLEY_EVERY = 70, 540, 9
CROSS_EVERY = 25
# A shooter's sensors off with its guided shots in flight.
BLIND_SHIP, BLIND_FIRE, BLIND_FROM, BLIND_TO = "Friend-2", 180, 190, 250
# A shooter moved into another frame with its shots in flight.
EXILE_SHIP, EXILE_TARGET, EXILE_FIRE, EXILE_AT = ("Enemy-2", "Friend-3",
                                                  280, 288)
# A target moved into another frame with shots in flight at it.
FLEE_SHIP, FLEE_FIRE, FLEE_AT = "Enemy-1", 330, 338
# A target killed with shots in flight at it.
KILL_SHIP, KILL_FIRE, KILL_AT = "Enemy-3", 380, 388
# A target off its NIF pose while shots at its subsystems home.
POSE_SHIP, POSE_FROM, POSE_TO = "Friend-4", 420, 500
# A target inside a dense MetaNebula: every can_detect at it breaks its lock
# (the latch the record compares), shots at it fly on their last-seen point.
NEB_SHIP, NEB_FROM, NEB_TO, NEB_RADIUS = "Friend-1", 150, 230, 6.0
NEB_NAME = "K3DiffNebula"
# Ships with a shield hull box (half of them).
BOXED = ("Player", "Friend-1", "Friend-3", "Enemy-1", "Enemy-4", "Ona-B")
HULL_BOX = ((0.0, 0.3, 0.0), (2.0, 3.0, 1.0))


def _pow_sqrt_split():
    """A box centre (a, b, 0) whose squared length is a double where Python's
    `x ** 0.5` (libm pow) and math.sqrt differ in the last place
    (bubble_bound_radius's centre_len is the former; the square of ONE
    component never splits them). Its length is in [4, 8), the binade of the
    bound `centre_len + max_semi` (the half extents below keep the sum under
    8), so a one-ulp difference in centre_len survives the sum: the bound
    recorded per tick then shows which root the kernel took. None when this
    libm has no split near (3.5, 2.5)."""
    import math
    a, b = 3.5, 2.5
    for _ in range(100000):
        x = a * a + b * b + 0.0 * 0.0
        if x ** 0.5 != math.sqrt(x):
            if 4.0 <= x ** 0.5 < 6.0:
                return (a, b, 0.0)
            return None
        a += 1e-6
    return None


@pytest.fixture(scope="module")
def odd_hull_box():
    """SB-2's hull box (Starbase12: no shot is aimed at it): its centre's
    length is one where `** 0.5` and sqrt differ. Searched at run time, not
    import: a libm with no split near the start skips, never a collection
    error."""
    centre = _pow_sqrt_split()
    if centre is None:
        pytest.skip("no pow/sqrt last-place split near (3.5, 2.5) on this "
                    "libm: the bound would not show which root K3 took")
    return (centre, (0.4, 0.6, 0.3))


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    nc.reset()


def _create(ship_type, pSet, name, at):
    import loadspacehelper
    ship = loadspacehelper.CreateShip(ship_type, pSet, name, "")
    assert ship is not None and not App.IsNull(ship), name
    ship.SetTranslateXYZ(*at)
    ship.UpdateNodeOnly()
    return ship


def _move_to(ship, pSet, at):
    """Out of its set and into `pSet` at `at` (a warp's set change)."""
    name = ship.GetName()
    ship.GetContainingSet().RemoveObjectFromSet(name)
    pSet.AddObjectToSet(ship, name)
    ship.SetTranslateXYZ(*at)
    ship.UpdateNodeOnly()


class _Scene:
    def __init__(self, mp, env, odd_hull_box):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
        nc.reset()
        App.g_kTimerManager._time = 0.0
        seed_every_rng(0)
        headless_mission.clear_in_flight()
        # A hit sound is one SDK RNG draw: decided by the fight alone.
        isolate_fight_audio(mp)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        self.player = App.Game_GetCurrentPlayer()
        self.qb = self.player.GetContainingSet()
        # Two regions of one system, and a set in its own frame.
        self.ona1 = load_region("Ona", "Ona1")
        self.ona2 = load_region("Ona", "Ona2")
        self.sb12 = App.SetClass_Create()
        App.g_kSetManager.AddSet(self.sb12, "Starbase12")
        off = frames.offset_between(self.ona1, self.ona2)
        assert off is not None and off != (0.0, 0.0, 0.0)
        base = (40000.0, 5236.0, 1.5)
        _create("Galaxy", self.ona1, "Ona-A", base)
        _create("Galaxy", self.ona1, "Ona-C", (base[0] + 14.0, base[1],
                                               base[2]))
        # 30 GU from Ona-A in SYSTEM coordinates: Ona1-local = Ona2 + off.
        _create("Vorcha", self.ona2, "Ona-B", (base[0] - off[0] + 6.0,
                                               base[1] - off[1] + 30.0,
                                               base[2] - off[2]))
        _create("BirdOfPrey", self.sb12, "SB-1", (0.0, 0.0, 0.0))
        _create("BirdOfPrey", self.sb12, "SB-2", (12.0, 3.0, 0.0))
        self.ships = list(iter_ships())
        assert len(self.ships) == 14, [s.GetName() for s in self.ships]
        for s in self.ships:
            s.SetRadius(RADIUS)
            if s.GetName() in BOXED:
                s._shield_hull_box = HULL_BOX
        self.by_name = {s.GetName(): s for s in self.ships}
        # Its box centre's length is one where `** 0.5` and sqrt differ.
        self.by_name["SB-2"]._shield_hull_box = odd_hull_box
        for s in self.ships:
            if s.GetContainingSet() is self.qb:
                face(s, self.foe(random.Random(SEED + 2), s))
        mp.setitem(damage_eligibility.select_eligible.__kwdefaults__,
                   "max_count", MAX_ELIGIBLE)
        step_memo.forget()
        nc.configure(env)
        assert nc.enabled() is (env is ON)
        self.native = env is ON
        self.torpedo_systems = [s.GetTorpedoSystem() for s in self.ships
                                if s.GetTorpedoSystem() is not None]
        self.cloakers = [s for s in self.ships
                         if s.GetCloakingSubsystem() is not None]
        self.tick = 0
        self.rec = Recorder(mp, self.ships, self.by_name["Enemy-4"],
                            native=self.native)
        if self.native:
            self.rec.tally = K3Tally(_h.combat_k3_next)
            mp.setattr(_h, "combat_k3_next", self.rec.tally)

    def close(self):
        for name in ("Ona1", "Ona2", "Starbase12"):
            App.g_kSetManager.DeleteSet(name)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def ship(self, name):
        return self.by_name[name]

    def side(self, ship):
        name = ship.GetName()
        return name.startswith("Enemy") or name in ("Ona-B", "SB-1", "SB-2")

    def foes(self, ship):
        return [s for s in self.ships
                if self.side(s) != self.side(ship) and not s.IsDead()
                and s.GetContainingSet() is ship.GetContainingSet()]

    def foe(self, rng, ship):
        foes = self.foes(ship)
        return rng.choice(foes) if foes else None

    def launch(self, rng, src, target, kind=None):
        """One hand-launched torpedo from `src` at `target` (any set of its
        frame), of a seeded kind."""
        if src.IsDead() or target is None:
            return None
        kind = kind or rng.choice(("centre", "offset", "offset", "dumb",
                                   "wide", "window"))
        here = xyz(src.GetWorldLocation())
        there = frames.local_in(src.GetContainingSet(), target)
        if there is None:
            return None
        speed = rng.uniform(20.0, 32.0)
        start = [here[i] + c for i, c in enumerate(
            aim_velocity(here, there, 5.0))]
        spread = (rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5),
                  rng.uniform(-0.8, 0.8))
        ttl = rng.choice((1.6, 3.0, 5.0))
        accel = rng.choice((0.8, 2.0, 3.5))
        if kind == "dumb":
            return fire(src, start, aim_velocity(start, there, speed, spread),
                        ttl=ttl)
        if kind == "wide":
            spread = (rng.choice((-1, 1)) * 12.0, 0.0, rng.uniform(-4, 4))
        offset = None
        if kind == "offset":
            offset = rng.choice(subsystems(target)).GetPosition()
        guidance = 0.3 if kind == "window" else rng.choice((1.2, 4.0))
        return fire(src, start, aim_velocity(start, there, speed, spread),
                    target=target, offset=offset, ttl=ttl,
                    guidance=guidance, accel=accel)

    # ── Beats ────────────────────────────────────────────────────────────────

    def drift(self):
        """Three ships drift (their velocity is the shots' lead), slowly
        changing it (the lead's acceleration term)."""
        for k, name in enumerate(("Enemy-4", "Friend-3", "Ona-B")):
            s = self.ship(name)
            if s.IsDead():
                continue
            v = TGPoint3(0.6 - 0.2 * k, -0.4 + 0.002 * self.tick,
                         0.15 * k)
            p = s.GetTranslate()
            s.SetTranslateXYZ(p.x + v.x * TICK_DELTA, p.y + v.y * TICK_DELTA,
                              p.z + v.z * TICK_DELTA)
            s.SetVelocity(v)

    def beats(self, rng):
        t = self.tick
        if VOLLEY_FROM <= t <= VOLLEY_TO and t % VOLLEY_EVERY == 0:
            qb = [s for s in self.ships if s.GetContainingSet() is self.qb
                  and not s.IsDead()]
            for _ in range(2):
                src = rng.choice(qb)
                self.launch(rng, src, self.foe(rng, src))
        if VOLLEY_FROM <= t <= VOLLEY_TO and t % CROSS_EVERY == 0:
            a, b, c = (self.ship("Ona-A"), self.ship("Ona-B"),
                       self.ship("Ona-C"))
            self.launch(rng, a, b, rng.choice(("centre", "offset")))
            self.launch(rng, b, rng.choice((a, c)), "centre")
            self.launch(rng, c, b, rng.choice(("offset", "dumb")))
        if t == BLIND_FIRE:
            # One at a drifting target: its frozen last-seen point parts from
            # where it is.
            src = self.ship(BLIND_SHIP)
            for target in [self.ship("Enemy-4")] + self.foes(src)[:2]:
                self.launch(rng, src, target, "centre")
        elif t == BLIND_FROM:
            self.ship(BLIND_SHIP).GetSensorSubsystem().TurnOff()
        elif t == BLIND_TO:
            self.ship(BLIND_SHIP).GetSensorSubsystem().TurnOn()
        if t == EXILE_FIRE:
            # At a DRIFTING target: the frozen last-seen point and the live
            # steer point part as soon as the shooter is gone.
            src = self.ship(EXILE_SHIP)
            for kind in ("centre", "offset"):
                self.launch(rng, src, self.ship(EXILE_TARGET), kind)
        elif t == EXILE_AT:
            # Far past any sensor range in the raw numbers the off-None
            # can_detect compares: its shots lose their target.
            _move_to(self.ship(EXILE_SHIP), self.sb12, (1.0e6, 1.0e6, 0.0))
        if t == FLEE_FIRE:
            target = self.ship(FLEE_SHIP)
            for src in self.foes(target)[:2]:
                self.launch(rng, src, target, "centre")
        elif t == FLEE_AT:
            _move_to(self.ship(FLEE_SHIP), self.sb12, (-5000.0, 0.0, 0.0))
        if t == KILL_FIRE:
            target = self.ship(KILL_SHIP)
            for src in self.foes(target)[:3]:
                self.launch(rng, src, target, "centre")
        elif t == KILL_AT:
            from engine.appc import ship_death
            target = self.ship(KILL_SHIP)
            ship_death.begin(target, self.player)
            target.SetDead()
        if t == POSE_FROM:
            articulation.force_part_pose(
                self.ship(POSE_SHIP), "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))
        elif t == POSE_TO:
            articulation.force_part_pose(self.ship(POSE_SHIP), "probe part",
                                         part_pose.IDENTITY)
        if t == NEB_FROM:
            nebula_around(self.ship(NEB_SHIP), NEB_NAME, NEB_RADIUS)
        elif NEB_FROM < t < NEB_TO and t % 20 == 0:
            # Guided shots at it: their guide's can_detect breaks the lock.
            target = self.ship(NEB_SHIP)
            for src in self.foes(target)[:2]:
                self.launch(rng, src, target, "centre")
        elif t == NEB_TO:
            self.ship(NEB_SHIP).GetContainingSet().RemoveObjectFromSet(
                NEB_NAME)
        if POSE_FROM <= t < POSE_TO and t % 10 == 0:
            target = self.ship(POSE_SHIP)
            for src in self.foes(target)[:2]:
                self.launch(rng, src, target, "offset")
        self.drift()

    # ── Ops: the ships' real tubes, shields, cloaks ─────────────────────────

    def op(self, rng):
        kind = rng.choice(("tubes", "tubes", "tubes", "stop", "shields_off",
                           "shields_on", "cloak", "decloak", "turn"))
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
        elif kind == "stop":
            rng.choice(self.torpedo_systems).StopFiring()
        elif kind == "shields_off":
            shields = rng.choice(self.ships).GetShields()
            if shields is not None:
                shields.TurnOff()
        elif kind == "shields_on":
            shields = rng.choice(self.ships).GetShields()
            if shields is not None:
                shields.TurnOn()
        elif kind == "cloak":
            rng.choice(self.cloakers).GetCloakingSubsystem().StartCloaking()
        elif kind == "decloak":
            rng.choice(self.cloakers).GetCloakingSubsystem().StopCloaking()
        elif kind == "turn":
            import math
            ship = rng.choice(self.ships)
            m = TGMatrix3()
            m.MakeZRotation(rng.uniform(-math.pi, math.pi))
            ship.SetMatrixRotation(m)

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self, ticks_per_frame, ticks=TICKS, before_tick=None):
        rng = random.Random(SEED)
        beat_rng = random.Random(SEED + 1)
        p_op = 0.05 * ticks_per_frame
        while self.tick < ticks:
            if rng.random() < p_op:
                self.op(rng)
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            if rng.random() < p_op:
                self.op(rng)
            for _ in range(ticks_per_frame):
                self.tick += 1
                self.rec.tick = self.tick
                self.beats(beat_rng)
                if before_tick is not None:
                    before_tick(self)
                ships = list(iter_ships())
                with host_loop._combat_effect_scope():
                    host_loop._advance_weapons(ships, TICK_DELTA)
                    host_loop._advance_combat(ships, TICK_DELTA,
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


def _both(monkeypatch, odd_hull_box, ticks_per_frame, ticks=TICKS,
          before_tick=None):
    runs = []
    for env in (OFF, ON):
        with monkeypatch.context() as mp:
            scene = _Scene(mp, env, odd_hull_box)
            try:
                runs.append(scene.run(ticks_per_frame, ticks=ticks,
                                      before_tick=before_tick))
            finally:
                scene.close()
                projectiles._active.clear()
    ref, nat = runs
    compare(ref.rec, nat.rec)
    assert nat.audit == [], nat.audit
    assert ref.counts.get("k3_runs", 0) == 0, ref.counts
    assert ref.counts.get("k4_runs", 0) == 0, ref.counts
    return ref, nat


def _python_reasons(counts):
    return ({k: v for k, v in counts["k3_python_reasons"].items() if v},
            {k: v for k, v in counts["k4_python_reasons"].items() if v})


# Every branch spec §7 lists, as the kernel decided it.
BRANCHES = (
    "guided_visible", "guided_invisible", "ballistic_dead",
    "ballistic_frame", "unguided", "window_end", "ttl",
    "cross_region_homing", "cross_region_hit", "hit_is_bubble",
    "tier:fallback", "steer_point:posed", "steer_point:native_mount",
    "source_other_frame", "source_other_frame_unseen", "same_ship_hits",
    "ttl_and_hit_same_tick")


@pytest.mark.parametrize("ticks_per_frame", (1, 4))
def test_k3_k4_match_python_in_a_torpedo_fight(monkeypatch, odd_hull_box,
                                               ticks_per_frame):
    t0 = time.perf_counter()
    ref, nat = _both(monkeypatch, odd_hull_box, ticks_per_frame)
    elapsed = time.perf_counter() - t0
    n = nat.rec.tally.n
    k3_why, k4_why = _python_reasons(nat.counts)
    print("\nk3/k4 headless differential (tpf=%d): %.1f s for 2 x %d ticks;"
          "\n  kernel records %r\n  k4 %r\n  k3_runs %d k3_asks %r "
          "k3_guide_reasons %r\n  k4_runs %d\n  k3 python reasons %r\n  "
          "k4 python reasons %r\n  hits %d, presented %d, events %d"
          % (ticks_per_frame, elapsed, TICKS, dict(sorted(n.items())),
             nat.rec.k4, nat.counts["k3_runs"], nat.counts["k3_asks"],
             nat.counts["k3_guide_reasons"], nat.counts["k4_runs"], k3_why,
             k4_why, len([c for c in ref.rec.calls if c[0] == "hit"]),
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
    # K3 and K4 decided every step: no whole-step hand-back.
    # Native damage Task 4: K3 applies every hit itself, none handed back.
    assert nat.counts["k3_native_hits"] > 0, nat.counts
    assert nat.counts["k3_hit_python"] == 0, nat.counts["k3_hit_python_reasons"]
    assert nat.counts["k3_runs"] > 0 and nat.counts["k3_python_steps"] == 0, \
        nat.counts
    assert nat.counts["k4_runs"] == TICKS and not k4_why, nat.counts
    # Every scan's targets and sources are scanned ships in one frame
    # table: no torpedo's _guide is ever handed to Python.
    check_guide_asks(nat.counts, nat.rec.tally, expected=())
    # The latch row compared something: a can_detect lock broke.
    assert nat.rec.latched > 0
    # Every branch happened in the kernel.
    for key in BRANCHES:
        assert n.get(key, 0) > 0, (key, n)
    # K4: the cut fell inside an exact tie, and cross-frame ships scored.
    assert nat.rec.k4["tie_at_cut"] > 0 and nat.rec.k4["cross_frame"] > 0, \
        nat.rec.k4
    # The effects reached the world: hits, their presentation, weapon-hit events
    # with their payload, shots leaving flight.
    calls = ref.rec.calls
    assert any(c[0] == "hit" for c in calls)
    assert any(c[0] == "hit_present" and c[10] for c in calls), \
        "no hit with shield_point IS the hit point"
    hits = [e for e in ref.rec.events if e[0] == App.ET_WEAPON_HIT]
    assert hits and all(e[4] is not None for e in hits)
    assert any(e[0] == App.ET_TORPEDO_EXITED_SET for e in ref.rec.events)
    assert any(ref.rec.scan_writes.values())


def test_two_hits_on_one_ship_same_tick(monkeypatch, odd_hull_box):
    """Two shots reach one ship in the same tick, from either side: both are
    hits (the world is static for the walk: the second is decided before the
    first is applied), applied in list order, in both arms. A third shot,
    launched FIRST, reaches its TTL in that same tick: it leaves flight
    before both hits (update_all's `expired` holds the TTL expiries, in list
    order, ahead of the hits)."""
    seen = {}

    def before_tick(scene):
        if scene.tick == 80:
            # Not drifting and no hull box: both shots meet its sphere
            # after the same number of steps (the 10th: 9 GU at 0.5 GU a
            # step, against a 4 GU sphere).
            target = scene.ship("Enemy-2")
            p = xyz(target.GetWorldLocation())
            shots = seen.setdefault(scene.native, [])
            shots.append(fire(scene.ship("Friend-3"), (0.0, 0.0, 60.0),
                              (0.0, 0.0, 10.0), ttl=9.5 * TICK_DELTA))
            for k, sign in enumerate((1.0, -1.0)):
                start = (p[0] + sign * 9.0, p[1], p[2])
                shots.append(fire(
                    scene.ship("Friend-%d" % (k + 1)), start,
                    (-sign * 30.0, 0.0, 0.0), ttl=5.0))

    ref, nat = _both(monkeypatch, odd_hull_box, 1, ticks=100,
                     before_tick=before_tick)
    n = nat.rec.tally.n
    assert n.get("same_ship_hits", 0) > 0, n
    assert n.get("ttl_and_hit_same_tick", 0) > 0, n
    ttl_shot, *hit_shots = [ref.rec.label(t) for t in seen[False]]
    hits = [c for c in ref.rec.calls if c[0] == "hit" and c[2] in hit_shots]
    assert len(hits) == 2 and hits[0][1] == hits[1][1] == 89, hits
    assert hits[0][3] == hits[1][3] == "Enemy-2", hits
    assert [c[2] for c in hits] == hit_shots, hits
    exits = [e[1] for e in ref.rec.events
             if e[0] == App.ET_TORPEDO_EXITED_SET and e[3] == 89]
    assert exits[:1] == [ttl_shot] and set(exits[1:3]) == set(hit_shots), \
        exits
