"""The posed-parts fight both posed differentials run (native combat posed
parts, Task 5; spec docs/superpowers/specs/2026-11-01-native-combat-posed-
parts-design.md §5): tests/integration/test_native_posed_differential.py
(headless) and tests/host/test_native_posed_differential.py (real
instances).

combat_stress (the player, four Federation ships and four enemies, one of
them a Bird of Prey: Enemy-4) plus a second, scripted Bird of Prey (Enemy-B)
placed inside the ring. Both Birds of Prey are real hardpoint loads, so their
leaf is cached and their part slots resolve:

* Enemy-B is SETTLED IN CRUISE: snapped to its cruise pose before the fight
  and given no target, so its wings stay up (posed) all fight;
* Enemy-4 is MID-TRANSITION: its NPC state is "red" with a target and
  "cruise" without one, and its target is taken away and given back every
  TOGGLE_EVERY ticks -- shorter than the rig's swing, so its wings are
  always on the way somewhere.

And one Federation ship is posed too: Friend-3, a Galaxy, has its phaser
banks on parts forced by name (the SPV's `force_state_poses` and
`SetPhysicalParent`): most on a hinged part, three on a part whose pose is
identity to `part_pose.is_identity` but not to a multiply (a 5e-10
translation: Python returns the mount itself, and so must the kernel). Its
Phasers system is moved onto Ventral Phaser 1's mount, so a parent and its
child share a point on different parts (R3), and the enemies' cannons and
tubes aim at that point: Python's first match is the parent. K2 walks a
posed ship's banks, and K1 aims at a posed Federation ship's mounts.

Both sides fire phasers, pulse (the Birds of Prey's disruptor cannons) and
torpedoes, through public calls on a seeded op stream (StartFiring with and
without an offset, re-target, stop, reload, turn, move, shields), with the
Federation ships LOCKING the Birds of Prey's subsystems (K2's aim on a posed
ship) and aiming tubes at their mounts (K1's `_RESOLVE` on a posed target).
Torpedoes are also launched by hand at the Birds of Prey's mounts on a seeded
schedule (K3 steering on a posed target). Scripted beats make the rest
certain:

* MANUAL: the player in Manual Aim on Enemy-B's posed wing, the pick moving;
* PARENT: a Star Cannon's property SetPhysicalParent'd to the other wing
  mid-fight, then back to Auto (each a part-map generation bump: every slot
  stale until the next step boundary re-resolves it -- the beat checks that
  it IS stale right after the bump);
* PREVIEW: the SPV preview overlay set (the Port Cannon onto the other
  wing, so a mount really moves) and cleared (two more bumps);
* SEVER: from SEVER_AT, the first weapon hit on Enemy-B severs one of its
  wings INSIDE the step (an ET_WEAPON_HIT handler: apply_hit -> sever), and
  the handler checks at once that every mount of the ship reads, natively,
  exactly Python's value -- the severed wing's mounts their REST point
  (Review Focus 2) -- without any re-resolution.

Per tick both arms record everything tests/helpers/k3_fight.py's Recorder
records (torpedoes, ships, eligibility, latches, incoming table, the call
and event logs), and through its `extra` hook: every weapon system's and
weapon's fire-control state, every posed ship's articulation state, part
poses and detached parts, and the world mount position of every subsystem
of every posed ship (Python's, by .hex() -- the native arm also asks the kernel's own
`mount_position` for each and requires the same bits).
"""
import math
import random

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import articulation
from engine.appc import native_combat as nc
from engine.appc import part_pose
from engine.appc import part_severance
from engine.appc import physical_parents
from engine.appc import projectiles
from engine.appc import sensor_contacts
from engine.appc import subsystems as ss
from engine.appc import weapon_subsystems as ws
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import headless_mission
from tests.helpers.fight_audio import isolate_fight_audio
from tests.helpers.k3_fight import (K3Tally, Recorder, aim_velocity,
                                    check_guide_asks, face, fire, hx,
                                    posed_branches, posed_fallbacks,
                                    check_native_attributions,
                                    check_weapon_state_paths,
                                    presented, round_trips,
                                    seed_every_rng, weapon_rows, xyz)

TICKS = 660
OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
RADIUS = 4.0            # combat_stress's nominal hull (headless only)

CRUISE_BOP, SWING_BOP = "Enemy-B", "Enemy-4"
CRUISE_AT = (0.0, 11.0, 2.0)
WINGS = ("left wing", "left wing01")
LEAF = "birdofprey"
POSED_FED, PROBE_PART, PROBE_FLAT = "Friend-3", "probe part", "probe flat"
PROBE_POSE = part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0)
# Identity to `part_pose.is_identity` (within its 1e-9), not to a multiply:
# Python returns the mount itself, so must the kernel (branch, never
# multiply -- spec §4.4).
FLAT_POSE = (part_pose.IDENTITY[0], (5e-10, 0.0, 0.0))
# The Galaxy's banks on the flat part; the rest ride the hinged one.
FLAT_BANKS = ("Ventral Phaser 2", "Ventral Phaser 3", "Ventral Phaser 4")
# R3: the Galaxy's Phasers system is moved onto this bank's mount (the bank
# on the hinged part, the system on none): an offset there is the PARENT's
# by Python's first-match order.
SHARED_BANK = "Ventral Phaser 1"
SHARED_FROM, SHARED_TO, SHARED_EVERY = 100, 600, 30
FEDS = ("Player", "Friend-1", "Friend-2", "Friend-3", "Friend-4")

