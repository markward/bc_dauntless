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
bubble entry (floats by .hex()); the K3 step's hits; every hit as its
HIT_PRESENT delivers it (spy_hits), and in
the same log every beam contact, hit VFX spawn and shield hit (the
presentation: spy_presentation, round trips Task 5; compared per tick as a
multiset, compare_calls); the
incoming-torpedo table's velocity writes (a per-tick multiset) and its
incoming_ids answer -- plus what the phase adds: every ship's death, hull and
shield faces, ``damage_eligibility._current`` (see eligibility_view: ids
differ between the arms, so ties are named by rank) together with whether it
equals select_eligible on the same objects, and every ship pair's can_detect
lock-break latch; and the whole ordered event log with each weapon hit's
payload -- less the queued kinds (weapon events, bank sounds), which go to a
per-tick ordered list of their own (``Recorder.queued``,
tests/helpers/effect_split.py): with native on, the tick's effect scope
delivers them at the boundary.

In the native arm a ``K3Tally`` wraps ``combat_k3_next``: every record the
kernel returns is classified BEFORE Python acts on it (the Python attributes
still hold the pre-tick values then), so the branch counts say what the
KERNEL decided, not what the scene was built to make likely.

Scene helpers both files share: ``seed_every_rng``, ``subsystems``, ``face``,
``nebula_around``.

Posed parts (Task 5) reuses the record for its own differentials
(tests/helpers/posed_fight.py): ``Recorder(extra=...)`` appends a scene's
own rows each tick, ``weapon_rows`` is the K1 differential's fire-control
record, and ``posed_fallbacks`` / ``posed_branches`` read the kernels'
posed counters.
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
from engine.appc import weapon_subsystems as ws
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.projectiles import Torpedo
from engine.appc.sets import SetClass
from engine.appc.subsystems import ShipSubsystem
from engine.systems import frames
from tests.helpers import effect_split

_ZERO = (0.0, 0.0, 0.0)


def seed_every_rng(seed):
    """Every RNG a fight draws on (the K1 differential's list): the module
    `random`, the SDK's App.g_kSystemWrapper.GetRandomNumber, the engine's
    two process-lifetime streams (avoidance, random unit vectors) and the
    presentation generator (engine/appc/presentation_rng.py)."""
    from engine.appc import collision_avoidance
    from engine.appc import presentation_rng
    from engine.appc.math import reset_random_unit_vector_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    collision_avoidance._rng.seed(collision_avoidance._AVOID_RNG_SEED)
    reset_random_unit_vector_rng()
    presentation_rng.reset()


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


class ShieldedContact(tuple):
    """A spy's beam_contact row for a contact that acted on shields up on a
    target with an instance id: its whole presentation is the shield_hit it
    makes, and the K2 drain makes most of those in C++ with no beam_contact
    call at all (spec 2026-11-02 §4.4). compare_calls leaves these rows out
    and compares the shield hits -- the shield_hit spy's rows and the
    drain's captured ones (capture_native_shield_hits) alike. Still a tuple:
    a test reading the log sees it as any other row."""

    __slots__ = ()


def contact_row(row, acted, ship_instances, ship):
    """A beam_contact spy's `row`, marked ShieldedContact when `acted` and
    the target has an instance id -- exactly when a shield_hit row stands
    for it (beam_contact pushes a splash only then). A shielded contact on a
    target with none presents nothing, the drain never takes it natively
    (no iid), so both arms call beam_contact and its row stays compared."""
    if acted and ship_instances is not None \
            and ship_instances.get(ship) is not None:
        return ShieldedContact(row)
    return row


#: The capture list the outermost capture_native_shield_hits wrapper
#: installed for the drain call in progress (None: no call).
_capturing = [None]


