"""K2 beams are bit-identical to the Python `cb.phasers` step in a fight with
REAL render instances (native combat phase 2, Task 6; plan
docs/superpowers/plans/2026-10-31-native-combat-k2-beams.md; spec §7; map
§8.3.1).

The 1a/1b differentials are headless: `ship_instances` is None, so every
beam lands on its aim point (no hull trace, no sphere tier), and no hull box
is cached, so the shield bubble is never met. This one boots the headless
host (a real `g_world`), loads combat_stress (8 AI ships and the player:
Sovereign, Akira, Galaxy, Nebula against a Warbird, a Vor'cha, a Galor and a
Bird of Prey) and realizes every ship through host_loop's own
`realize_set_objects` -- the live path, which loads each NIF, creates its
instance, seeds its radius from the model and caches its shield hull box
(`_cache_shield_hull_box`). `session.ship_instances` is the session's
TrackedInstances, so K2 traces natively through the renderer's own compiled
trace.

Two fresh loads -- Python (``DAUNTLESS_NATIVE_COMBAT=0``) and native
(``=1``) -- get the same seeded stream of public operations: fire, re-target,
stop, single fire, systems off and on, damaged banks, ships moved and
turned, shields off and on, cloaks started and stopped, a subsystem locked on
a ship OTHER than the one fired at, Manual Aim on, moved and off, banks lit
by hand (no held trigger: only `cb.phasers` drives them). On top of the
stream, scripted beats at fixed ticks make the rare branches certain: an
opening volley once the sensors are powered; one ship posed off its NIF pose
while a foe locks it; the point-blank rig (strip F7: the target's centre IS a
bank's mount, with the bank's world forward all negative, so only F7's zero
test keeps the yaw at 0); the reversed-arc rig (strip F8: the Akira's stock
high-to-low widths, lit at targets inside the sorted arc); the arc-fail
beat (a lock astern, mid-beam: the partial pulse); a phaser system off for a
stretch.

RENDER SYNC. The trace reads `g_world` as last synced, not the sim pose
(map §1.4, §8.3.9). Both arms sync at the same point of the same frame
sequence: at the top of each frame every realized ship's instance is set to
host_loop's own `_ship_world_matrix` (what the realize path pushes); the
ops that follow in that frame (moves, turns) are seen by the sim at once but
by the trace only at the next frame's sync, so the trace runs on a stale
pose for the rest of the frame, as it does live in a catch-up frame.

After every tick the two arms compare (floats by .hex(), every other value
with its type): every phaser bank's `_dwell`, `_firing`, `_target` and
`_beam_on_countdown`; every phaser system's held-fire state; every ship's
death flag, hull condition and six shield faces; the ordered call log of
every bank and phaser-system StopFiring that runs with a bank firing (an
idle one is logged writes, round trips Tasks 2-3), every
hit_feedback.beam_contact (all arguments, and the shields_block it acted on;
a shielded one stands out of the compare for the shield hit it makes),
every hit VFX spawn and shield hit those make -- and every shield splash the
K2 drain presents natively, from its capture (all arguments: the
presentation, round trips Task 5; per tick as a multiset, since K2 presents
resting contacts after the step's last record -- spec 2026-11-02 §4.4, §5,
Q1)
and every hit as its HIT_PRESENT delivers it (all inputs: K2 applies its
damage pulses in the walk, native damage Task 4); and the full ordered event
log,
with each ET_WEAPON_HIT's payload. The native arm must show that every
branch the scene is built for really happened in the KERNEL (the record
stream, tallied as it is returned, and the drained resting contacts, those
the drain presented natively included):
contacts on the mesh and the sphere
tier, bubble entries, windup contacts, pulses (applied in the walk: no
CONTACT record), arc-fail partial pulses,
firing banks' stops (logged with their LOOP_STOP since combat fire events
Task 4: no BANK_STOP / SYSTEM_STOP record), a lock on another ship, Manual Aim on and off, a cloaking
target and a posed ship (walked natively, and a lock on it aimed natively:
posed parts, Task 4) -- and end with a clean mirror audit.
"""
import math
import os
import random
import sys
import time

import pytest

import App
from tests.helpers import bc_assets

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_next"),
    reason="native K2 bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import articulation  # noqa: E402
from engine.appc import combat  # noqa: E402
from engine.appc import effect_queue  # noqa: E402
from engine.appc import hit_feedback  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_pose  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc import sensor_contacts  # noqa: E402
from engine.appc import weapon_subsystems as ws  # noqa: E402
from engine.appc.events import WeaponHitEvent  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.ship_iter import iter_ships  # noqa: E402
from engine.core import loop as game_loop  # noqa: E402
from engine.core import step_memo  # noqa: E402
from engine.core.loop import TICK_DELTA  # noqa: E402
from engine.core.tracked_instances import TrackedInstances  # noqa: E402
from tests.helpers import effect_split, headless_mission  # noqa: E402
from tests.helpers.fight_audio import isolate_fight_audio  # noqa: E402
from tests.helpers.k3_fight import (  # noqa: E402
    capture_native_shield_hits, compare_calls, contact_row, presented,
    spy_hits, spy_presentation)

GALAXY_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")

TICKS = 600
SEED = 20261031
OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
# A ship's sensors have no range (it detects nothing, so StartFiring holds
# nothing) until its sensors' power comes up at 1.0 s of game time: the
# opening volley is after that.
VOLLEY_AT = 64
# One ship off its NIF pose for a stretch, locked and fired at by a foe.
POSED, POSER = "Friend-1", "Enemy-2"
POSE_FROM, POSE_TO = 120, 200
# The point-blank rig (F7): a foe parked exactly on a bank's mount.
RIG_SHIP, RIG_BANK, RIG_TARGET = "Friend-3", "Dorsal Phaser 2", "Enemy-3"
RIG_FROM, RIG_TO = 300, 330
# The reversed-arc rig (F8): the Akira's stock Ventral Phasers 1 and 4 have
# their width authored high-to-low; each is lit at a target inside its arc.
CLAMP_SHIP = "Friend-2"
CLAMP_BANKS = (("Ventral Phaser 1", "Enemy-3", -0.6),
               ("Ventral Phaser 4", "Friend-4", 0.6))
