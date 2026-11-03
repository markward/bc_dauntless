"""K4: damage eligibility through the native kernel (native combat phase 3,
Task 2; spec docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md
§4.1, §4.2, §6).

With the switch on, `damage_eligibility.update` asks the kernel for the
eligible ships (`native_combat.k4_update`), over the per-step ship scan and
the per-step frame table (`native_combat.step_scan`). The answer must be the
SAME id set `select_eligible` -- left untouched as the reference -- returns,
for every scene; anything the kernel cannot decide exactly (a non-finite
radius, position or score, a duplicate ship, a patched function) falls back
to `select_eligible` whole.

Frames are real: mapped sets get their system frame through
`frames.frame_of` (region_hooks' flag + resolve's anchor/system lookups,
patched here to a table: neither is a function K4 stands in for).
"""
import math
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k4_eligible"),
    reason="native K4 bindings not built")

import engine.host_loop as host_loop  # noqa: E402,F401  (K2's class snapshot)
from engine.appc import damage_eligibility as de  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc.sets import SetClass  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.core import ids  # noqa: E402
from engine.systems import frames, region_hooks, resolve  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}

# set name -> (system, anchor_gu); a set in this table is mapped.
ANCHORS = {
    "K4SysA1": ("K4SysA", (0.0, 0.0, 0.0)),
    "K4SysA2": ("K4SysA", (1000.5, -20.25, 3.0)),
    "K4SysB1": ("K4SysB", (-7.0, 12.5, 0.125)),
}
SET_NAMES = ("K4SysA1", "K4SysA2", "K4SysB1", "K4Plain")


@pytest.fixture(autouse=True)
def _switch(monkeypatch):
    nc.reset()
    anchors = dict(ANCHORS)
    monkeypatch.setattr(
        resolve, "anchor_of",
        lambda name: anchors[name][1] if name in anchors else None)
    monkeypatch.setattr(
        resolve, "system_of",
        lambda name: anchors[name][0] if name in anchors else None)
    nc.configure(ON)
    assert nc.enabled()
    yield anchors
    for name in SET_NAMES:
        App.g_kSetManager._sets.pop(name, None)
    nc.reset()


def _make_set(name):
    s = SetClass()
    s.SetName(name)
    App.g_kSetManager._sets[name] = s
    if name in ANCHORS:
        region_hooks.mark_mapped(s)
    return s


def _ship(pSet, name, at=(0.0, 0.0, 0.0), radius=1.0):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslateXYZ(*at)
    s.SetRadius(radius)
    if pSet is not None:
        pSet.AddObjectToSet(s, name)
    return s


def _native(player, ships):
    """Run K4 (asserting it decided) and return its id set."""
    before = nc.counts()["k4_runs"]
    assert nc.k4_update(player, ships), nc.counts()["k4_python_reasons"]
    assert nc.counts()["k4_runs"] == before + 1
    return de.current()


class _Game:
    def __init__(self, player):
        self._player = player

    def GetPlayer(self):
        return self._player


def _update_as(monkeypatch, player, ships):
    """damage_eligibility.update with `player` as the game's player; returns
    the stored set (the kernel's, or select_eligible's on a fallback)."""
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(player),
                        raising=False)
    de.update(ships)
    return de.current()


def _reasons():
    return {k: v for k, v in nc.counts()["k4_python_reasons"].items() if v}


@pytest.fixture
def pool():
    """Four sets of 70 ships each plus 10 setless ships."""
    sets = {name: _make_set(name) for name in SET_NAMES}
    ships = []
    for name, pSet in sets.items():
        for i in range(70):
            ships.append(_ship(pSet, "%s_%d" % (name, i)))
    for i in range(10):
        ships.append(_ship(None, "Setless_%d" % i))
    return sets, ships


_COORDS = (0.0, -0.0, 1.0, -1.0, 5.0, 10.0, 250.0, -3.5)
_RADII = (0.0, -0.0, 1.0, 1.0, 2.0, 3.5, 0.25)


def _randomise(rng, ship):
    if rng.random() < 0.5:
        at = tuple(rng.choice(_COORDS) for _ in range(3))
    else:
        at = tuple(rng.uniform(-2000.0, 2000.0) for _ in range(3))
    ship.SetTranslateXYZ(*at)
    ship.SetRadius(rng.choice(_RADII) if rng.random() < 0.6
                   else rng.uniform(0.0, 50.0))