def capture_native_shield_hits(mp, on_item):
    """Wrap combat_k2_drain so every shield splash the drain presents
    natively is captured (combat_present_capture, on only for the call) and
    handed to `on_item(item)`, in queue order, before the drain returns:
    item = (bank, target, iid, view_xyz, relative_xyz | None, rgba,
    intensity, radius), view_xyz being exactly the point host_io.shield_hit
    would have been given. Wrappers nest: an inner one shares the capture
    the outer one installed and reports what its own call appended."""
    real = _h.combat_k2_drain

    def drain():
        cap = _capturing[0]
        if cap is not None:
            first = len(cap)
            entries = real()
            for item in cap[first:]:
                on_item(item)
            return entries
        cap = _capturing[0] = []
        _h.combat_present_capture(cap)
        try:
            entries = real()
        finally:
            _h.combat_present_capture(None)
            _capturing[0] = None
        for item in cap:
            on_item(item)
        return entries
    mp.setattr(_h, "combat_k2_drain", drain)


def spy_hits(mp, calls, tick, label, hexer=None, after=None):
    """Every hit, as both arms make it (native damage Task 4: K2 applies a
    damage pulse in its walk and K3 its hits after the step's expiries, so
    combat.apply_hit is no longer called for them natively -- and a spy ON
    it would be obeyed: the kernels hand a patched apply_hit's hits back).

    - "hit_present" rows: each HIT_PRESENT as it is delivered
      (hit_feedback.present, at the tick boundary in both arms), every input
      the hit gave its presentation: (tick, ship, damage, point, source,
      normal, weapon_type, radius, shield_point, shield_point IS point,
      absorbed shields / subsystem / hull, the primary subsystem, its
      transition, persist_decal, allow_structural_wear, ship_instances given,
      tangent, decal radius and dent, single_impact, shield radius); `after`
      hooks run after each (a stand-in for a hit's handler, now at the
      boundary).
    - "hit" rows are the K3 hits update_all decided, logged by the caller's
      update_all spy (Python's step returns them) and by spy_k3_hits (the
      native step applies them itself)."""
    from engine.appc import hit_feedback
    hexer = hexer or hx
    present = hit_feedback.present

    def present_spy(**kw):
        sp, point = kw.get("shield_point"), kw.get("point")
        calls.append((
            "hit_present", tick(), label(kw["ship"]), hexer(kw["damage"]),
            hexer(point), label(kw.get("source")), hexer(kw.get("normal")),
            hexer(kw.get("weapon_type")), hexer(kw.get("radius")),
            hexer(sp), sp is not None and sp is point,
            hexer(kw.get("absorbed_shields")),
            hexer(kw.get("absorbed_subsystem")),
            hexer(kw.get("absorbed_hull")), label(kw.get("subsystem")),
            repr(kw.get("sub_transition")), kw.get("persist_decal"),
            kw.get("allow_structural_wear"),
            kw.get("ship_instances") is not None, hexer(kw.get("tangent")),
            hexer(kw.get("decal_radius")), hexer(kw.get("decal_dent")),
            kw.get("single_impact"), hexer(kw.get("shield_radius")),
            sorted(kw)))
        result = present(**kw)
        for hook in list(after or ()):
            hook()
        return result

    mp.setattr(hit_feedback, "present", present_spy)


def spy_k3_hits(mp, row):
    """The native K3 step's hits as _k3_walk hands them to _k3_apply_hits
    (after the expiries), each through `row(torpedo, ship, point, normal)`
    -- the row an update_all spy logs for Python's returned hits."""
    apply = nc._k3_apply_hits

    def apply_spy(hits, ship_instances, walk, _orig=apply):
        for t, ship, point, normal in hits:
            row(t, ship, point, normal)
        return _orig(hits, ship_instances, walk)

    mp.setattr(nc, "_k3_apply_hits", apply_spy)