CLAMP_FROM, CLAMP_TO = 360, 390
# The arc-fail beat: the player holds every bank on one foe; mid-beam it
# locks a subsystem on another foe parked astern.
ARC_HELD, ARC_LOCK = "Enemy-3", "Enemy-4"
ARC_FIRE, ARC_LOCK_AT = 440, 500
# A phaser system switched off for a stretch: stopped every tick (logged
# writes; a bank lit on it also queues its LOOP_STOP).
OFF_SHIP, OFF_FROM, OFF_TO = "Friend-4", 540, 560


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
            r.init(256, 256, "native-k2-differential")
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
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()


# ── Values ───────────────────────────────────────────────────────────────────

def _t(v):
    """A value with its type; floats by .hex(), points by their hexes."""
    if v is None:
        return None
    if isinstance(v, float):
        return ("float", v.hex())
    if isinstance(v, TGPoint3):
        return ("TGPoint3",) + tuple(float(c).hex() for c in (v.x, v.y, v.z))
    if isinstance(v, (tuple, list)) and len(v) == 3:
        return ("seq",) + tuple(float(c).hex() for c in v)
    return (type(v).__name__, v)


def _seed_every_rng(seed):
    """Every RNG a fight draws on (the K1 differential's list)."""
    from engine.appc import collision_avoidance
    from engine.appc import presentation_rng
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()
    presentation_rng.reset()


def _xyz(p):
    return (p.x, p.y, p.z)


def _subsystems(ship):
    return [s for s in (ship.GetPowerSubsystem(), ship.GetSensorSubsystem(),
                        ship.GetImpulseEngineSubsystem(), ship.GetShields(),
                        ship.GetPhaserSystem())
            if s is not None]


# ── The kernel's record stream, tallied in the native arm ───────────────────

def _k1_stop() -> bool:
    """Whether the StopFiring running now is one a kernel stands in for:
    K1's -- the held-weapon pump's, or a walk's (update_weapons, run_k1),
    since combat fire events Task 3 -- or K2's -- the phaser step's
    (_phaser_step_ship / _phaser_step_bank, run_k2), since Task 4 -- or
    K0's, a bank drained dry in the weapons step (_advance_weapons), since
    Task 4 too. They log those, a firing bank's included, and queue its
    LOOP_STOP (no Python call natively), so the compared call log leaves
    them to the per-tick record and the queued list (a stop Python makes
    there in the native arm -- a ship or weapon a kernel hands back -- is
    left out in both arms alike)."""
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_name in ("_pump_held_weapons", "update_weapons",
                                "run_k1", "_phaser_step_ship",
                                "_phaser_step_bank", "run_k2",
                                "_advance_weapons"):
            return True
        f = f.f_back
    return False


class _Tally:
    """Wraps combat_k2_next: every record the kernel returns is classified
    BEFORE Python acts on it (the objects are read off the live mirror
    registry, which still equals Python at that point)."""

    def __init__(self, scene):
        self.scene = scene
        self.n = {}
        self.kinds = None
        self.last_stop = None
        self.firing = set()

    def bump(self, key, by=1):
        self.n[key] = self.n.get(key, 0) + by

    def __call__(self):
        # Which banks fire before the call: a pulse CONTACT whose bank no
        # longer fires was stopped in this call -- the arc fail's stop,
        # logged since combat fire events Task 4 (no BANK_STOP before it).
        self.firing = {b.__dict__.get("_nslot") for b in self.scene.banks
                       if b.__dict__.get("_firing")}
        rec = self.orig()
        if self.kinds is None:
            k = _h.combat_k2_kinds()
            self.kinds = {v: name for name, v in k.items()}
        kind = self.kinds[rec[0]]
        self.bump(kind)
        if kind == "BANK_STOP":
            self.last_stop = rec[1]
            return rec
        if kind == "ASK":
            return rec
        if kind == "CONTACT":
            self.contact(rec[1:15])
        self.pulses()
        self.last_stop = None
        return rec

    def pulses(self):
        """The damage pulses the kernel applied in its walk since the last
        record (native damage Task 4: no CONTACT record), each tallied as a
        pulse of its bank, target and ship."""
        reg = nc._registry
        for bh, th, bubble, tier in _h.combat_k2_last_hits():
            bank, target = reg.get(bh), reg.get(th)
            self.bump("native_pulse")
            self.bump("tier:" + tier)
            if bubble:
                self.bump("bubble")
            self.objects(bh, bank, target, bank.GetParentShip(), 1.0)

    def drain(self):
        """Wraps combat_k2_drain: the resting contacts queued for the drain,
        each tallied as it is handed over (after DONE, before Python
        presents it)."""
        entries = self.orig_drain()
        for e in entries:
            self.bump("queued_contact")
            self.contact(e[:14])
        return entries

    def native(self, item):
        """A rest the drain presented natively (its capture,
        capture_native_shield_hits): a shielded resting contact, tallied by
        what its bank, target and ship say (the capture has no trace tier or
        bubble)."""
        bh, th = item[0], item[1]
        reg = nc._registry
        bank, target = reg.get(bh), reg.get(th)
        self.bump("native_contact")
        self.bump("shields:True")
        self.objects(bh, bank, target, bank.GetParentShip(), 0.0)

    def contact(self, c):
        """One contact's fields, CONTACT's layout from `bank` to
        `flush_dwell` (a CONTACT record's, or a drained rest's)."""
        (bh, th, sh, _yh, _e, _tp, _dist, _aim, _impact, normal, tier,
         bubble, shields, flush) = c
        reg = nc._registry
        bank, target, ship = reg.get(bh), reg.get(th), reg.get(sh)
        self.bump("tier:" + tier)
        if bubble is not None:
            self.bump("bubble")
        if shields is not None:
            self.bump("shields:%s" % bool(shields))
        self.objects(bh, bank, target, ship, flush)

    def objects(self, bh, bank, target, ship, flush):
        """The branches a contact's bank, target and ship show."""
        if flush > 0.0:
            self.bump("pulse")
            if self.last_stop == bh or (bh in self.firing
                                        and not bank.__dict__.get("_firing")):
                self.bump("arc_fail_pulse")
        elif bank.__dict__.get("_beam_on_countdown", 0.0) > 0.0:
            self.bump("windup_contact")
        if ship.is_using_target_offset():
            self.bump("manual_on")
        else:
            self.bump("manual_off")
            lock = ship.__dict__.get("_target_subsystem")
            if lock is not None and lock.GetParentShip() is not target:
                self.bump("lock_other_ship")
        if bank.__dict__["_arc_width_lo"] > bank.__dict__["_arc_width_hi"]:
            self.bump("reversed_arc")
        if (RIG_FROM <= self.scene.tick < RIG_TO
                and ship.GetName() == RIG_SHIP
                and target.GetName() == RIG_TARGET
                and bank.GetName() == RIG_BANK):
            self.bump("point_blank")
        cloak = target.GetCloakingSubsystem()
        if cloak is not None and (cloak.IsCloaking() or cloak.IsDecloaking()):
            self.bump("cloaking_target")