# A ship's sensors have no range until their power is up (~1 s): the opening
# volley follows it.
VOLLEY_AT = 64
LAUNCH_FROM, LAUNCH_TO, LAUNCH_EVERY = 70, 620, 7
# The swinging Bird of Prey's target toggles (its NPC state red <-> cruise).
TOGGLE_FROM, TOGGLE_TO, TOGGLE_EVERY = 90, 600, 70
# The player in Manual Aim on the cruising Bird of Prey's wing.
MANUAL_FROM, MANUAL_TO, MANUAL_MOVE = 150, 300, 25
# A generation bump: SetPhysicalParent on a wing cannon's property, and back.
PARENT_AT, PARENT_TO = 240, 330
# The SPV preview overlay set and cleared.
PREVIEW_AT, PREVIEW_TO = 420, 480
# From here the next weapon hit on the cruising Bird of Prey severs a wing
# inside the step; shots at it make the hit certain.
SEVER_AT = 360


def _hexes(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def walk(ship):
    """Every subsystem of `ship`: top-level (hull included), then children."""
    out, seen = [], set()

    def visit(sub):
        if sub is None or id(sub) in seen:
            return
        seen.add(id(sub))
        out.append(sub)
        for c in getattr(sub, "_children", None) or ():
            visit(c)
    for sub in ship.GetSubsystems():
        visit(sub)
    return out


def groups(ship):
    return [g for g in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                        ship.GetTorpedoSystem()) if g is not None]


def lockable(ship):
    """The subsystems of `ship` a lock or a tube offset may name: every one
    with an authored mount (the wing cannons, the tube, the engines ...)."""
    return [s for s, _p in part_severance._mounted_subsystems(ship)]


_SEVER = {}


def SeverHandler(_dest, evt):
    """ET_WEAPON_HIT broadcast handler: from SEVER_AT, the first hit on the
    cruising Bird of Prey severs a wing it still has, at the boundary of the
    tick that hit it (the hit's ET_WEAPON_HIT is delivered there: native
    damage M2; before, in the middle of the step). In the native arm every
    mount of the ship is then asked of the kernel at once (no resolution in
    between) and must equal Python's bit for bit; the severed wing's mounts
    must be their rest point."""
    scene = _SEVER.get("scene")
    if scene is None or scene.tick < SEVER_AT or "tick" in _SEVER:
        return
    target = evt.GetTarget()
    if target is None or target.GetName() != CRUISE_BOP:
        return
    bop = target
    wing = next((w for w in WINGS
                 if not part_severance.is_detached(bop, w)), None)
    if wing is None:
        return
    leaf = articulation.leaf_for(bop)
    on_wing = [s for s, p in part_severance._mounted_subsystems(bop)
               if physical_parents.part_for_property(
                   leaf, physical_parents.property_of(s), p) == wing]
    before = {id(s): _hexes(ss._subsystem_world_position(s, None))
              for s in on_wing}
    _SEVER.update(tick=scene.tick, wing=wing, on_wing=len(on_wing),
                  step_open=step_memo.active())
    part_severance.sever(bop, scene.iid(bop), wing)
    rest = moved = checked = 0
    for s in on_wing:
        want = ss._subsystem_world_position(s, None)
        unposed = scene.unposed_mount(s)
        assert _hexes(want) == _hexes(unposed), s.GetName()
        rest += 1
        moved += _hexes(want) != before[id(s)]
    if scene.native:
        for sub, ship_arg in scene.mount_subs(bop):
            want = ss._subsystem_world_position(sub, ship_arg)
            got = _h.combat_test_mount_position(
                sub.__dict__["_nslot"],
                -1 if ship_arg is None else ship_arg.__dict__["_nslot"])
            assert tuple(c.hex() for c in got) == _hexes(want), \
                (sub.GetName(), got, want)
            checked += 1
    _SEVER.update(rest=rest, moved=moved, checked=checked)