def spy_presentation(mp, calls, tick, label, contacts=True):
    """Every hit VFX spawn and every shield hit, with their arguments, into
    the compared call log `calls`, in the order they happen (`tick()` the
    arm's tick, `label` its labeller) -- the shield hits the K2 drain makes
    natively too, from its capture, as the rows the shield_hit spy would
    have logged; with `contacts`, every hit_feedback.beam_contact too (its
    arguments, and the shields_block it acted on: headless, a contact on a
    shielded ship presents nothing, so the contact itself is what shows it;
    a shielded one on a target with an instance id is a ShieldedContact,
    left out of the compare for the shield hit that stands for it). What a
    beam contact or a hit PRESENTS: a K2 resting contact is presented at the
    drain after the step's last record (spec 2026-11-02 §4.3-4.4), so
    presentation is compared per tick as a multiset (compare_calls; ruling
    Q1), while the game-state calls logged into the same list keep their
    order. The instance id is compared only as present or not: two loads
    realize alike but number their instances independently."""
    from engine import host_io
    from engine.appc import hit_feedback, hit_vfx
    spawn, shield_hit = hit_vfx.spawn, host_io.shield_hit
    beam_contact = hit_feedback.beam_contact

    def contact_spy(**kw):
        if "shields_block" in kw:
            acted = kw["shields_block"]
        else:
            acted = bool(combat.shields_block(kw["ship"]))
        calls.append(contact_row(
            ("beam_contact", tick(), label(kw["ship"]), label(kw["source"]),
             hx(kw["point"]), hx(kw["normal"]), hx(kw["shield_point"]),
             hx(kw["tick_damage"]), hx(kw.get("weapon_type")),
             hx(kw.get("radius")), hx(bool(acted)),
             sorted(k for k in kw if k != "shields_block")), acted,
            kw["ship_instances"], kw["ship"]))
        return beam_contact(**kw)

    def spawn_spy(position, *args, **kw):
        normal = args[0] if args else kw.get("normal")
        severity = args[1] if len(args) > 1 else kw.get("severity")
        body = kw.get("body_point")
        calls.append(("vfx", tick(), hx(position), hx(normal),
                      repr(severity), kw.get("instance_id") is not None,
                      None if body is None else hx(tuple(map(float, body))),
                      kw.get("weapon_kind"), kw.get("spark_count"),
                      label(kw.get("pSet")), sorted(kw)))
        return spawn(position, *args, **kw)

    def shield_spy(iid, point, *args, **kw):
        calls.append(("shield_hit", tick(), iid is not None,
                      hx(tuple(map(float, point))),
                      tuple(hx(float(a)) if isinstance(a, (int, float))
                            else repr(a) for a in args),
                      sorted(kw)))
        return shield_hit(iid, point, *args, **kw)

    def native_hit(item):
        # The row shield_spy logs for beam_contact's positional call
        # shield_hit(iid, point, rgba, intensity, radius).
        _b, _t, iid, view, _rel, rgba, intensity, radius = item
        calls.append(("shield_hit", tick(), iid is not None,
                      hx(tuple(map(float, view))),
                      (repr(tuple(rgba)), hx(float(intensity)),
                       hx(float(radius))), []))

    mp.setattr(hit_vfx, "spawn", spawn_spy)
    mp.setattr(host_io, "shield_hit", shield_spy)
    if _h is not None:
        capture_native_shield_hits(mp, native_hit)
    if contacts:
        mp.setattr(hit_feedback, "beam_contact", contact_spy)


#: The presentation calls spy_presentation logs: no order inside a tick
#: (ruling Q1, spec 2026-11-02 §5).
PRESENTATION = ("beam_contact", "vfx", "shield_hit")


def presented(calls):
    """How many presentation calls (beam contacts, VFX spawns, shield hits)
    `calls` holds."""
    return sum(1 for c in calls if c[0] in PRESENTATION)


def split_calls(calls):
    """(every other call, in order; {tick: that tick's presentation calls,
    sorted}). A call's second element is its tick. A ShieldedContact is in
    neither: its shield hit stands for it."""
    ordered, shown = [], {}
    for c in calls:
        if isinstance(c, ShieldedContact):
            continue
        if c[0] in PRESENTATION:
            shown.setdefault(c[1], []).append(c)
        else:
            ordered.append(c)
    return ordered, {t: sorted(v, key=repr) for t, v in shown.items()}


def compare_calls(ref_calls, nat_calls):
    """The game-state calls equal in order; each tick's presentation equal
    as a multiset (ruling Q1), shielded beam contacts left out (their shield
    hits compare: ShieldedContact)."""
    ref, ref_shown = split_calls(ref_calls)
    nat, nat_shown = split_calls(nat_calls)
    for i, (x, y) in enumerate(zip(ref, nat)):
        assert x == y, "call %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref) == len(nat)
    assert sorted(ref_shown) == sorted(nat_shown), (sorted(ref_shown),
                                                    sorted(nat_shown))
    for t in ref_shown:
        assert ref_shown[t] == nat_shown[t], (
            "tick %d presentation differs:\n python %r\n native %r" % (
                t, ref_shown[t], nat_shown[t]))