# ── The scene ────────────────────────────────────────────────────────────────

class _Scene:
    """combat_stress, loaded fresh and realized on the real host, with the
    native switch set after the load; the op stream, the per-tick record,
    the call log and the event log."""

    # Record the RAW passive asleep flag of each bank (only meaningful with
    # K0 stood down: K0 puts no weapon to sleep, so with it running the flag
    # differs by design and the record keeps "asleep while NOT at rest"
    # instead; as the K1 differential).
    raw_asleep = False

    def __init__(self, mp, r, env):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        # Radii come from the models (realize), as live: not the headless
        # mission's nominal 4 GU.
        mp.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
        self.r = r
        nc.reset()
        App.g_kTimerManager._time = 0.0
        _seed_every_rng(0)
        headless_mission.clear_in_flight()
        # A hit sound is one SDK RNG draw, so whether a hit plays one must
        # be decided by the fight alone: tests/helpers/fight_audio.
        isolate_fight_audio(mp)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        self.player = App.Game_GetCurrentPlayer()
        self.set = self.player.GetContainingSet()
        self.session = host_loop.MissionSession(mission_name="k2_diff")
        assert type(self.session.ship_instances) is TrackedInstances
        host_loop.realize_set_objects(self.session, self.set, r,
                                      include_planets=False)
        self.ships = list(iter_ships())
        assert len(self.ships) == 9
        assert all(s in self.session.ship_instances for s in self.ships)
        assert all(getattr(s, "_shield_hull_box", None) is not None
                   for s in self.ships)
        face = random.Random(SEED + 2)
        for ship in self.ships:
            self.face(ship, self._enemy_of(face, ship))
        step_memo.forget()
        nc.configure(env)
        assert nc.enabled() is (env is ON)
        self.native = env is ON
        self.systems = [s.GetPhaserSystem() for s in self.ships
                        if s.GetPhaserSystem() is not None]
        self.banks = [g.GetWeapon(i) for g in self.systems
                      for i in range(g.GetNumWeapons())]
        self.cloakers = [s for s in self.ships
                         if s.GetCloakingSubsystem() is not None]
        assert self.cloakers and len(self.systems) >= 8, self.systems
        self.labels = {id(s): s.GetName() for s in self.ships}
        for s in self.ships:
            for sub in _subsystems(s) + [s.GetHull()]:
                self.labels.setdefault(
                    id(sub), "%s/%s" % (s.GetName(), sub.GetName()))
        for b in self.banks:
            self.labels[id(b)] = "%s/%s" % (
                b.GetParentSubsystem().GetParentShip().GetName(), b.GetName())
        self.held = []
        self.tick = 0
        self.log = []
        self.calls = []
        self.events = []
        self.lists = {}         # id(system) -> its last recorded _target_list
        self.tally = None
        self.killed_at = None
        self.scopes = effect_split.Scopes(mp)
        self._spy(mp)
        if self.native:
            self.tally = _Tally(self)
            self.tally.orig = _h.combat_k2_next
            self.tally.orig_drain = _h.combat_k2_drain
            mp.setattr(_h, "combat_k2_next", self.tally)
            mp.setattr(_h, "combat_k2_drain", self.tally.drain)
            capture_native_shield_hits(mp, self.tally.native)

    def close(self):
        host_loop.teardown_set_objects(self.session, self.set, self.r)

    # ── Spies ────────────────────────────────────────────────────────────────

    def _spy(self, mp):
        bank_stop = ws.PhaserBank.StopFiring
        sys_stop = ws.PhaserSystem.StopFiring
        beam_contact = hit_feedback.beam_contact

        def bank_spy(bank, _orig=bank_stop):
            # A FIRING bank's stop only: a stop of a bank not firing is pure
            # field writes, which K1 logs with no call (round trips Task 2);
            # its effect is in the per-tick record. Nor one of K1's: K1 logs
            # a firing bank's stop too (combat fire events Task 3).
            if bank.__dict__.get("_firing") and not _k1_stop():
                self.calls.append(("bank_stop", self.tick, self.label(bank)))
            return _orig(bank)

        def sys_spy(sys_, *args, _orig=sys_stop):
            # A stop with a bank FIRING only: an offline system whose banks
            # are all idle is stopped with logged writes and no call (round
            # trips Task 3); its effect is in the per-tick record.
            if any(b.__dict__.get("_firing")
                   for b in sys_.__dict__.get("_children", ())) \
                    and not _k1_stop():
                self.calls.append(("system_stop", self.tick,
                                   self.label(sys_)))
            return _orig(sys_, *args)

        def contact_spy(**kw):
            if "shields_block" in kw:
                acted = kw["shields_block"]
            else:
                acted = bool(combat.shields_block(kw["ship"]))
            # A shielded contact on a target with an instance id is a
            # ShieldedContact: its shield hit stands for it in the compare
            # (the drain presents most of them natively, with no
            # beam_contact call; spec 2026-11-02 §4.4).
            self.calls.append(contact_row((
                "beam_contact", self.tick, self.label(kw["ship"]),
                self.label(kw["source"]), _t(kw["point"]), _t(kw["normal"]),
                _t(kw["shield_point"]), _t(kw["tick_damage"]),
                kw["ship_instances"] is self.session.ship_instances,
                _t(kw.get("weapon_type")), _t(kw.get("radius")), _t(acted),
                # K2 hands the loop's shields_block in as a kwarg (the value
                # acted on is compared above); every other kwarg must match.
                sorted(k for k in kw if k != "shields_block")), acted,
                kw["ship_instances"], kw["ship"]))
            return beam_contact(**kw)

        mp.setattr(ws.PhaserBank, "StopFiring", bank_spy)
        mp.setattr(ws.PhaserSystem, "StopFiring", sys_spy)
        # (K0 has no override guard, phase 6 A2: the bank spy does not make
        # it stand down; a drained bank's stop is logged natively.)
        mp.setattr(hit_feedback, "beam_contact", contact_spy)
        # Every hit as its HIT_PRESENT delivers it (native damage Task 4:
        # K2 applies a pulse in its walk, with no combat.apply_hit call --
        # and a spy ON it would be obeyed, the pulse handed back).
        spy_hits(mp, self.calls, lambda: self.tick, self.label, _t)
        # What the contacts and hits PRESENT (every hit VFX spawn and shield
        # hit, with their arguments), in the same log: a resting contact is
        # presented at the drain after the step's last record, so the
        # presentation compares per tick as a multiset (compare_calls).
        spy_presentation(mp, self.calls, lambda: self.tick, self.label,
                         contacts=False)    # contact_spy above has them

        # The queued kinds (weapon events, bank sounds): a per-tick ordered
        # list of their own (tests/helpers/effect_split.py).
        self.queued = effect_split.Queued(mp, self.label, lambda: self.tick)
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            row = (evt.GetEventType(), self.label(evt.GetSource()),
                   self.label(evt.GetDestination()), self.tick,
                   self.payload(evt))
            if self.queued.takes(evt):
                self.queued.rows.append(row)
            else:
                self.events.append(row)
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def label(self, obj):
        """A ship's, subsystem's or bank's name; anything else numbered by
        first sight (held, so its id is never reused)."""
        if obj is None:
            return None
        name = self.labels.get(id(obj))
        if name is None:
            name = self.labels[id(obj)] = "%s#%d" % (type(obj).__name__,
                                                     len(self.held))
            self.held.append(obj)
        return name

    def payload(self, evt):
        if not isinstance(evt, WeaponHitEvent):
            return None
        return (_t(evt.GetDamage()), _t(evt.GetHitPoint()),
                _t(evt.GetNormal()), _t(evt.GetRadius()),
                _t(evt.IsHullHit()), _t(evt.GetWeaponType()),
                self.label(evt.GetSubsystem()), self.label(evt.GetTarget()))

    # ── Ops ──────────────────────────────────────────────────────────────────

    def _foes(self, ship):
        side = ship.GetName().startswith("Enemy")
        return [s for s in self.ships
                if s.GetName().startswith("Enemy") != side and not s.IsDead()]

    def _enemy_of(self, rng, ship):
        foes = self._foes(ship)
        return rng.choice(foes) if foes else None

    @staticmethod
    def face(ship, target):
        a, b = ship.GetTranslate(), target.GetTranslate()
        m = TGMatrix3()
        m.MakeZRotation(math.atan2(-(b.x - a.x), b.y - a.y))
        ship.SetMatrixRotation(m)

    def _offset(self, rng):
        if rng.random() < 0.5:
            return None
        return TGPoint3(rng.uniform(-2.0, 2.0), rng.uniform(-3.0, 3.0),
                        rng.uniform(-1.0, 1.0))

    def op(self, rng, kind):
        if kind == "fire":
            g = rng.choice(self.systems)
            g.SetSingleFire(rng.choice((0, 0, 1)))
            g.StartFiring(self._enemy_of(rng, g.GetParentShip()),
                          self._offset(rng))
        elif kind == "stop":
            rng.choice(self.systems).StopFiring()
        elif kind == "off":
            rng.choice(self.systems).TurnOff()
        elif kind == "on":
            rng.choice(self.systems).TurnOn()
        elif kind == "condition":
            b = rng.choice(self.banks)
            b.SetCondition(b.GetMaxCondition() * rng.choice((0.0, 0.5, 1.0)))
        elif kind == "drain":
            b = rng.choice(self.banks)
            b.SetChargeLevel(b.GetMaxCharge() * rng.choice((0.05, 0.3, 1.0)))
        elif kind == "lock_other":
            # A ship locks a subsystem on a foe OTHER than the one its
            # phasers are held on, and keeps firing (no StartFiring: the
            # beams keep their dwell): the aim and the arc test use the
            # lock's ship (map §1.2), so a bank whose arc holds the held
            # target but not the lock fails its arc in cb.phasers (K1's pump
            # aims at the held target) and flushes its partial pulse.
            system = rng.choice(self.systems)
            ship = system.GetParentShip()
            foes = [f for f in self._foes(ship)
                    if f is not system.__dict__.get("_held_target")]
            if foes:
                ship.SetTargetSubsystem(rng.choice(_subsystems(
                    rng.choice(foes))))
        elif kind == "unlock":
            rng.choice(self.ships).SetTargetSubsystem(None)
        elif kind == "manual_on":
            target = self._enemy_of(rng, self.player)
            if target is not None:
                self.player.SetTarget(target)
                self.player.SetTargetSubsystem(rng.choice(
                    _subsystems(target)))
                self.manual_move(rng)
                self.player.GetPhaserSystem().StartFiring(
                    target, self.player.GetTargetOffsetTG())
        elif kind == "manual_move":
            if self.player.is_using_target_offset():
                self.manual_move(rng)
        elif kind == "manual_off":
            self.player.UseTargetOffsetTG(0)
        elif kind == "light":
            # A bank lit by hand (no held trigger: only cb.phasers drives it),
            # still winding up.
            b = rng.choice(self.banks)
            ship = b.GetParentSubsystem().GetParentShip()
            target = self._enemy_of(rng, ship)
            if target is not None and not ship.IsDead():
                b._target = target
                b._firing = True
                b._beam_on_countdown = ws.BEAM_ON_DELAY_S
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
        elif kind == "move":
            ship = rng.choice(self.ships)
            p = ship.GetTranslate()
            ship.SetTranslateXYZ(p.x + rng.uniform(-3.0, 3.0),
                                 p.y + rng.uniform(-3.0, 3.0),
                                 p.z + rng.uniform(-1.0, 1.0))
        elif kind == "face":
            ship = rng.choice(self.ships)
            target = self._enemy_of(rng, ship)
            if target is not None:
                self.face(ship, target)
        elif kind == "turn":
            ship = rng.choice(self.ships)
            m = TGMatrix3()
            m.MakeZRotation(rng.uniform(-3.14159, 3.14159))
            ship.SetMatrixRotation(m)
        else:
            raise AssertionError(kind)

    def manual_move(self, rng):
        self.player.set_manual_target_offset(TGPoint3(
            rng.uniform(-1.5, 1.5), rng.uniform(-4.0, 4.0),
            rng.uniform(-0.8, 0.8)))

    def volley(self, rng):
        """Once the sensors are powered (VOLLEY_AT), everyone opens fire with
        every bank that bears, so beams run long enough to pulse (and an arc
        lost mid-beam flushes a partial one)."""
        if self.tick == VOLLEY_AT:
            for g in self.systems:
                g.TurnOn()
                g.SetSingleFire(0)
                g.StartFiring(self._enemy_of(rng, g.GetParentShip()))

    def ship(self, name):
        return next(s for s in self.ships if s.GetName() == name)

    def pose(self):
        """One ship off its NIF pose for a stretch (its own banks walked
        natively through its pose table and part slots), and a foe locking
        a subsystem on it (the aim point is a posed ship's mount, native
        too). Both went to Python before posed parts went native (RUN_PYTHON
        posed_ship, ASK aim_point)."""
        ship = self.ship(POSED)
        if self.tick == POSE_FROM:
            articulation.force_part_pose(
                ship, "probe part",
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))
            poser = self.ship(POSER)
            poser.SetTarget(ship)
            poser.SetTargetSubsystem(ship.GetShields())
            poser.GetPhaserSystem().StartFiring(ship)
        elif self.tick == POSE_TO:
            articulation.force_part_pose(ship, "probe part",
                                         part_pose.IDENTITY)

    def clamp_rig(self):
        """The reversed-width rig (strip F8, map §1.3): a bank whose arc
        width is authored high-to-low (lo > hi: the Akira's Ventral Phasers
        1 and 4, stock) clamps its strip yaw in AUTHORED order, so it always
        emits at `lo`; the arc gate sorts the pair, so the bank still fires
        at a target inside the sorted arc. Each is lit at a target parked at
        the strip yaw given (inside the sorted width, outside the authored
        clamp), so a sorted clamp would emit elsewhere."""
        if not CLAMP_FROM <= self.tick < CLAMP_TO:
            return
        ship = self.ship(CLAMP_SHIP)
        if ship.IsDead():
            return
        system = ship.GetPhaserSystem()
        if not system.IsOn():
            system.TurnOn()
        if system.__dict__.get("_fire_held"):
            # A held trigger's pump would stop banks it did not light.
            system.StopFiring()
        R = ship.GetWorldRotation()
        for bank_name, target_name, yaw in CLAMP_BANKS:
            target = self.ship(target_name)
            bank = next(system.GetWeapon(i)
                        for i in range(system.GetNumWeapons())
                        if system.GetWeapon(i).GetName() == bank_name)
            assert bank._arc_width_lo > bank._arc_width_hi
            f, u = TGPoint3(*_xyz(bank._direction)), TGPoint3(*_xyz(bank._up))
            f.MultMatrixLeft(R)
            u.MultMatrixLeft(R)
            r = (f.y * u.z - f.z * u.y, f.z * u.x - f.x * u.z,
                 f.x * u.y - f.y * u.x)
            c = bank._emitter_world_position()
            d = 12.0
            target.SetTranslateXYZ(
                c.x + d * (math.cos(yaw) * f.x + math.sin(yaw) * r[0]),
                c.y + d * (math.cos(yaw) * f.y + math.sin(yaw) * r[1]),
                c.z + d * (math.cos(yaw) * f.z + math.sin(yaw) * r[2]))
            if not bank._firing and not target.IsDead():
                bank._target = target
                bank._firing = True
                bank._beam_on_countdown = ws.BEAM_ON_DELAY_S

    def arc_beat(self):
        """A scripted arc-fail flush (Review Focus 5): the player faces a foe
        and holds every bank on it; 60 ticks later (beams on, dwell banked)
        a second foe is parked astern of it and the player locks one of its
        subsystems. K1's pump aims at the held foe (in arc), cb.phasers at
        the lock's ship (astern): every forward bank fails its arc, stops,
        and delivers its partial pulse with this tick's aim."""
        if self.tick == ARC_FIRE:
            held = self.ship(ARC_HELD)
            self.face(self.player, held)
            system = self.player.GetPhaserSystem()
            system.TurnOn()
            system.SetSingleFire(0)
            system.StartFiring(held)
        if ARC_FIRE <= self.tick < ARC_LOCK_AT:
            # Until the lock, no op's lock or Manual Aim moves the aim.
            self.player.SetTargetSubsystem(None)
            self.player.UseTargetOffsetTG(0)
        elif self.tick == ARC_LOCK_AT:
            p = self.player.GetWorldLocation()
            fwd = self.player.GetWorldRotation().GetCol(1)
            lock = self.ship(ARC_LOCK)
            lock.SetTranslateXYZ(p.x - 15.0 * fwd.x, p.y - 15.0 * fwd.y,
                                 p.z - 15.0 * fwd.z)
            self.player.UseTargetOffsetTG(0)
            self.player.SetTargetSubsystem(lock.GetShields())

    def off_beat(self):
        """A phaser system off for a stretch: stopped every tick, as logged
        writes; a bank lit by hand on it (at the switch-off and again
        mid-stretch) also queues its LOOP_STOP (combat fire events Task 4;
        a SYSTEM_STOP record before)."""
        ship = self.ship(OFF_SHIP)
        system = ship.GetPhaserSystem()
        if self.tick in (OFF_FROM, OFF_FROM + 10) and not ship.IsDead():
            target = next((f for f in self._foes(ship)), None)
            bank = system.GetWeapon(0)
            if target is not None and not bank._firing:
                bank._target = target
                bank._firing = True
                bank._beam_on_countdown = ws.BEAM_ON_DELAY_S
        if self.tick == OFF_FROM:
            system.TurnOff()
        elif self.tick == OFF_TO:
            system.TurnOn()

    def rig(self):
        """The point-blank rig (strip F7, map §1.3): a bank whose target's
        hull centre IS its mount, so `target_world - center` is exactly
        (+0, +0, +0). Its ship is turned so the bank's world forward has
        three negative components: the forward projection is then -0.0, and
        only F7's explicit zero test keeps the yaw at 0 (atan2(r, -0.0) is
        +-pi, which the clamp would move to an arc edge). No lock and no
        Manual Aim on the rig ship, so the aim point is the hull centre. The
        target sits inside the firing hull: the trace starts inside it."""
        if not RIG_FROM <= self.tick < RIG_TO:
            return
        ship, target = self.ship(RIG_SHIP), self.ship(RIG_TARGET)
        if ship.IsDead() or target.IsDead():
            return
        f = (-1.0, -2.0, -0.5)
        n = math.sqrt(sum(c * c for c in f))
        f = tuple(c / n for c in f)
        u = (0.0, 0.0, 1.0)
        d = sum(a * b for a, b in zip(u, f))
        u = tuple(a - d * b for a, b in zip(u, f))
        n = math.sqrt(sum(c * c for c in u))
        u = tuple(c / n for c in u)
        r = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2],
             f[0] * u[1] - f[1] * u[0])
        m = TGMatrix3()
        m.set_from_tuple((r[0], f[0], u[0], r[1], f[1], u[1],
                          r[2], f[2], u[2]))
        ship.SetMatrixRotation(m)
        ship.SetTargetSubsystem(None)
        ship.UseTargetOffsetTG(0)
        system = ship.GetPhaserSystem()
        bank = next(system.GetWeapon(i)
                    for i in range(system.GetNumWeapons())
                    if system.GetWeapon(i).GetName() == RIG_BANK)
        p = bank._emitter_world_position()
        target.SetTranslateXYZ(p.x, p.y, p.z)
        if not system.IsOn():
            system.TurnOn()
        if not bank._firing:
            bank._target = target
            bank._firing = True
            bank._beam_on_countdown = ws.BEAM_ON_DELAY_S

    # ── Record ───────────────────────────────────────────────────────────────

    def record(self):
        row = []
        for b in self.banks:
            d = b.__dict__
            # `_firing` and `_beam_on_countdown` are what a bank's idle
            # StopFiring writes; since round trips Tasks 2-3 K1's idle stops
            # and K2's offline stops LOG them (no call), so this row is where
            # those writes are compared.
            # A missed wake (passive weapons): asleep while NOT at rest. A
            # `_firing` write, logged or not, wakes a sleeping bank
            # (WakeField). K0 runs on the native arm (this scene's spies
            # patch the stock PhaserBank / PhaserSystem StopFiring, which
            # K0's guard looks for since it logs a drained bank's stop: the
            # spy world re-takes K0's stock snapshot, see _spy) and puts no
            # weapon to sleep (spec 2026-11-02-native-weapon-state-design.md §4.3),
            # so the RAW flag differs by design; it is compared with K0
            # stood down (test_k2_matches_python_with_k0_stood_down).
            asleep = passive_state.is_asleep(b)
            row.append((self.label(b), _t(d.get("_dwell")),
                        _t(d.get("_firing")), self.label(d.get("_target")),
                        _t(d.get("_beam_on_countdown")),
                        asleep if self.raw_asleep else
                        asleep and not b._passive_at_rest()))
        for g in self.systems:
            # What an offline stop writes (round trips Task 3: logged), and
            # whether `_target_list` is a NEW object since the last record
            # (StopFiring writes a new `[]` every tick, empty or not; the
            # previous object is held, so its id is never reused).
            d = g.__dict__
            lst = d.get("_target_list")
            new = lst is not self.lists.get(id(g))
            self.lists[id(g)] = lst
            row.append((self.label(g), _t(d.get("_fire_held")),
                        self.label(d.get("_held_target")),
                        _t(d.get("_held_offset")),
                        tuple(self.label(t) for t in lst),
                        _t(d.get("_last_group_fired")), new))
        for s in self.ships:
            hull = s.GetHull()
            shields = s.GetShields()
            row.append((s.GetName(), _t(s.IsDead()),
                        None if hull is None else _t(hull.GetCondition()),
                        None if shields is None else tuple(
                            _t(shields.GetCurShields(f)) for f in range(6))))
        self.log.append(row)

    # ── Run ──────────────────────────────────────────────────────────────────

    def sync_render(self):
        """The frame's render sync: every realized ship's instance at its sim
        pose, through host_loop's own matrix (what realize pushes)."""
        for ship, iid in self.session.ship_instances.items():
            self.r.set_world_transform(
                iid, host_loop._ship_world_matrix(ship,
                                                  host_loop.BC_MODEL_SCALE))

    def run(self, ops, ticks_per_frame, ticks=TICKS, before_tick=None):
        rng = random.Random(SEED)
        instances = self.session.ship_instances
        # About one op every six ticks, at any tpf.
        p_frame = 0.06 * ticks_per_frame
        while self.tick < ticks:
            if rng.random() < p_frame:
                self.op(rng, rng.choice(ops))
            self.sync_render()
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            # After the sync: the trace sees these only next frame.
            if rng.random() < p_frame:
                self.op(rng, rng.choice(ops))
            for _ in range(ticks_per_frame):
                self.tick += 1
                self.volley(rng)
                self.pose()
                self.rig()
                self.clamp_rig()
                self.arc_beat()
                self.off_beat()
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
                self.record()
                if rng.random() < 0.04:
                    self.op(rng, rng.choice(ops))
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert not _h.combat_k2_open()
        self.counts = nc.counts()
        self.effects = effect_queue.counts()
        return self