class PosedFight:
    """One arm: combat_stress grown into the posed fight (module docstring),
    native switch set after the load. `r` is the renderer module for the
    host file (ships realized: real instances, radii and hull boxes), None
    headless."""

    def __init__(self, mp, env, seed, r=None, setup=None):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        if r is not None:
            # Radii come from the models (realize), as live.
            mp.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
        self.r = r
        self.seed = seed
        nc.reset()
        App.g_kTimerManager._time = 0.0
        seed_every_rng(0)
        headless_mission.clear_in_flight()
        isolate_fight_audio(mp)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        self.player = App.Game_GetCurrentPlayer()
        self.set = self.player.GetContainingSet()
        import loadspacehelper
        bop = loadspacehelper.CreateShip("BirdOfPrey", self.set, CRUISE_BOP,
                                         "")
        assert bop is not None and not App.IsNull(bop)
        bop.SetTranslateXYZ(*CRUISE_AT)
        bop.UpdateNodeOnly()
        self.session = None
        if r is not None:
            self.session = host_loop.MissionSession(mission_name="posed_diff")
            host_loop.realize_set_objects(self.session, self.set, r,
                                          include_planets=False)
        self.ships = list(iter_ships())
        assert len(self.ships) == 10, [s.GetName() for s in self.ships]
        if r is None:
            for s in self.ships:
                s.SetRadius(RADIUS)
        else:
            assert all(s in self.session.ship_instances for s in self.ships)
            assert all(s.GetRadius() > 0.0 for s in self.ships)
        self.by_name = {s.GetName(): s for s in self.ships}
        self.bops = [self.by_name[CRUISE_BOP], self.by_name[SWING_BOP]]
        for b in self.bops:
            assert b.GetScript() == "ships.BirdOfPrey", b.GetScript()
            assert [p.GetName() for p in articulation.parts_for_ship(b)] \
                == list(WINGS)
            assert articulation.leaf_for(b) == LEAF
        face_rng = random.Random(seed + 2)
        for ship in self.ships:
            face(ship, self.foe(face_rng, ship))
        cruise, swing = self.bops
        articulation.force_pose(cruise, "cruise")
        cruise.SetTarget(None)
        swing.SetTarget(self.foe(face_rng, swing))
        assert articulation.state_for(swing) == "red"
        # A Galaxy whose phaser banks ride parts forced by name (the SPV's
        # force_state_poses + SetPhysicalParent; module docstring): K2
        # walks a posed ship's banks, and enemies aim at a posed Federation
        # ship. Its Phasers system is moved onto SHARED_BANK's mount (an
        # SPV move of the system; this load's object, nothing to restore).
        self.galaxy = self.by_name[POSED_FED]
        assert self.galaxy.GetScript() == "ships.Galaxy"
        articulation.force_state_poses(self.galaxy, {PROBE_PART: PROBE_POSE,
                                                     PROBE_FLAT: FLAT_POSE})
        phasers = self.galaxy.GetPhaserSystem()
        for w in ws_weapons(phasers):
            prop = physical_parents.property_of(w)
            mp.setattr(prop, "_physical_parent", prop._physical_parent)
            prop.SetPhysicalParent(PROBE_FLAT if w.GetName() in FLAT_BANKS
                                   else PROBE_PART)
            if w.GetName() == SHARED_BANK:
                p = w.GetPosition()
                self.shared = (p.x, p.y, p.z)
        assert physical_parents.property_of(phasers).GetPhysicalParent() \
            is None
        phasers._position = TGPoint3(*self.shared)
        # The parent is Python's first match at the point, and the parts
        # differ: the child's mount moves with the hinge, the parent's not.
        bank = next(w for w in ws_weapons(phasers)
                    if w.GetName() == SHARED_BANK)
        assert part_severance.authored_mount_subsystem(
            self.galaxy, self.shared) is phasers
        assert tuple(articulation.part_transform_point(
            self.galaxy, self.shared, prop=physical_parents.property_of(
                phasers))) == self.shared
        assert tuple(articulation.part_transform_point(
            self.galaxy, self.shared, prop=physical_parents.property_of(
                bank))) != self.shared
        self.posed = self.bops + [self.galaxy]
        # The properties the PARENT beat writes: back as they were when
        # this arm's context closes (they outlive the mission load).
        self.cannon_props = {}
        for w in ws_weapons(cruise.GetPulseWeaponSystem()):
            prop = physical_parents.property_of(w)
            mp.setattr(prop, "_physical_parent", prop._physical_parent)
            self.cannon_props[w.GetName()] = prop
        self.native = env is ON
        self.stats = {"stale_seen": 0, "record_resolves": 0,
                      "mount_checks": 0, "mounts_posed": 0,
                      "swing_moving": 0, "cruise_ticks": 0,
                      "manual_ticks": 0, "manual_moved": 0,
                      "detached_ticks": 0, "parent_moved": 0,
                      "preview_moved": 0, "emitter_checks": 0}
        if setup is not None:
            setup(self, mp)
        step_memo.forget()
        nc.configure(env)
        assert nc.enabled() is self.native
        self.systems = [g for s in self.ships for g in groups(s)]
        self.weapons = [g.GetWeapon(i) for g in self.systems
                        for i in range(g.GetNumWeapons())]
        self.firing = list(self.systems)
        self.torpedo_systems = [g for g in self.systems
                                if isinstance(g, ws.TorpedoSystem)]
        self.tick = 0
        self.rec = Recorder(mp, self.ships, self.player,
                            ship_instances=(None if self.session is None
                                            else self.session.ship_instances),
                            native=self.native, extra=self.extra_rows)
        for g in self.systems:
            self.rec.labels[id(g)] = "%s/%s" % (g.GetParentShip().GetName(),
                                                g.GetName())
        for w in self.weapons:
            self.rec.labels[id(w)] = "%s/%s" % (
                w.GetParentSubsystem().GetParentShip().GetName(), w.GetName())
        for b in self.posed:
            for sub in walk(b):
                self.rec.labels.setdefault(id(sub), "%s/%s" % (
                    b.GetName(), sub.GetName()))
        if self.native:
            self.rec.tally = K3Tally(_h.combat_k3_next)
            mp.setattr(_h, "combat_k3_next", self.rec.tally)
        _SEVER.clear()
        _SEVER["scene"] = self
        self._handler = __name__ + ".SeverHandler"
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_WEAPON_HIT, self.player, self._handler)

    def close(self):
        App.g_kEventManager.RemoveBroadcastHandler(
            App.ET_WEAPON_HIT, self.player, self._handler)
        self.sever = {k: v for k, v in _SEVER.items() if k != "scene"}
        _SEVER.clear()
        physical_parents.clear_preview(LEAF)
        projectiles._active.clear()
        if self.r is not None:
            host_loop.teardown_set_objects(self.session, self.set, self.r)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def iid(self, ship):
        if self.session is None:
            return None
        return self.session.ship_instances.get(ship)

    def side(self, ship):
        return ship.GetName().startswith("Enemy")

    def foes(self, ship):
        return [s for s in self.ships
                if self.side(s) != self.side(ship) and not s.IsDead()]

    def foe(self, rng, ship):
        foes = self.foes(ship)
        return rng.choice(foes) if foes else None

    def live_bop(self, rng):
        bops = [b for b in self.bops if not b.IsDead()]
        return rng.choice(bops) if bops else None

    def mount_subs(self, bop):
        """(subsystem, explicit ship or None) for every mirrored subsystem of
        `bop`: the hull, whose own climb finds no ship, gets `bop`."""
        hull = bop.GetHull()
        return [(s, bop if s is hull else None) for s in walk(bop)
                if s.__dict__.get("_nslot") is not None]

    @staticmethod
    def unposed_mount(sub, ship=None):
        """The mount with no part transform (the rest point)."""
        if ship is None:
            ship = sub._climb_to_ship()
        p = sub.GetPosition()
        o = TGPoint3(p.x, p.y, p.z)
        o.MultMatrixLeft(ship.GetWorldRotation())
        pos = ship.GetWorldLocation()
        return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)

    def wing_pick(self, rng, wing):
        """A Manual Aim pick inside `wing`'s box that the box rule gives to
        it and no mount claims (so it is a Manual Aim offset, authored
        False), or None if the draw missed."""
        lo, hi = articulation.part_boxes_for(LEAF)[wing]
        bop = self.by_name[CRUISE_BOP]
        for _ in range(20):
            p = tuple(a + rng.uniform(0.2, 0.8) * (b - a)
                      for a, b in zip(lo, hi))
            if (articulation._live_part(bop, None, p, False, None) == wing
                    and part_severance.authored_mount_subsystem(bop, p)
                    is None):
                return p
        return None

    # ── Ops ──────────────────────────────────────────────────────────────────

    def op(self, rng):
        kind = rng.choice(("fed_phasers", "fed_phasers", "fed_torps",
                           "fed_torps", "bop_fire", "bop_fire",
                           "enemy_fire", "retarget", "stop", "reload",
                           "single", "turn", "move", "face", "shields_off",
                           "shields_on", "drain", "unlock"))
        if kind == "fed_phasers":
            # A Federation ship locks a Bird of Prey's subsystem and beams it
            # (K2 aims at the posed lock's mount).
            ship = self.by_name[rng.choice(FEDS)]
            bop = self.live_bop(rng)
            if bop is None or ship.IsDead():
                return
            ship.SetTargetSubsystem(rng.choice(lockable(bop)))
            g = ship.GetPhaserSystem()
            g.SetSingleFire(rng.choice((0, 0, 1)))
            g.StartFiring(bop, rng.choice((None, ship.GetTargetOffsetTG())))
        elif kind == "fed_torps":
            # Tubes at a Bird of Prey's mount (K1 `_RESOLVE` on a posed
            # target; the torpedo then steers there: K3).
            ship = self.by_name[rng.choice(FEDS)]
            bop = self.live_bop(rng)
            torps = ship.GetTorpedoSystem()
            if bop is None or ship.IsDead() or torps is None:
                return
            if rng.random() < 0.6:
                face(ship, bop)
            self.reload(torps)
            torps.StartFiring(bop, rng.choice(lockable(bop)).GetPosition())
        elif kind == "bop_fire":
            # A Bird of Prey fires its wing cannons and tube (K1 walks a
            # posed ship).
            bop = self.live_bop(rng)
            if bop is None:
                return
            target = self.foe(rng, bop)
            if target is None:
                return
            if rng.random() < 0.5:
                face(bop, target)
            cannons = bop.GetPulseWeaponSystem()
            cannons.SetSingleFire(0)
            cannons.StartFiring(target, rng.choice(
                (None, rng.choice(lockable(target)).GetPosition())))
            self.reload(bop.GetTorpedoSystem())
            bop.GetTorpedoSystem().StartFiring(target)
        elif kind == "enemy_fire":
            # Any enemy at a Federation ship, half the time at a mount (the
            # posed Galaxy's included: `_RESOLVE` on its forced part).
            g = rng.choice([g for g in self.firing
                            if self.side(g.GetParentShip())])
            target = self.foe(rng, g.GetParentShip())
            if target is None:
                return
            if isinstance(g, ws.TorpedoSystem):
                self.reload(g)
            g.StartFiring(target, rng.choice(
                (None, rng.choice(lockable(target)).GetPosition())))
        elif kind == "retarget":
            held = [g for g in self.firing if g.__dict__.get("_fire_held")]
            if held:
                g = rng.choice(held)
                ship = g.GetParentShip()
                target = (self.live_bop(rng) if not self.side(ship)
                          else self.foe(rng, ship))
                g.StartFiring(target, None)
        elif kind == "stop":
            rng.choice(self.firing).StopFiring()
        elif kind == "reload":
            self.reload(rng.choice(self.torpedo_systems))
        elif kind == "single":
            rng.choice(self.firing).SetSingleFire(rng.choice((0, 1)))
        elif kind == "turn":
            m = TGMatrix3()
            m.MakeZRotation(rng.uniform(-math.pi, math.pi))
            rng.choice(self.ships).SetMatrixRotation(m)
        elif kind == "move":
            ship = rng.choice(self.ships)
            p = ship.GetTranslate()
            ship.SetTranslateXYZ(p.x + rng.uniform(-2.0, 2.0),
                                 p.y + rng.uniform(-2.0, 2.0),
                                 p.z + rng.uniform(-1.0, 1.0))
        elif kind == "face":
            ship = rng.choice(self.ships)
            target = self.foe(rng, ship)
            if target is not None:
                face(ship, target)
        elif kind in ("shields_off", "shields_on"):
            shields = rng.choice(self.ships).GetShields()
            if shields is not None:
                (shields.TurnOff if kind == "shields_off"
                 else shields.TurnOn)()
        elif kind == "drain":
            w = rng.choice([w for w in self.weapons
                            if isinstance(w, ws._EnergyWeaponFireMixin)])
            w.SetChargeLevel(w.GetMaxCharge() * rng.choice((0.05, 0.3, 1.0)))
        elif kind == "unlock":
            ship = self.by_name[rng.choice(FEDS)]
            if ship is not self.player or not self.manual_window():
                ship.SetTargetSubsystem(None)
        else:
            raise AssertionError(kind)

    @staticmethod
    def reload(torps):
        if torps is None:
            return
        ammo = torps.GetCurrentAmmoType()
        if ammo is not None:
            ammo.SetAvailable(ammo.GetMaxTorpedoes())
        for i in range(torps.GetNumWeapons()):
            torps.GetWeapon(i).SetNumReady(1)
        torps.TurnOn()

    # ── Beats ────────────────────────────────────────────────────────────────

    def manual_window(self):
        return MANUAL_FROM <= self.tick < MANUAL_TO

    def launch(self, rng, src, target, offset):
        """A hand-launched guided torpedo from `src` at `target`'s
        target-local `offset` (a mount point: K3 steers at a posed mount)."""
        if src is None or target is None or src.IsDead() or target.IsDead():
            return
        here = xyz(src.GetWorldLocation())
        there = xyz(target.GetWorldLocation())
        start = [here[i] + c for i, c in enumerate(
            aim_velocity(here, there, src.GetRadius() + 1.0))]
        spread = (rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0),
                  rng.uniform(-0.5, 0.5))
        fire(src, start, aim_velocity(start, there, rng.uniform(20.0, 30.0),
                                      spread),
             target=target, offset=offset, ttl=rng.choice((2.0, 4.0)),
             guidance=rng.choice((1.5, 4.0)), accel=rng.choice((1.0, 2.5)))

    def beats(self, rng):
        t = self.tick
        cruise, swing = self.bops
        if t == VOLLEY_AT:
            for g in self.firing:
                ship = g.GetParentShip()
                g.TurnOn()
                g.SetSingleFire(0)
                if self.side(ship):
                    g.StartFiring(self.foe(rng, ship), None)
                else:
                    bop = self.live_bop(rng)
                    ship.SetTargetSubsystem(rng.choice(lockable(bop)))
                    g.StartFiring(bop, ship.GetTargetOffsetTG())
            for torps in self.torpedo_systems:
                self.reload(torps)
        if LAUNCH_FROM <= t <= LAUNCH_TO and t % LAUNCH_EVERY == 0:
            bop = self.live_bop(rng)
            if bop is not None:
                fed = self.by_name[rng.choice(FEDS)]
                self.launch(rng, fed, bop,
                            rng.choice(lockable(bop)).GetPosition())
                target = self.foe(rng, bop)
                if target is not None:
                    self.launch(rng, bop, target,
                                rng.choice((None, rng.choice(
                                    lockable(target)).GetPosition())))
        if (TOGGLE_FROM <= t <= TOGGLE_TO
                and (t - TOGGLE_FROM) % TOGGLE_EVERY == 0
                and not swing.IsDead()):
            swing.SetTarget(None if swing.GetTarget() is not None
                            else self.foe(rng, swing))
        self.manual_beat(rng)
        if t in (PARENT_AT, PARENT_TO):
            prop = self.cannon_props["Star Cannon"]
            if t == PARENT_AT:
                w = next(w for w in ws_weapons(cruise.GetPulseWeaponSystem())
                         if w.GetName() == "Star Cannon")
                p = w.GetPosition()
                now = physical_parents.part_for_property(
                    LEAF, prop, (p.x, p.y, p.z))
                assert now in WINGS, now
                before = _hexes(ss._subsystem_world_position(w, None))
                prop.SetPhysicalParent(WINGS[1 - WINGS.index(now)])
                after = _hexes(ss._subsystem_world_position(w, None))
                self.stats["parent_moved"] += before != after
            else:
                prop.SetPhysicalParent(None)
            self.check_stale()
        if t == PREVIEW_AT:
            # The Port Cannon previewed onto the OTHER wing, so the preview
            # really moves a mount (as the PARENT beat does).
            prop = self.cannon_props["Port Cannon"]
            w = next(w for w in ws_weapons(cruise.GetPulseWeaponSystem())
                     if w.GetName() == "Port Cannon")
            p = w.GetPosition()
            now = physical_parents.part_for_property(
                LEAF, prop, (p.x, p.y, p.z))
            assert now in WINGS, now
            before = _hexes(ss._subsystem_world_position(w, None))
            physical_parents.set_preview(
                LEAF, {prop.GetName(): WINGS[1 - WINGS.index(now)]})
            after = _hexes(ss._subsystem_world_position(w, None))
            self.stats["preview_moved"] += before != after
            self.check_stale()
        elif t == PREVIEW_TO:
            physical_parents.clear_preview(LEAF)
            self.check_stale()
        if (SHARED_FROM <= t <= SHARED_TO
                and (t - SHARED_FROM) % SHARED_EVERY == 0
                and not self.galaxy.IsDead()):
            # Pulse and tubes at the shared point (K1 `_RESOLVE`: the first
            # subsystem there is the Phasers system, the parent).
            for name in ("Enemy-1", "Enemy-2", "Enemy-3"):
                ship = self.by_name[name]
                for g in groups(ship):
                    if isinstance(g, ws.PhaserSystem) or ship.IsDead():
                        continue
                    if isinstance(g, ws.TorpedoSystem):
                        self.reload(g)
                    face(ship, self.galaxy)
                    g.SetSingleFire(0)
                    g.StartFiring(self.galaxy, TGPoint3(*self.shared))
        if SEVER_AT <= t < SEVER_AT + 120 and t % 3 == 0 \
                and "tick" not in _SEVER and not cruise.IsDead():
            self.launch(rng, self.player, cruise, None)

    def manual_beat(self, rng):
        t = self.tick
        cruise = self.by_name[CRUISE_BOP]
        if t == MANUAL_FROM or (self.manual_window()
                                and (t - MANUAL_FROM) % MANUAL_MOVE == 0):
            if cruise.IsDead():
                return
            pick = self.wing_pick(rng, rng.choice(WINGS))
            if pick is None:
                return
            self.player.SetTarget(cruise)
            self.player.set_manual_target_offset(TGPoint3(*pick))
            self.stats["manual_moved"] += tuple(
                articulation.part_transform_point(
                    cruise, pick, authored=False)) != pick
            if t == MANUAL_FROM:
                for g in groups(self.player):
                    g.TurnOn()
                    g.SetSingleFire(0)
                    if isinstance(g, ws.TorpedoSystem):
                        self.reload(g)
                    g.StartFiring(cruise, self.player.GetTargetOffsetTG())
        elif t == MANUAL_TO:
            self.player.UseTargetOffsetTG(0)
        if self.manual_window() and self.player.is_using_target_offset():
            self.stats["manual_ticks"] += 1

    def check_stale(self):
        """Right after a part-map generation bump, before any step boundary:
        a posed ship's mount slot reads stale natively (the kernel would
        fall back, never read the old part)."""
        if not self.native:
            return
        for bop in self.posed:
            if not nc._posed_flag(bop):
                continue
            sub, ship_arg = next((s, a) for s, a in self.mount_subs(bop)
                                 if a is None)
            try:
                _h.combat_test_mount_position(sub.__dict__["_nslot"], -1)
            except ValueError as e:
                assert "part_stale" in str(e), e
                self.stats["stale_seen"] += 1

    # ── Record ───────────────────────────────────────────────────────────────

    def extra_rows(self):
        rows = weapon_rows(self.rec.label, self.systems, self.weapons)
        cruise, swing = self.bops
        for bop in self.posed:
            d = bop.__dict__
            poses = d.get("_articulation_poses") or {}
            rows.append((bop.GetName(), articulation.state_for(bop),
                         sorted(d.get("_articulation_transitions") or ()),
                         sorted(part_severance.detached_parts(bop)),
                         [(n, tuple(hx(c) for row in poses[n][0]
                                    for c in row),
                           tuple(hx(c) for c in poses[n][1]))
                          for n in sorted(poses)]))
            rows.append((bop.GetName() + " mounts", self.mounts(bop)))
            rows.append((bop.GetName() + " emitters", self.emitters(bop)))
        self.stats["swing_moving"] += bool(
            swing.__dict__.get("_articulation_transitions"))
        self.stats["cruise_ticks"] += articulation.state_for(cruise) \
            == "cruise" and nc._posed_flag(cruise) == 1
        self.stats["detached_ticks"] += bool(
            part_severance.detached_parts(cruise))
        return rows

    def mounts(self, bop):
        """Every mount of `bop` by Python, .hex(); in the native arm the
        kernel's own answer must be the same bits."""
        out = []
        for sub, ship_arg in self.mount_subs(bop):
            want = ss._subsystem_world_position(sub, ship_arg)
            out.append(_hexes(want))
            self.stats["mounts_posed"] += _hexes(want) != _hexes(
                self.unposed_mount(sub, ship_arg))
            if not self.native:
                continue
            args = (sub.__dict__["_nslot"],
                    -1 if ship_arg is None else ship_arg.__dict__["_nslot"])
            try:
                got = _h.combat_test_mount_position(*args)
            except ValueError as e:
                # Bumped after this step's last boundary (a sever's
                # destroyed subsystem, say): what the next boundary does.
                assert "part_stale" in str(e), e
                self.stats["record_resolves"] += 1
                nc.resolve_stale_part_slots([bop])
                got = _h.combat_test_mount_position(*args)
            assert tuple(c.hex() for c in got) == _hexes(want), (
                self.tick, sub.GetName(), got, want)
            self.stats["mount_checks"] += 1
        return out

    def emitters(self, ship):
        """Every weapon of the posed `ship`: its world forward, whether its
        arc holds each live foe, and (a phaser bank) its strip emit point at
        each, by .hex(): the forward the kernel's (fire control's one copy
        since its Python copy was deleted, M3), the arc and strip Python's,
        the native arm requiring the kernel's own bits. Arc, strip and cone DIRECTIONS are never posed (MAP R7):
        only the emit point's centre follows the part."""
        out = []
        if ship.IsDead():
            return out
        foes = [xyz(f.GetWorldLocation()) for f in self.foes(ship)][:3]
        sh = ship.__dict__["_nslot"]
        for g in groups(ship):
            for w in ws_weapons(g):
                h = w.__dict__["_nslot"]
                fwd = tuple(v.hex() for v in
                            _h.combat_test_emitter_forward_world(h, sh))
                c = xyz(ss._subsystem_world_position(w, None))
                aims = []
                for f in foes:
                    d = [f[i] - c[i] for i in range(3)]
                    n = math.sqrt(sum(v * v for v in d)) or 1.0
                    aims.append(TGPoint3(d[0] / n, d[1] / n, d[2] / n))
                arcs = [bool(ws._emitter_in_arc(w, ship, a)) for a in aims]
                strips = ([_hexes(w._strip_emit_position(TGPoint3(*f)))
                           for f in foes]
                          if isinstance(w, ws.PhaserBank) else [])
                out.append((fwd, arcs, strips))
                if not self.native:
                    continue
                for a, want in zip(aims, arcs):
                    assert _h.combat_test_emitter_in_arc(
                        h, sh, (a.x, a.y, a.z)) is want, (
                        self.tick, w.GetName())
                for f, want in zip(foes, strips):
                    got = _h.combat_test_strip_emit_position(h, f, False)
                    assert tuple(v.hex() for v in got) == want, (
                        self.tick, w.GetName(), got, want)
                self.stats["emitter_checks"] += 1
        return out

    # ── Run ──────────────────────────────────────────────────────────────────

    def sync_render(self):
        if self.session is None:
            return
        for ship, iid in self.session.ship_instances.items():
            self.r.set_world_transform(
                iid, host_loop._ship_world_matrix(ship,
                                                  host_loop.BC_MODEL_SCALE))

    def run(self, ticks_per_frame, ticks=TICKS, before_tick=None):
        rng = random.Random(self.seed)
        beat_rng = random.Random(self.seed + 1)
        instances = (None if self.session is None
                     else self.session.ship_instances)
        p_op = 0.08 * ticks_per_frame
        while self.tick < ticks:
            if rng.random() < p_op:
                self.op(rng)
            self.sync_render()
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
                                              ship_instances=instances,
                                              player=self.player,
                                              push_render_data=False)
                host_loop._combat_tick_boundary()   # as the host does (native damage)
                self.rec.record()
                if rng.random() < 0.04:
                    self.op(rng)
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        self.audit = []
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert not _h.combat_k3_open()
            assert _h.combat_k1_depth() == 0
            assert not _h.combat_k2_open()
        self.counts = nc.counts()
        return self


