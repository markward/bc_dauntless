"""Shared pieces of the K3/K4 differentials (native combat phase 3, Task 6;
spec docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md §7):
tests/integration/test_native_k3_differential.py (headless) and
tests/host/test_native_k3_differential.py (real instances).

A differential arm builds a scene, then wires a ``Recorder`` into it: the
recorder labels every ship and torpedo by first sight (the two arms create
them in the same order), spies on the calls a torpedo step makes, and
records after every tick everything Task 5's dispatch test compares
(tests/unit/test_native_k3_dispatch.py) -- every torpedo in flight (or that
left flight this tick): position, velocity, age, guidance fields, mount key,
bubble entry (floats by .hex()); update_all's hits; every apply_hit; the
incoming-torpedo table's velocity writes (a per-tick multiset) and its
incoming_ids answer -- plus what the phase adds: every ship's death, hull and
shield faces, ``damage_eligibility._current`` (see eligibility_view: ids
differ between the arms, so ties are named by rank) together with whether it
equals select_eligible on the same objects, and every ship pair's can_detect
lock-break latch; and the whole ordered event log with each weapon hit's
payload.

In the native arm a ``K3Tally`` wraps ``combat_k3_next``: every record the
kernel returns is classified BEFORE Python acts on it (the Python attributes
still hold the pre-tick values then), so the branch counts say what the
KERNEL decided, not what the scene was built to make likely.

Scene helpers both files share: ``seed_every_rng``, ``subsystems``, ``face``,
``nebula_around``.
A differential arm's audio and crew throttles are isolated by
tests/helpers/fight_audio.isolate_fight_audio.
"""
import math
import random

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import combat
from engine.appc import damage_eligibility
from engine.appc import native_combat as nc
from engine.appc import projectiles
from engine.appc import sensor_detection as sd
from engine.appc import torpedo_scan
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.projectiles import Torpedo
from engine.systems import frames

_ZERO = (0.0, 0.0, 0.0)


def seed_every_rng(seed):
    """Every RNG a fight draws on (the K1 differential's list): the module
    `random`, the SDK's App.g_kSystemWrapper.GetRandomNumber and the engine's
    two process-lifetime streams (avoidance, random unit vectors)."""
    from engine.appc import collision_avoidance
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()


def subsystems(ship):
    """The ship's subsystems a shot may aim at (power, sensors, impulse,
    shields), those it has."""
    return [s for s in (ship.GetPowerSubsystem(), ship.GetSensorSubsystem(),
                        ship.GetImpulseEngineSubsystem(), ship.GetShields())
            if s is not None]