OPS = (("fire",) * 8 + ("lock_other",) * 3 + ("light",) * 3
       + ("stop", "stop", "off", "on", "on", "condition", "drain",
          "unlock", "manual_on", "manual_move", "manual_off",
          "shields_off", "shields_on", "shields_on", "cloak", "decloak",
          "move", "face", "turn", "turn"))


def _compare(ref, nat):
    assert len(ref.log) == len(nat.log)
    for tick, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                tick, x, y)
    compare_calls(ref.calls, nat.calls)
    for i, (x, y) in enumerate(zip(ref.events, nat.events)):
        assert x == y, "event %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref.events) == len(nat.events)
    effect_split.compare(ref.queued, nat.queued)
    # The native arm's were delivered at the tick boundary; the reference
    # never opened the scope, so its K0 and K2 producers acted at once and
    # it queued only the damage kinds (native damage M2: both arms) and
    # what K1's own sessions deferred (fire control is native in both arms:
    # fire control native only, M9).
    e = nat.effects
    assert e["delivered"] > e["damage"], e
    assert e["skipped_gone"] == e["failed"] == 0, e
    assert nat.scopes.opened > 0, nat.scopes.opened
    assert ref.scopes.opened == 0, ref.scopes.opened
    assert ref.effects["skipped_gone"] == ref.effects["failed"] == 0, \
        ref.effects
    assert nat.audit == [], nat.audit
    assert ref.counts.get("k2_records", 0) == 0, ref.counts
    assert nat.counts["k2_records"] > 0, nat.counts
    assert nat.counts["k2_python_steps"] == 0, nat.counts