def ws_weapons(system):
    return [system.GetWeapon(i) for i in range(system.GetNumWeapons())]


def both(monkeypatch, ticks_per_frame, seed, r=None, ticks=TICKS,
         setup=None, before_tick=None):
    """The Python arm, then the native arm; each closed before the next.
    `setup(scene, mp)` runs before the native switch is set, `before_tick(
    scene)` after each tick's beats."""
    from tests.helpers.k3_fight import compare
    runs = []
    for env in (OFF, ON):
        with monkeypatch.context() as mp:
            scene = PosedFight(mp, env, seed, r=r, setup=setup)
            try:
                runs.append(scene.run(ticks_per_frame, ticks=ticks,
                                      before_tick=before_tick))
            finally:
                scene.close()
    ref, nat = runs
    compare(ref.rec, nat.rec)
    assert nat.audit == [], nat.audit
    assert ref.counts.get("k3_runs", 0) == 0, ref.counts
    # Fire control is native in both arms (fire control native only, M9):
    # the reference is the Python of K0, K2, K3, K4 and damage only.
    assert ref.counts["k1_records"] > 0, ref.counts
    assert ref.counts["k2_records"] == 0, ref.counts
    # The sever happened alike (the native arm also checked its mounts).
    same = [{k: v for k, v in d.items() if k != "checked"}
            for d in (ref.sever, nat.sever)]
    assert same[0] == same[1], (ref.sever, nat.sever)
    return ref, nat