def test_k4_matches_select_eligible(pool):
    sets, every = pool
    rng = random.Random(20261101)
    kw = de.select_eligible.__kwdefaults__
    stock = kw["max_count"]
    try:
        for scene in range(2000):
            n = rng.randint(0, 70)
            ships = rng.sample(every, n)
            for s in ships:
                _randomise(rng, s)
            if rng.random() < 0.05:
                for s in ships:
                    s.SetRadius(rng.choice((0.0, -0.0)))
            roll = rng.random()
            if roll < 0.15 or not ships:
                player = None
            elif roll < 0.8:
                player = rng.choice(ships)
            else:
                player = rng.choice(every)
                _randomise(rng, player)
            kw["max_count"] = rng.choice((6, 6, 6, 6, 1, 0, 3, 10, 80))
            want = de.select_eligible(player, ships)
            got = _native(player, ships)
            assert got == want, "scene %d" % scene
    finally:
        kw["max_count"] = stock
    assert _reasons() == {}


def test_k4_matches_select_eligible_with_scaled_ships(pool):
    sets, every = pool
    rng = random.Random(20261103)
    scales = (1.0, 1.0, 2.5, 0.5, 3.0, 8.5, 0.0, -2.0, math.nan, math.inf)
    try:
        for scene in range(500):
            ships = rng.sample(every, rng.randint(0, 70))
            for s in ships:
                _randomise(rng, s)
                s.SetScale(rng.choice(scales))
            player = rng.choice(ships) if ships and rng.random() < 0.7 else None
            want = de.select_eligible(player, ships)
            got = _native(player, ships)
            assert got == want, "scene %d" % scene
    finally:
        for s in every:
            s.SetScale(1.0)
    assert _reasons() == {}


def test_k4_ties_break_by_id(pool):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "TiePlayer", at=(0.0, 0.0, 0.0))
    twins = [_ship(pSet, "Twin%d" % i, at=(5.0, 0.0, 0.0), radius=2.0)
             for i in range(10)]
    ships = [player] + twins
    rng = random.Random(7)
    for _ in range(20):
        rng.shuffle(ships)
        got = _native(player, ships)
        assert got == de.select_eligible(player, ships)
        assert got == frozenset([id(player)] +
                                sorted(id(t) for t in twins)[:5])


def test_k4_distance_is_math_dist(pool):
    """E3: CPython's math.dist, never sqrt(dx*dx + dy*dy + dz*dz). Two
    equal-radius ships whose positions are a permutation of each other tie
    under math.dist but not under the naive root; the tie goes to the lower
    id, and the naive root would pick the other ship. Radii are zero, so
    the score is the proximity alone and an ulp of distance survives."""
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "DPlayer", radius=0.0)
    lo, hi = sorted((_ship(pSet, "D1", radius=0.0),
                     _ship(pSet, "D2", radius=0.0)), key=id)
    rng = random.Random(5)

    def naive(v):
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    found = 0
    while found < 20:
        p = tuple(rng.uniform(-5.0e5, 5.0e5) for _ in range(3))
        q = (p[1], p[2], p[0])
        o = (0.0, 0.0, 0.0)
        if math.dist(p, o) != math.dist(q, o) \
                or 1.0 / (1.0 + naive(p)) == 1.0 / (1.0 + naive(q)):
            continue
        found += 1
        near, far = (p, q) if naive(p) < naive(q) else (q, p)
        hi.SetTranslateXYZ(*near)       # the naive root's pick
        lo.SetTranslateXYZ(*far)
        ships = [player, hi, lo]
        de.select_eligible.__kwdefaults__["max_count"] = 2
        try:
            got = _native(player, ships)
            assert got == de.select_eligible(player, ships)
        finally:
            de.select_eligible.__kwdefaults__["max_count"] = 6
        assert got == frozenset({id(player), id(lo)})


def test_k4_player_outside_the_list_in_another_set(pool):
    """The player not in ships_list, in a set no listed ship is in: its frame
    is resolved this step too (same system, other region)."""
    sets, _every = pool
    player = _ship(sets["K4SysA2"], "OPlayer", at=(-1000.5, 20.25, -3.0))
    near = _ship(sets["K4SysA1"], "ONear", at=(1.0, 0.0, 0.0))
    far = _ship(sets["K4SysA1"], "OFar", at=(400.0, 0.0, 0.0))
    other = _ship(sets["K4SysB1"], "OOther", at=(1.0, 0.0, 0.0))
    ships = [far, other, near]
    de.select_eligible.__kwdefaults__["max_count"] = 3
    try:
        got = _native(player, ships)
        assert got == de.select_eligible(player, ships)
    finally:
        de.select_eligible.__kwdefaults__["max_count"] = 6
    assert got == frozenset({id(player), id(near), id(far)})