def _both(monkeypatch, r, ticks_per_frame, ops=OPS, ticks=TICKS,
          before_tick=None, setup=None):
    runs = []
    for env in (OFF, ON):
        with monkeypatch.context() as mp:
            scene = _Scene(mp, r, env)
            try:
                if setup is not None:
                    setup(scene, mp)
                runs.append(scene.run(ops, ticks_per_frame, ticks=ticks,
                                      before_tick=before_tick))
            finally:
                scene.close()
    ref, nat = runs
    _compare(ref, nat)
    return ref, nat


def _calls(scene, kind):
    return [c for c in scene.calls if c[0] == kind]


# ── The differential ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("ticks_per_frame", (1, 4))
def test_k2_matches_python_with_real_instances(monkeypatch, host,
                                               ticks_per_frame):
    t0 = time.perf_counter()
    ref, nat = _both(monkeypatch, host, ticks_per_frame)
    # Firing banks were stopped, and their loop stops compared.
    assert effect_split.stops(ref.queued) > 0, ref.queued.rows[:20]
    elapsed = time.perf_counter() - t0
    n = nat.tally.n
    reasons = nat.counts["k2_python_reasons"]
    print("\nk2 host differential (tpf=%d): %.1f s for 2 x %d ticks; "
          "records %r; presentation calls %d (vfx %d, shield hits %d); "
          "counts %r" % (ticks_per_frame, elapsed, TICKS, n,
                         presented(ref.calls), len(_calls(ref, "vfx")),
                         len(_calls(ref, "shield_hit")), nat.counts))
    # K0 stepped the weapons on the native arm (its guard does not hand a
    # ship back for the StopFiring spies; see record()).
    assert nat.counts["k0_steps"] > 0, nat.counts
    assert nat.counts["k0_python_reasons"]["override"] == 0, nat.counts
    # Every branch the scene is built for happened in the kernel.
    for key in ("tier:mesh", "tier:sphere", "bubble", "pulse",
                "windup_contact", "arc_fail_pulse", "lock_other_ship",
                "manual_on", "manual_off", "cloaking_target",
                "shields:True", "shields:False", "queued_contact"):
        assert n.get(key, 0) > 0, (key, n)
    # A firing bank's stop -- the walk's and an off system's -- is logged
    # writes plus its LOOP_STOP (combat fire events Task 4): no BANK_STOP or
    # SYSTEM_STOP record (both only for a stop the kernel cannot log).
    assert n.get("BANK_STOP", 0) == n.get("SYSTEM_STOP", 0) == 0, n
    assert nat.counts["k2_logged_bank_stop"] > 0, nat.counts
    assert nat.counts["k2_logged_firing_system_stop"] > 0, nat.counts
    assert nat.counts["k2_entries"]["LOOP_STOP"] > 0, nat.counts
    # Resting contacts were queued for the drain (spec 2026-11-02 §4.3):
    # the shield splashes presented by the drain itself (compared through
    # its capture), the rest returned and presented by the Python batch;
    # offline stops with every bank idle were logged writes; a CONTACT
    # record is a pulse.
    assert nat.counts["k2_present_native"] == n["native_contact"] > 0, (
        nat.counts, n)
    assert nat.counts["k2_present_python"] > 0, nat.counts
    assert nat.counts["k2_batched_contacts"] == (
        n["queued_contact"] + n["native_contact"]), (nat.counts, n)
    assert nat.counts["k2_present_python"] == n["queued_contact"], (
        nat.counts, n)
    assert nat.counts["k2_present_gone"] == 0, nat.counts
    assert nat.counts["k2_logged_system_stop"] > 0, nat.counts
    # Every damage pulse was applied in the walk (native damage Task 4): no
    # CONTACT record, none handed back.
    assert n.get("CONTACT", 0) == 0, n
    assert n["pulse"] == n["native_pulse"] == \
        nat.counts["k2_native_pulses"] > 0, (n, nat.counts)
    assert nat.counts["k2_pulse_python"] == 0, nat.counts
    # K1's round trips ran under the beams: walks started with no record and
    # lit beams sustained as logged writes (Tasks 1-2). K1's idle bank stop
    # is NOT asserted here: this scene rarely has one (measured 19 at tpf 1,
    # 0 at tpf 4); the K1 differential carries it.
    logged = nat.counts["k1_logged"]
    assert logged["walk_start"] > 0 and logged["beam_sustain"] > 0, logged
    # The presentation was compared, shield hits and hull VFX both.
    assert _calls(ref, "shield_hit") and _calls(ref, "vfx"), presented(
        ref.calls)
    # The posed ship and the lock on it: native (posed parts, Task 4; they
    # were posed_ship and ASK aim_point before).
    assert reasons["posed_ship"] == 0, reasons
    assert reasons["part_stale"] == 0, reasons
    assert nat.counts["k2_posed"]["banks"] > 0, nat.counts
    assert nat.counts["k2_posed"]["lock_aims"] > 0, nat.counts
    assert n.get("point_blank", 0) > 0, n         # the F7 rig
    assert n.get("reversed_arc", 0) > 0, n        # the F8 rig
    # ... and the effects reached the world.
    assert _calls(ref, "hit_present") and _calls(ref, "beam_contact")
    hits = [e for e in ref.events if e[0] == App.ET_WEAPON_HIT]
    assert hits and all(e[4] is not None for e in hits)