def nebula_around(ship, name, radius):
    """A dense MetaNebula sphere of `radius` centred on `ship`, added to its
    set as `name`: concealment ~1 at the ship (gain 1, floor -1 saturate the
    fbm), so every can_detect AT it breaks its lock (the latch) and guided
    shots at it fly on their frozen last-seen point. No creation damage."""
    p = ship.GetWorldLocation()
    n = App.MetaNebula_Create(0.5, 0.5, 0.7, 145.0, 1.0, "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(p.x, p.y, p.z, radius)
    n.SetFbmDials(0.02, 1.0, -1.0)
    ship.GetContainingSet().AddObjectToSet(n, name)
    return n


def face(ship, target):
    """Turn `ship` (about Z) to face `target`."""
    a, b = ship.GetTranslate(), target.GetTranslate()
    m = TGMatrix3()
    m.MakeZRotation(math.atan2(-(b.x - a.x), b.y - a.y))
    ship.SetMatrixRotation(m)


def hx(v):
    """A value with its type; floats by .hex(), points by their hexes."""
    if v is None:
        return None
    if isinstance(v, float):
        return ("float", v.hex())
    if isinstance(v, TGPoint3):
        return ("TGPoint3",) + tuple(float(c).hex() for c in (v.x, v.y, v.z))
    if isinstance(v, tuple) and len(v) == 3 and all(
            isinstance(c, float) for c in v):
        return ("seq",) + tuple(c.hex() for c in v)
    return (type(v).__name__, v)


def fire(src, at, vel, target=None, offset=None, ttl=None, guidance=None,
         accel=None, damage=20.0):
    """A torpedo launched by hand (as test_native_k3_dispatch's World.fire):
    from `src`, at `at` in its set, flying `vel`, homing on `target` (at the
    target-local `offset`, if given), with the SDK setters for TTL, guidance
    window and turn rate. Registered, so it joins the source's set."""
    t = Torpedo()
    t._source_ship = src
    t.SetTranslateXYZ(*at)
    t._velocity = TGPoint3(*vel)
    t.SetDamage(damage)
    if ttl is not None:
        t.SetLifetime(ttl)
    if guidance is not None:
        t.SetGuidanceLifetime(guidance)
    if accel is not None:
        t.SetMaxAngularAccel(accel)
    if target is not None:
        t._target_ship = target
        if offset is not None:
            t.SetTargetOffset(offset)
    projectiles.register(t)
    return t


def aim_velocity(src_xyz, dst_xyz, speed, spread=(0.0, 0.0, 0.0)):
    """`speed` along src -> dst + spread."""
    d = [dst_xyz[i] + spread[i] - src_xyz[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d)) or 1.0
    return tuple(c / n * speed for c in d)


def xyz(p):
    return (p.x, p.y, p.z)


def _k4_scores(player, ships):
    """{id(ship): score} for every listed ship but the player: select_eligible's
    own arithmetic (read-only), or None without a player."""
    de = damage_eligibility
    if player is None:
        return None
    max_r = max((de._radius(s) for s in ships), default=0.0) or 1.0
    out = {}
    for s in ships:
        if id(s) == id(player):
            continue
        prox = 1.0 / (1.0 + frames.system_distance(s, player))
        out[id(s)] = (de.PROX_WEIGHT * prox
                      + de.SIZE_WEIGHT * (de._radius(s) / max_r))
    return out


def eligibility_view(player, ships, eligible, label):
    """``damage_eligibility._current`` in a form two arms can compare, and
    what it shows about the cut. Ids differ between the arms, so a ship that
    ties another's score exactly is named by its tie (the score's hex) and its
    RANK in id order inside it: both arms then name the ship each picked by
    the id() tie-break alike, and a kernel that broke the tie another way
    names another rank. Returns (sorted names, tie_at_cut, cross_frame):
    whether the cut fell inside an exact tie (only the tie-break decides who
    is in) and how many listed ships score no proximity (another frame)."""
    de = damage_eligibility
    ships = list(ships)
    scores = _k4_scores(player, ships)
    if scores is None:
        return sorted(label(s) for s in ships if id(s) in eligible), False, 0
    groups = {}
    for s in ships:
        if id(s) in scores:
            groups.setdefault(scores[id(s)], []).append(s)
    names = {}
    for score, members in groups.items():
        if len(members) == 1:
            names[id(members[0])] = label(members[0])
            continue
        for rank, s in enumerate(sorted(members, key=id)):
            names[id(s)] = "tie%s#%d" % (score.hex(), rank)
    names[id(player)] = label(player)
    view = sorted(names.get(i, "?") for i in eligible)
    max_count = de.select_eligible.__kwdefaults__["max_count"]
    ordered = sorted(scores.values(), reverse=True)
    cut = max_count - 1         # the player's slot first
    tie = 0 < cut < len(ordered) and ordered[cut - 1] == ordered[cut]
    cross = sum(1 for s in ships if id(s) in scores
                and frames.system_distance(s, player) == math.inf)
    return view, tie, cross


class Recorder:
    """The per-tick record, the call log and the event log of one arm (see
    the module docstring). `ships` are labelled by name; anything else by
    first sight. `observer` answers incoming_ids every tick."""

    def __init__(self, mp, ships, observer, ship_instances=None,
                 native=False):
        self.native = native
        self.ships = list(ships)
        self.observer = observer
        self.ship_instances = ship_instances
        self.labels = {id(s): s.GetName() for s in self.ships}
        self.held = []
        self.torps = []          # every torpedo seen, first-sight order
        self.torp_ids = set()
        self.live = set()        # id()s in flight after the last record
        self.tick = 0
        self.log = []
        self.calls = []
        self.events = []
        self.scan_writes = {}
        self.k4 = {"tie_at_cut": 0, "cross_frame": 0}
        self.eligible = None
        self.tally = None
        # Every True can_detect lock-break latch recorded (pair x tick): the
        # "latched" row compares something only while this grows.
        self.latched = 0
        self._spy(mp)

    # ── Labels ───────────────────────────────────────────────────────────────

    def label(self, obj):
        if obj is None:
            return None
        name = self.labels.get(id(obj))
        if name is None:
            name = self.labels[id(obj)] = "%s#%d" % (type(obj).__name__,
                                                     len(self.held))
            self.held.append(obj)
        if isinstance(obj, Torpedo) and id(obj) not in self.torp_ids:
            self.torp_ids.add(id(obj))
            self.torps.append(obj)
        return name

    def payload(self, evt):
        if not isinstance(evt, WeaponHitEvent):
            return None
        return (hx(evt.GetDamage()), hx(evt.GetHitPoint()),
                hx(evt.GetNormal()), hx(evt.GetRadius()),
                hx(evt.IsHullHit()), hx(evt.GetWeaponType()),
                self.label(evt.GetSubsystem()), self.label(evt.GetTarget()))

    # ── Spies ────────────────────────────────────────────────────────────────

    def _spy(self, mp):
        apply_hit = combat.apply_hit
        update_all = projectiles.update_all

        def hit_spy(target, damage, point, **kw):
            sp = kw.get("shield_point")
            self.calls.append((
                "apply_hit", self.tick, self.label(target), hx(damage),
                hx(point), self.label(kw.get("source")),
                hx(kw.get("normal")), hx(kw.get("weapon_type")),
                self.label(kw.get("hardpoint_weapon")), hx(sp),
                sp is not None and sp is point,
                kw.get("ship_instances") is self.ship_instances,
                hx(kw.get("damage_hull")), sorted(kw)))
            return apply_hit(target, damage, point, **kw)

        def update_spy(dt, ships, *, ship_instances=None):
            hits = update_all(dt, ships, ship_instances=ship_instances)
            for t, ship, point, normal in hits:
                self.calls.append((
                    "hit", self.tick, self.label(t), self.label(ship),
                    hx(point), hx(normal), hx(t._bubble_entry),
                    point is t._bubble_entry))
            return hits

        mp.setattr(combat, "apply_hit", hit_spy)
        mp.setattr(projectiles, "update_all", update_spy)

        update = damage_eligibility.update

        def eligibility_spy(ships, _orig=update):
            _orig(ships)
            try:
                game = App.Game_GetCurrentGame()
                player = game.GetPlayer() if game is not None else None
            except Exception:
                player = None
            current = damage_eligibility._current
            view, tie, cross = eligibility_view(player, ships, current,
                                                self.label)
            # The reference on the SAME objects (so the same ids): what
            # select_eligible makes of this step's list.
            same = current == damage_eligibility.select_eligible(player,
                                                                  ships)
            self.eligible = (view, same)
            if tie:
                self.k4["tie_at_cut"] += 1
            if cross:
                self.k4["cross_frame"] += 1

        mp.setattr(damage_eligibility, "update", eligibility_spy)

        scan_cls = type(torpedo_scan.get_scan())
        set_velocity = scan_cls.set_velocity
        by_objid = {}
        self._by_objid = by_objid

        def set_velocity_spy(scan, tid, vx, vy, vz, _orig=set_velocity):
            label = by_objid.get(tid, tid)
            self.scan_writes.setdefault(self.tick, []).append(
                (label, hx((float(vx), float(vy), float(vz)))))
            return _orig(scan, tid, vx, vy, vz)

        mp.setattr(scan_cls, "set_velocity", set_velocity_spy)

        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            src = evt.GetSource()
            row = (evt.GetEventType(), self.label(src),
                   self.label(evt.GetDestination()), self.tick,
                   self.payload(evt))
            if isinstance(src, Torpedo):
                by_objid[src.GetObjID()] = self.label(src)
            self.events.append(row)
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    # ── Record ───────────────────────────────────────────────────────────────

    def bound(self, ship):
        """The ship's broadphase bound: Python's bubble_bound_radius, or in
        the native arm the KERNEL's (the value its ship cache holds; the
        broadphase is conservative, so a bound one ulp off would never show
        in a hit -- it is compared here instead)."""
        if not self.native:
            return hx(combat.bubble_bound_radius(ship))
        try:
            return hx(_h.combat_test_bubble_bound_radius(nc.slot(ship)))
        except ValueError:
            return "ask"

    def _torp_row(self, t):
        d = t.__dict__
        key = d.get("_mount_key")
        if key is not None:
            key = (self.label(key[0]), hx(key[1]), hx(key[2]), hx(key[3]),
                   self.label(key[4]))
        return (self.label(t), t in projectiles._active,
                hx(t.GetTranslate()), hx(t._vel), hx(d.get("_age")),
                hx(d.get("_last_seen_target_pos")),
                hx(d.get("_last_target_vel")), key, hx(t._bubble_entry),
                self.label(d.get("_target_ship")))

    def record(self):
        for t in projectiles._active:
            self.label(t)
            self._by_objid.setdefault(t.GetObjID(), self.label(t))
        active = {id(t) for t in projectiles._active}
        row = [self._torp_row(t) for t in self.torps
               if id(t) in active or id(t) in self.live]
        self.live = active
        for s in self.ships:
            hull = s.GetHull()
            shields = s.GetShields()
            row.append((s.GetName(), hx(s.IsDead()),
                        None if hull is None else hx(
                            float(hull.GetCondition())),
                        None if shields is None else tuple(
                            hx(float(shields.GetCurShields(f)))
                            for f in range(6))))
        row.append(("eligible",) + self.eligible)
        row.append(("bounds", [self.bound(s) for s in self.ships]))
        latched = [sd._latched(a, b) for a in self.ships
                   for b in self.ships if a is not b]
        self.latched += sum(1 for v in latched if v)
        row.append(("latched", latched))
        row.append(("scan_writes", sorted(self.scan_writes.get(self.tick,
                                                               []))))
        if type(projectiles._active) is projectiles._ActiveList:
            row.append(("incoming", [
                self._by_objid.get(i, i) for i in projectiles.incoming_ids(
                    self.observer, 3600.0, None, 0)]))
        self.log.append(row)


class K3Tally:
    """Wraps combat_k3_next in the native arm: classifies every record the
    kernel returns before Python acts on it.

    Read straight off the kernel's records: "ask:<query>" (every ASK),
    "guided_by_ask" (a write for a torpedo this step's ASK guide named),
    "ttl" and "ttl_and_hit_same_tick" (DONE's expired list less its hits),
    "hit", "tier:<tier>", "normal", "bubble", "hit_is_bubble" and
    "same_ship_hits" (DONE's hit tuples), "steer_point:cross_region" (the
    ASK's own offset argument).

    Classified from PYTHON-side state (the torpedo's pre-tick attributes,
    frames.offset_between, the target's IsDead and pose) together with the
    write record's last-seen / velocity: "unguided", "window_end",
    "ballistic_frame", "ballistic_dead", "source_other_frame(_unseen)",
    "guided_visible", "cross_region_homing", "guided_invisible",
    "guided_no_turn" and "cross_region_hit" (the hit ship's and torpedo's
    frames).

    Read off the KERNEL's own counters (combat_k3_counts, posed parts Task
    4): "steer_point:<why>" for every steer_point ASK, by the reason the
    kernel counted for it (k3_steer_reasons: "steer_point:unattributed" is
    a mount attribution, "steer_point:part_stale" a stale slot, ...);
    "steer_point:mount" is the attribution ASKs (unattributed); and
    "steer_point:posed" the steer points the kernel decided NATIVELY at a
    posed target's mount or Manual Aim pick (k3_posed_steers)."""

    def __init__(self, orig):
        self.orig = orig
        self.n = {}
        self.asked_guide = set()
        self.ask = _h.combat_k3_kinds()["ASK"]
        c = _h.combat_k3_counts()
        self.steer_why = dict(c["k3_steer_reasons"])
        self.posed_steers = c["k3_posed_steers"]

    def bump(self, key, by=1):
        self.n[key] = self.n.get(key, 0) + by

    def __call__(self):
        rec = self.orig()
        if rec[0] == self.ask:
            self.on_ask(rec)
        else:
            self.on_done(rec)
        return rec

    def on_ask(self, rec):
        query, args = rec[1], rec[2:]
        self.bump("ask:" + query)
        if query == "guide":
            self.asked_guide.add(args[0])
        elif query == "steer_point":
            why = _h.combat_k3_counts()["k3_steer_reasons"]
            for k, n in why.items():
                if n != self.steer_why.get(k, 0):
                    self.bump("steer_point:" + k, n - self.steer_why.get(k, 0))
                    if k == "unattributed":
                        self.bump("steer_point:mount")
            self.steer_why = dict(why)
            if args[2] is not None and tuple(args[2]) != _ZERO:
                self.bump("steer_point:cross_region")

    def on_done(self, rec):
        _kind, writes, expired, hits = rec
        posed = _h.combat_k3_counts()["k3_posed_steers"]
        self.bump("steer_point:posed", posed - self.posed_steers)
        self.posed_steers = posed
        rows = nc._k3_rows
        for h, _age, seen, _tvel, vel in writes:
            t = rows[h]
            self.classify(t, h, seen, vel)
        hit_torps = {th for th, *_rest in hits}
        ttl = [h for h in expired if h not in hit_torps]
        self.bump("ttl", len(ttl))
        if ttl and hit_torps:
            self.bump("ttl_and_hit_same_tick")
        ships = {}
        for th, sh, _p, tier, normal, bubble, is_bubble in hits:
            self.bump("hit")
            self.bump("tier:" + tier)
            if normal is not None:
                self.bump("normal")
            if bubble is not None:
                self.bump("bubble")
            if is_bubble:
                self.bump("hit_is_bubble")
            ships[sh] = ships.get(sh, 0) + 1
            t, ship = rows[th], nc._registry.get(sh)
            off = frames.offset_between(frames.containing_set(ship),
                                        frames.containing_set(t))
            if off is not None and off != _ZERO:
                self.bump("cross_region_hit")
        for n in ships.values():
            if n > 1:
                self.bump("same_ship_hits")
        self.asked_guide.clear()

    def classify(self, t, h, seen, vel):
        d = t.__dict__
        target = d.get("_target_ship")
        if target is None:
            self.bump("unguided")
            return
        if not d["_age"] < d["_guidance_lifetime"]:
            self.bump("window_end")
            return
        if h in self.asked_guide:
            self.bump("guided_by_ask")
            return
        tset = frames.containing_set(t)
        gset = frames.containing_set(target)
        off = frames.offset_between(tset, gset)
        if off is None:
            self.bump("ballistic_frame")
            return
        if target.IsDead():
            self.bump("ballistic_dead")
            return
        src = t._source_ship
        if src is not None and frames.offset_between(
                frames.containing_set(src), gset) is None:
            # _target_visible's `off is None`: can_detect still asks.
            self.bump("source_other_frame")
            if seen is None:
                self.bump("source_other_frame_unseen")
        if seen is not None:
            self.bump("guided_visible")
            if off != _ZERO:
                self.bump("cross_region_homing")
        elif vel is not None:
            self.bump("guided_invisible")
        else:
            self.bump("guided_no_turn")


def compare(ref, nat):
    """Every per-tick row, call and event equal (floats by .hex())."""
    assert len(ref.log) == len(nat.log)
    for tick, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b), "tick %d: %d rows vs %d" % (tick, len(a),
                                                            len(b))
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                tick, x, y)
    for i, (x, y) in enumerate(zip(ref.calls, nat.calls)):
        assert x == y, "call %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref.calls) == len(nat.calls)
    for i, (x, y) in enumerate(zip(ref.events, nat.events)):
        assert x == y, "event %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref.events) == len(nat.events)


#: Every reason the kernel can give for an ASK guide (k3_projectiles.cc
#: Walker::guide, projectile_geometry.cc guide_torpedo's need_guide).
GUIDE_REASONS = frozenset((
    "target_not_in_scan", "source_not_in_scan",
    "unrepresentable torpedo field", "_target_ship", "torpedo or target set",
    "target has no real IsDead", "torpedo transform", "_source_ship",
    "source or target frame", "source or target set", "can_detect"))


def check_guide_asks(counts, tally, expected):
    """The guide ASKs the native arm made, pinned: recorded, every one with a
    reason (their sum IS the ASK count), the tally saw the same number of
    records, and no reason outside `expected` (a subset of GUIDE_REASONS:
    what this scene is built to cause). Returns the reasons that occurred."""
    asks = counts["k3_asks"]["guide"]
    reasons = counts["k3_guide_reasons"]
    assert set(reasons) <= GUIDE_REASONS, reasons
    assert sum(reasons.values()) == asks, (asks, reasons)
    assert tally.n.get("ask:guide", 0) == asks, (asks, tally.n)
    seen = {k for k, v in reasons.items() if v}
    assert seen <= set(expected), (seen, expected)
    return seen