def test_k4_cross_frame_gets_no_proximity(pool):
    sets, _every = pool
    player = _ship(sets["K4SysA1"], "XPlayer", at=(10.0, 0.0, 0.0))
    near_other_frame = _ship(sets["K4SysB1"], "XNear", at=(10.0, 0.0, 0.0))
    far_same_frame = _ship(sets["K4SysA1"], "XFar", at=(900.0, 0.0, 0.0))
    # Same system, other region: its anchor puts it 1000 GU off numerically
    # but this local position cancels that.
    same_system = _ship(sets["K4SysA2"], "XShift",
                        at=(-990.5, 20.25, -3.0))
    setless = _ship(None, "XSetless", at=(10.0, 0.0, 0.0))
    ships = [player, near_other_frame, far_same_frame, same_system, setless]
    de.select_eligible.__kwdefaults__["max_count"] = 3
    try:
        got = _native(player, ships)
        want = de.select_eligible(player, ships)
    finally:
        de.select_eligible.__kwdefaults__["max_count"] = 6
    assert got == want
    assert got == frozenset({id(player), id(same_system), id(far_same_frame)})


def test_k4_no_player_size_only(pool):
    sets, every = pool
    rng = random.Random(11)
    for _ in range(50):
        ships = rng.sample(every, 30)
        for s in ships:
            _randomise(rng, s)
        got = _native(None, ships)
        assert got == de.select_eligible(None, ships)
        # Size only: the six largest radii (ties by id).
        top = sorted(ships, key=lambda s: (-s.GetRadius(), id(s)))[:6]
        assert got == frozenset(id(s) for s in top)


def test_k4_all_zero_radii_or_one(pool):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "ZPlayer")
    ships = [player] + [_ship(pSet, "Z%d" % i, at=(float(i), 0.0, 0.0),
                              radius=(0.0 if i % 2 else -0.0))
                        for i in range(9)]
    player.SetRadius(-0.0)
    got = _native(player, ships)
    assert got == de.select_eligible(player, ships)
    assert got == frozenset([id(player)] + [id(s) for s in ships[1:6]])


@pytest.mark.parametrize("bad", ["nan radius", "inf radius", "inf position",
                                 "nan player position"])
def test_k4_nan_or_inf_falls_back(pool, monkeypatch, bad):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "NPlayer")
    ships = [player] + [_ship(pSet, "N%d" % i, at=(float(i), 0.0, 0.0))
                        for i in range(8)]
    if bad == "nan radius":
        ships[3].SetRadius(math.nan)
    elif bad == "inf radius":
        ships[3].SetRadius(math.inf)
    elif bad == "inf position":
        ships[3].SetTranslateXYZ(math.inf, 0.0, 0.0)
    else:
        player.SetTranslateXYZ(math.nan, 0.0, 0.0)
    assert not nc.k4_update(player, ships)
    assert _reasons() == {"nonfinite": 1}
    # Through update: the whole function runs in Python instead.
    got = _update_as(monkeypatch, player, ships)
    assert got == de.select_eligible(player, ships)
    assert _reasons() == {"nonfinite": 2}


def test_k4_duplicate_ship_falls_back(pool, monkeypatch):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "DPlayer")
    a = _ship(pSet, "DA", at=(1.0, 0.0, 0.0))
    b = _ship(pSet, "DB", at=(2.0, 0.0, 0.0))
    ships = [player, a, b, a]
    assert not nc.k4_update(player, ships)
    assert _reasons() == {"duplicate": 1}
    got = _update_as(monkeypatch, player, ships)
    assert got == de.select_eligible(player, ships)
    assert _reasons() == {"duplicate": 2}


_PATCH_TARGETS = (
    (de, "select_eligible"), (de, "_radius"), (frames, "system_distance"),
    (frames, "offset_between"), (frames, "frame_of"),
    (frames, "containing_set"), (frames, "local_in"), (frames, "_xyz"),
    (ids, "implements"), (math, "dist"),
)