def test_k2_matches_python_with_k0_stood_down(monkeypatch, host):
    """K0 stood down (native_combat.k0_weapons answers False, as an audit
    makes it: the passive walk runs on both arms and sleeps at-rest banks),
    so the RAW asleep flag is compared: a wake one of K2's C-applied writes
    misses (a `_firing` stored without waking its sleeping bank) shows as a
    difference. The default differential runs K0 on the native arm."""
    monkeypatch.setattr(nc, "k0_weapons", lambda ships, dt: False)
    monkeypatch.setattr(_Scene, "raw_asleep", True)
    ref, nat = _both(monkeypatch, host, 1)
    assert nat.counts["k0_steps"] == 0, nat.counts
    banks = [r[5] for rows in ref.log for r in rows
             if len(r) == 6 and isinstance(r[5], bool)]
    assert True in banks and False in banks, "no bank slept"


def test_no_host_bindings_matches_python(monkeypatch, host):
    """host_io._h None (Ruling C2, item 3) with REAL instances: Python's
    ray_trace_mesh then traces nothing, so every beam on a realized hull
    takes the sphere tier, though the kernel's installed hooks could still
    reach g_world. The driver tells the kernel (ctx "trace" False) and it
    must land on the same sphere points."""
    from engine import host_io

    def setup(scene, mp):
        mp.setattr(host_io, "_h", None)

    ref, nat = _both(monkeypatch, host, 4, ticks=300, setup=setup)
    n = nat.tally.n
    assert n.get("tier:sphere", 0) > 0 and n.get("tier:mesh", 0) == 0, n