def _place_in_ship(ship, sub):
    """`sub`'s name, made unique within `ship` by its place among the
    subsystems of that name in the ship's own walk order (the same in both
    arms): "Phaser[1]" for the second of two "Phaser" banks."""
    from engine.appc.subsystems import iter_subsystems
    name = sub.GetName()
    same = [s for s in iter_subsystems(ship) if s.GetName() == name]
    if len(same) < 2:
        return name
    for i, s in enumerate(same):
        if s is sub:
            return "%s[%d]" % (name, i)
    return name


def _claim(labels, obj, name):
    """Give `obj` the label `name`; one taken by another object is a
    collision two arms could compare equal through (task review M6)."""
    assert name not in labels.values(), (
        "recorder label %r names two objects" % name)
    labels[id(obj)] = name
    return name


class Recorder:
    """The per-tick record, the call log and the event log of one arm (see
    the module docstring). `ships` are labelled by name; anything else by
    first sight. `observer` answers incoming_ids every tick."""

    def __init__(self, mp, ships, observer, ship_instances=None,
                 native=False, extra=None):
        self.native = native
        # A callable returning more rows for this tick (appended last): what
        # a differential compares beyond this record (posed parts: weapon
        # state, part poses and mount positions -- posed_fight.py).
        self.extra = extra
        self.ships = list(ships)
        self.observer = observer
        self.ship_instances = ship_instances
        self.labels = {id(s): s.GetName() for s in self.ships}
        self.held = []
        self.named = []          # weapons labelled by name (held alive)
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
        self.queued = effect_split.Queued(mp, self.label, lambda: self.tick)
        self._spy(mp)

    # ── Labels ───────────────────────────────────────────────────────────────

    def label(self, obj):
        if obj is None:
            return None
        name = self.labels.get(id(obj))
        if name is None and isinstance(obj, ShipSubsystem):
            # A recorded ship's subsystem (a weapon, a weapon system), by
            # name: its first sight is often an event delivered at the tick
            # boundary -- a weapon event native delivers there, a damage
            # event both arms deliver there (native damage M2), in an order
            # against the native arm's boundary launches that differs from
            # the reference's mid-step ones. Held apart from the numbered
            # objects, so it never shifts a number.
            owner = obj._owning_ship()
            ship = self.labels.get(id(owner))
            if ship is not None:
                name = _claim(self.labels, obj, "%s/%s" % (
                    ship, _place_in_ship(owner, obj)))
                self.named.append(obj)
        if name is None and isinstance(obj, SetClass):
            # A set, by name, for the same reason (a death's events, which
            # both arms deliver at the boundary, name the ship's set).
            name = _claim(self.labels, obj, "set:%s" % obj.GetName())
            self.named.append(obj)
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
        update_all = projectiles.update_all
        # Every hit as delivered, and K3's decided hits in both arms
        # (spy_hits: the kernels apply theirs without combat.apply_hit).
        spy_hits(mp, self.calls, lambda: self.tick, self.label)

        def hit_row(t, ship, point, normal):
            self.calls.append((
                "hit", self.tick, self.label(t), self.label(ship),
                hx(point), hx(normal), hx(t._bubble_entry),
                point is t._bubble_entry))

        def update_spy(dt, ships, *, ship_instances=None):
            hits = update_all(dt, ships, ship_instances=ship_instances)
            for t, ship, point, normal in hits:
                hit_row(t, ship, point, normal)
            return hits

        mp.setattr(projectiles, "update_all", update_spy)
        spy_k3_hits(mp, hit_row)

        register = projectiles.register

        def register_spy(torpedo, *args, _orig=register, **kwargs):
            # Numbered at launch: with native on, its ET_TORPEDO_FIRED (its
            # first sight before) is delivered at the tick boundary, after
            # objects the rest of the step labels. (A launch K1 deferred is
            # registered there too, with its fire-time set: `args`.)
            _orig(torpedo, *args, **kwargs)
            self.label(torpedo)

        mp.setattr(projectiles, "register", register_spy)
        # The presentation calls, in the same log as the apply_hits: their
        # order among the hits is compared (a K2 resting contact's, batched
        # since round trips Task 3, included).
        spy_presentation(mp, self.calls, lambda: self.tick, self.label)

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
            if self.queued.takes(evt):
                self.queued.rows.append(row)
            else:
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
        if self.extra is not None:
            row.extend(self.extra())
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
    "steer_point:mount" is the attribution ASKs (unattributed: a mount the
    kernel cannot tell); "steer_point:posed" the steer points the kernel
    decided NATIVELY at a posed target's mount or Manual Aim pick
    (k3_posed_steers); and "steer_point:native_mount" the `_mount_key`
    writes DONE carried (the kernel attributed the mount itself: round
    trips, Task 4), cross-checked against k3_native_attributions."""

    def __init__(self, orig):
        self.orig = orig
        self.n = {}
        self.asked_guide = set()
        self.ask = _h.combat_k3_kinds()["ASK"]
        c = _h.combat_k3_counts()
        self.steer_why = dict(c["k3_steer_reasons"])
        self.posed_steers = c["k3_posed_steers"]
        self.native_mounts = c["k3_native_attributions"]

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
        c = _h.combat_k3_counts()
        posed = c["k3_posed_steers"]
        self.bump("steer_point:posed", posed - self.posed_steers)
        self.posed_steers = posed
        mounts = sum(1 for w in writes if w[5] is not None)
        assert mounts == c["k3_native_attributions"] - self.native_mounts, \
            (mounts, c["k3_native_attributions"], self.native_mounts)
        self.native_mounts = c["k3_native_attributions"]
        self.bump("steer_point:native_mount", mounts)
        rows = nc._k3_rows
        for h, _age, seen, _tvel, vel, _mount in writes:
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
    """Every per-tick row, call and event equal (floats by .hex();
    presentation per tick as a multiset, compare_calls)."""
    assert len(ref.log) == len(nat.log)
    for tick, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        assert len(a) == len(b), "tick %d: %d rows vs %d" % (tick, len(a),
                                                            len(b))
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                tick, x, y)
    compare_calls(ref.calls, nat.calls)
    for i, (x, y) in enumerate(zip(ref.events, nat.events)):
        assert x == y, "event %d differs:\n python %r\n native %r" % (i, x, y)
    assert len(ref.events) == len(nat.events)
    effect_split.compare(ref.queued, nat.queued)


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


def weapon_rows(label, systems, weapons):
    """Every weapon system's and weapon's fire-control state (the K1
    fight's record, tests/helpers/k1_fight.py):
    floats by .hex(), objects by `label`, a weapon's `_target_offset` by its
    hexes and by WHICH weapon first held that same object, and whether it is
    asleep (passive weapons: a `_firing` write, a logged one included, wakes
    it)."""
    from engine.appc import passive_state
    from engine.appc import weapon_subsystems as ws
    rows = []
    for g in systems:
        d = g.__dict__
        rows.append((label(g), hx(g.IsFiring()), hx(d.get("_fire_held")),
                     hx(d.get("_force_update")),
                     hx(d.get("_last_weapon_idx")),
                     hx(d.get("_last_group_fired")),
                     label(d.get("_held_target")),
                     [label(t) for t in d.get("_target_list", ())]))
    first = {}
    for i, w in enumerate(weapons):
        d = w.__dict__
        energy = isinstance(w, ws._EnergyWeaponFireMixin)
        tube = isinstance(w, ws.TorpedoTube)
        off = d.get("_target_offset")
        if off is not None:
            first.setdefault(id(off), i)
        rows.append((
            label(w), hx(w.IsFiring()), label(d.get("_target")),
            hx(d.get("_fire_timer", 0.0)), hx(d.get("_depleted")),
            hx(d.get("_dwell")), hx(d.get("_beam_on_countdown")),
            w.GetChargeLevel().hex() if energy else None,
            hx(d.get("_cooldown_remaining")),
            hx(w.GetNumReady()) if tube else None,
            hx(off) if isinstance(off, TGPoint3) else repr(off),
            None if off is None else first[id(off)],
            # A missed wake: asleep while NOT at rest (any write of a
            # WakeField wakes). The raw asleep flag differs by design with
            # native on: K0 steps every weapon and puts none to sleep
            # (spec 2026-11-02-native-weapon-state-design.md §4.3).
            passive_state.is_asleep(w) and not w._passive_at_rest()))
    return rows


# Posed parts (spec docs/superpowers/specs/2026-11-01-native-combat-posed-
# parts-design.md §4.5): every posed hand-back a differential with posed
# ships must see at 0, and the native posed-branch counters it must see run.

#: (counter path, reason) pairs that are 0 in a fight whose posed ships have
#: their slots resolved at every step boundary. Since aim points became
#: plain body points (fire control native only, M5) an offset no mount
#: claims is no hand-back at all, in K1, K2 or K3.
_POSED_ZERO = (
    [("k1_no_fire", None, why) for why in ("part_stale", "decision")]
    + [("k2_python_reasons", None, why)
       for why in ("posed_ship", "part_stale")]
    + [("k3_steer_reasons", None, why)
       for why in ("posed_target", "part_stale", "mount_stale")])


def _read(counts, key, sub, why):
    c = counts[key]
    return (c[sub] if sub is not None else c)[why]


def posed_fallbacks(counts):
    """{name: n} of every posed hand-back that must be 0 (_POSED_ZERO)."""
    return {"%s%s/%s" % (key, "" if sub is None else "[%s]" % sub, why):
            _read(counts, key, sub, why) for key, sub, why in _POSED_ZERO}


def round_trips(counts):
    """The round-trip-removal counters (plan 2026-11-01-native-combat-round-
    trips): K1 walks started with no WALK_START record and its logged beam
    sustains and idle bank stops (Tasks 1-2), K2 resting contacts batched
    and offline system stops logged (Task 3), K3 mounts attributed natively
    (Task 4)."""
    logged = counts["k1_logged"]
    return {"k1_logged/walk_start": logged["walk_start"],
            "k1_logged/beam_sustain": logged["beam_sustain"],
            "k1_logged/idle_bank_stop": logged["idle_bank_stop"],
            "k2_batched_contacts": counts["k2_batched_contacts"],
            "k2_logged_system_stop": counts["k2_logged_system_stop"],
            "k3_native_attributions": counts["k3_native_attributions"]}


def weapon_state_paths(counts):
    """The native weapon-state counters (spec 2026-11-02-native-weapon-
    state-design.md §5): weapons K0 stepped natively, writes the bindings
    applied in C (K0, K1, K2 logs), scalar mirror pushes made in one call."""
    return {"k0_steps": counts["k0_steps"],
            "c_applied_writes": counts["c_applied_writes"],
            "fast_pushes": counts["fast_pushes"]}


def check_weapon_state_paths(counts):
    """Each native weapon-state path ran in the native arm of a fight."""
    paths = weapon_state_paths(counts)
    for key, n in paths.items():
        assert n > 0, (key, paths)


def check_native_attributions(counts, tally):
    """Round trips Task 4 in a fight: torpedo mounts were attributed by the
    kernel (k3_native_attributions), every one rode a DONE `_mount_key`
    write the tally counted, and no steer_point ASK was left for an
    attribution (``unattributed``)."""
    native = counts["k3_native_attributions"]
    assert native > 0, counts
    assert tally.n.get("steer_point:native_mount", 0) == native, (
        native, tally.n)
    assert counts["k3_steer_reasons"]["unattributed"] == 0, counts
    assert tally.n.get("steer_point:mount", 0) == 0, tally.n


def posed_branches(counts):
    """The native posed branches: a posed ship's systems walked (K1), a Fire
    aimed at a posed target's offset (K1 `_RESOLVE`), a posed ship's banks
    (K2), a lock on a posed ship's subsystem (K2) and a torpedo steered at a
    posed target's mount or pick (K3)."""
    return {"k1_posed/walks": counts["k1_posed"]["walks"],
            "k1_posed/target_aims": counts["k1_posed"]["target_aims"],
            "k2_posed/banks": counts["k2_posed"]["banks"],
            "k2_posed/lock_aims": counts["k2_posed"]["lock_aims"],
            "k3_posed_steers": counts["k3_posed_steers"]}