@pytest.mark.parametrize("module, name", _PATCH_TARGETS,
                         ids=["%s.%s" % (m.__name__, n)
                              for m, n in _PATCH_TARGETS])
def test_k4_patched_function_falls_back(pool, monkeypatch, module, name):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "PPlayer")
    ships = [player] + [_ship(pSet, "P%d" % i, at=(float(i), 0.0, 0.0))
                        for i in range(8)]
    real = getattr(module, name)
    monkeypatch.setattr(module, name,
                        lambda *a, **k: real(*a, **k))
    assert not nc.k4_update(player, ships)
    assert _reasons() == {"patched": 1}
    monkeypatch.undo()
    assert nc.k4_update(player, ships)


def test_k4_instance_patch_falls_back(pool, monkeypatch):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "IPlayer")
    a = _ship(pSet, "IA", at=(1.0, 0.0, 0.0))
    a.GetRadius = lambda: 99.0
    ships = [player, a]
    assert not nc.k4_update(player, ships)
    assert _reasons() == {"instance_patch": 1}
    got = _update_as(monkeypatch, player, ships)
    assert got == de.select_eligible(player, ships)
    assert _reasons() == {"instance_patch": 2}


def test_k4_player_without_row_falls_back(pool):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    a = _ship(pSet, "RA", at=(1.0, 0.0, 0.0))

    class _Fake:
        def GetRadius(self):
            return 1.0

    assert not nc.k4_update(_Fake(), [a])
    assert _reasons() == {"player": 1}


def test_k4_audit_stands_down(pool):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    player = _ship(pSet, "APlayer")
    nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})
    assert nc.audit_enabled()
    assert not nc.k4_update(player, [player])
    assert _reasons() == {"audit": 1}


def test_frame_table_resolved_every_step(pool, _switch):
    anchors = _switch
    sets, _every = pool
    player = _ship(sets["K4SysA1"], "FPlayer", at=(0.0, 0.0, 0.0))
    # In region A2: 1000.5 GU east of the player at the first anchors.
    a2 = _ship(sets["K4SysA2"], "FA2", at=(0.0, 0.0, 0.0))
    local = _ship(sets["K4SysA1"], "FLocal", at=(500.0, 0.0, 0.0))
    ships = [player, a2, local]
    de.select_eligible.__kwdefaults__["max_count"] = 2
    try:
        nc.step_scan(ships)
        assert _native(player, ships) == frozenset({id(player), id(local)})
        # Region A2's anchor moves right next to the player: the next step
        # must use it, not the frame it resolved last step.
        anchors["K4SysA2"] = ("K4SysA", (3.0, 0.0, 0.0))
        nc.step_scan(ships)
        got = _native(player, ships)
        assert got == de.select_eligible(player, ships)
        assert got == frozenset({id(player), id(a2)})
        # And A2 leaves the system: no proximity credit at all.
        anchors["K4SysA2"] = ("K4SysOther", (3.0, 0.0, 0.0))
        nc.step_scan(ships)
        got = _native(player, ships)
        assert got == de.select_eligible(player, ships)
        assert got == frozenset({id(player), id(local)})
    finally:
        de.select_eligible.__kwdefaults__["max_count"] = 6


def test_step_scan_returns_the_sets_in_play(pool):
    sets, _every = pool
    a = _ship(sets["K4SysA1"], "SA")
    b = _ship(sets["K4SysB1"], "SB")
    c = _ship(None, "SC")
    st = nc.step_scan([a, b, c])
    assert st.ok and st.reason is None
    assert st.sets == [sets["K4SysA1"].__dict__["_nslot"],
                       sets["K4SysB1"].__dict__["_nslot"]]


def test_update_dispatches_to_k4_and_host_step_scans(pool, monkeypatch):
    sets, _every = pool
    pSet = sets["K4SysA1"]
    ships = [_ship(pSet, "U%d" % i, at=(float(i), 0.0, 0.0))
             for i in range(8)]
    before = nc.counts()["k4_runs"]
    de.update(ships)
    assert nc.counts()["k4_runs"] == before + 1
    assert de.current() == de.select_eligible(None, ships)
    calls = []
    real = nc.step_scan
    monkeypatch.setattr(nc, "step_scan",
                        lambda s: calls.append(s) or real(s))
    host_loop._advance_combat(ships, 1.0 / 60.0, push_render_data=False)
    assert len(calls) == 1 and calls[0] == ships
    assert nc.counts()["k4_runs"] == before + 2