# ── A handler changes the target in the middle of a step ────────────────────

KILL_TARGET = "Enemy-3"
CHANGE_AT, KILL_AT = 90, 170
_HANDLER = {}


def WeaponHitHandler(_dest, evt):
    """An SDK-style broadcast handler on ET_WEAPON_HIT. On the first phaser
    pulse on the target from tick CHANGE_AT it drops the target's shields and
    shoves it sideways; on the first from tick KILL_AT it kills it (the death
    sequence, splash included, then SetDead). Both run at that tick's
    boundary, where the pulse's ET_WEAPON_HIT is delivered (native damage
    M2), so every bank from the next step on must see the changed target."""
    scene = _HANDLER.get("scene")
    if scene is None or evt.GetWeaponType() != WeaponHitEvent.PHASER:
        return
    target = evt.GetTarget()
    if target is None or target.GetName() != KILL_TARGET:
        return
    if scene.tick >= KILL_AT and "killed" not in _HANDLER:
        _HANDLER["killed"] = scene.tick
        scene.killed_at = scene.tick
        scene.calls.append(("handler_kill", scene.tick))
        from engine.appc import ship_death
        ship_death.begin(target, evt.GetSource())
        target.SetDead()
    elif scene.tick >= CHANGE_AT and "changed" not in _HANDLER:
        _HANDLER["changed"] = scene.tick
        scene.calls.append(("handler_change", scene.tick))
        target.GetShields().TurnOff()
        p = target.GetTranslate()
        target.SetTranslateXYZ(p.x + 2.0, p.y - 1.5, p.z + 0.5)