def report(label, ticks_per_frame, elapsed, ref, nat):
    c = nat.counts
    print("\n%s (tpf=%d): %.1f s for 2 x %d ticks\n  posed branches %r\n"
          "  posed fallbacks %r\n  scene %r\n"
          "  sever %r\n  k1 no-fire %r\n  k2 python reasons %r\n"
          "  k3 steer reasons %r\n  k3 asks %r\n  kernel records %r\n"
          "  round trips %r\n"
          "  hits %d, presented %d, events %d, presentation calls %d"
          % (label, ticks_per_frame, elapsed, TICKS, posed_branches(c),
             {k: v for k, v in posed_fallbacks(c).items() if v},
             nat.stats, nat.sever,
             {k: v for k, v in c["k1_no_fire"].items() if v},
             {k: v for k, v in c["k2_python_reasons"].items() if v},
             {k: v for k, v in c["k3_steer_reasons"].items() if v},
             c["k3_asks"], dict(sorted(nat.rec.tally.n.items())),
             round_trips(c),
             len([x for x in ref.rec.calls if x[0] == "hit"]),
             len([x for x in ref.rec.calls if x[0] == "hit_present"]),
             len(ref.rec.events), presented(ref.rec.calls)))


def check_posed(ref, nat):
    """What both posed differentials assert of the native arm."""
    c = nat.counts
    # No posed hand-back: every slot was current when a kernel read it.
    assert set(posed_fallbacks(c).values()) == {0}, posed_fallbacks(c)
    # Every posed branch ran in the kernel.
    branches = posed_branches(c)
    for key in ("k1_posed/walks", "k1_posed/target_aims",
                "k2_posed/banks", "k2_posed/lock_aims", "k3_posed_steers"):
        assert branches[key] > 0, (key, branches)
    # No whole-step or whole-system hand-back either.
    assert not any(c["k1_no_fire"].values()), c["k1_no_fire"]
    assert c["k2_python_ships"] == 0 and c["k2_python_steps"] == 0, c
    # No posed aim handed to Python by K2 either (Task 2 review: Manual Aim
    # on a posed target is a plain body point, M5).
    assert c["k2_ask_queries"].get("aim_point", 0) == 0, c["k2_ask_queries"]
    assert c["k3_runs"] > 0 and c["k3_python_steps"] == 0, c
    check_guide_asks(c, nat.rec.tally, expected=())
    # Every round trip the plan removed ran on and at posed ships: K1 walks
    # with no WALK_START, sustains and idle stops logged (Tasks 1-2), K2
    # resting contacts queued for the drain (Task 3; spec 2026-11-02 §4.3),
    # K3 mounts attributed (Task 4). K2's
    # logged offline stop is the host file's (measured 0 headless).
    trips = round_trips(c)
    for key in ("k1_logged/walk_start", "k1_logged/beam_sustain",
                "k1_logged/idle_bank_stop", "k2_batched_contacts"):
        assert trips[key] > 0, (key, trips)
    check_native_attributions(c, nat.rec.tally)
    # K0 charged and reloaded every weapon, writes were C-applied and scalar
    # pushes made in one call (native weapon state).
    check_weapon_state_paths(c)
    # ... and their presentation was compared (per tick, compare_calls).
    assert presented(ref.rec.calls) > 0
    # The scene was what it claims, in both arms alike.
    s = nat.stats
    assert ref.stats == {k: (0 if k in ("stale_seen", "record_resolves",
                                        "mount_checks", "emitter_checks")
                             else v)
                         for k, v in s.items()}, (ref.stats, s)
    assert s["cruise_ticks"] > 0.5 * TICKS, s       # settled in cruise
    assert s["swing_moving"] > 0.3 * TICKS, s       # always swinging
    assert s["mounts_posed"] > 0, s                  # mounts really moved
    assert s["manual_ticks"] > 100 and s["manual_moved"] > 0, s
    assert s["parent_moved"] == 1, s                 # the PARENT beat moved
    assert s["preview_moved"] == 1, s                # the PREVIEW beat moved
    # Every mount query was answered at a current slot: none needed the
    # mid-step re-resolve.
    assert s["record_resolves"] == 0, s
    # Each generation bump made the slots stale (read natively right after
    # it), and the next boundary made them fresh: no part_stale above.
    assert s["stale_seen"] >= 4, s
    assert s["mount_checks"] > 10 * TICKS, s
    assert s["emitter_checks"] > 10 * TICKS, s
    # A wing came off at a tick's boundary, outside the step (native damage
    # M2), and the very next native query of every mount gave Python's
    # bits, the severed wing's its rest point.
    sev = nat.sever
    assert sev.get("step_open") is False, sev
    assert sev["on_wing"] > 0 and sev["rest"] == sev["on_wing"], sev
    assert sev["moved"] > 0, sev            # the wing was posed when cut
    assert sev["checked"] > 0, sev
    assert s["detached_ticks"] > 0, s
    # The fight happened: hits with their payload, phasers, cannons and
    # tubes all fired at and by the Birds of Prey.
    hits = [e for e in ref.rec.events if e[0] == App.ET_WEAPON_HIT]
    assert hits and all(e[4] is not None for e in hits)
    targets = {e[4][7] for e in hits}
    assert {"Enemy-B", "Enemy-4"} <= targets, targets
    fired = {e[1].split("/")[0] for e in ref.rec.queued.rows
             if e[0] in (App.ET_WEAPON_FIRED, App.ET_TORPEDO_FIRED)}
    assert {"Enemy-B", "Enemy-4", "Player"} <= fired, fired