def test_handler_kills_target_mid_volley(monkeypatch, host):
    """Every friendly beams the same Galor. A real ET_WEAPON_HIT handler
    (one of an apply_hit's own effects) first drops its shields and moves
    it, later kills it, each at a tick's boundary (native damage M2: before,
    in the middle of a step): the banks of the next step must see it
    shieldless and moved, then dead (a firing bank stops; a banked flush is
    dropped), exactly as the Python step does."""

    on_dead = {}

    def before_tick(scene):
        if scene.killed_at is not None and scene.tick - scene.killed_at in (
                1, 2):
            # Banks still firing on the dead target as each step begins.
            on_dead[scene.native, scene.tick - scene.killed_at] = sum(
                1 for b in scene.banks
                if b.__dict__.get("_firing")
                and b.__dict__.get("_target") is scene.ship(KILL_TARGET))
        if scene.tick == VOLLEY_AT + 1:
            target = scene.ship(KILL_TARGET)
            for g in scene.systems:
                ship = g.GetParentShip()
                if ship.GetName().startswith("Enemy"):
                    continue
                scene.face(ship, target)
                ship.SetTargetSubsystem(None)
                g.TurnOn()
                g.SetSingleFire(0)
                g.StartFiring(target)

    name = __name__ + ".WeaponHitHandler"
    ops = ("move", "drain", "shields_on", "condition")
    stats = []

    def setup(scene, mp):
        _HANDLER.clear()
        _HANDLER["scene"] = scene
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_WEAPON_HIT, scene.player, name)

        def remove():
            App.g_kEventManager.RemoveBroadcastHandler(
                App.ET_WEAPON_HIT, scene.player, name)
            stats.append(dict(_HANDLER, scene=None))
            _HANDLER.clear()
        mp.setattr(scene, "close", lambda _c=scene.close: (remove(), _c()))

    ref, nat = _both(monkeypatch, host, 4, ops=ops, ticks=KILL_AT + 60,
                     before_tick=before_tick, setup=setup)
    py, native = stats
    assert native == py and "changed" in py and "killed" in py, stats
    # Work followed each handler in the same step.
    for kind, key in (("handler_change", "changed"),
                      ("handler_kill", "killed")):
        i = next(i for i, c in enumerate(ref.calls) if c[0] == kind)
        assert ref.calls[i + 1][1] == py[key], ref.calls[i:i + 3]
    # The kill lands at the boundary (native damage M2, M5), so no bank
    # meets a target dying mid-walk any more: the banks still on it begin
    # the next step firing and that step stops them, in both arms.
    for native in (False, True):
        assert on_dead[native, 1] > 0 and on_dead[native, 2] == 0, on_dead
    assert ref.ship(KILL_TARGET).IsDead()
