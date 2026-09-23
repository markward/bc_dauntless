"""Appendage severance: attribution, accumulation, threshold.

The behaviour these pin is the one that could not be achieved at all under
voxel connectivity — see part_severance's module docstring for the measurement.
"""
import pytest

from engine.appc import articulation, part_severance as ps


LEAF = "birdofprey"


class _Hull:
    def __init__(self, maxc=4000.0):
        self._max = maxc
        self.condition = maxc

    def GetMaxCondition(self):
        return self._max


class _Pos:
    def __init__(self, x, y, z): self._v = (x, y, z)
    def GetX(self): return self._v[0]
    def GetY(self): return self._v[1]
    def GetZ(self): return self._v[2]


class _Sub:
    def __init__(self, name, pos):
        self.name = name
        self._pos = _Pos(*pos)
        self.condition = 100.0

    def GetPosition(self): return self._pos
    def SetCondition(self, v): self.condition = float(v)


class _Ship:
    """Stands in for a ShipClass. Mirrors only the surface severance touches."""

    def __init__(self, hull=4000.0, subs=()):
        self._hull = _Hull(hull)
        self._subs = list(subs)
        self._articulation_leaf = LEAF      # pre-cached: no SDK import in tests

    def GetHull(self): return self._hull
    def _iter_subsystems(self): return list(self._subs)


# ── Attribution ──────────────────────────────────────────────────────────────

def test_a_point_out_on_the_wing_resolves_to_that_wing():
    """Outboard of the body's |x| 0.31, only the wing box contains the point."""
    assert ps.part_for_point(LEAF, (0.8, 0.0, -0.4)) == "left wing01"
    assert ps.part_for_point(LEAF, (-0.8, 0.0, -0.4)) == "left wing"


def test_the_wing_root_is_ambiguous_and_falls_back_to_the_body():
    """The roots are EMBEDDED in the hull — the wing boxes overlap the body box
    from |x| 0.1236 to 0.31. A hit there is inside two boxes, and the safe
    answer is None (unattributed, i.e. behaves as it always did) rather than
    silently crediting a wing for damage done to the hull."""
    assert ps.part_for_point(LEAF, (0.20, -0.5, -0.03)) is None


def test_a_point_on_the_nose_resolves_to_the_head():
    assert ps.part_for_point(LEAF, (0.0, 0.85, 0.0)) == "head"


def test_a_ship_with_no_authored_boxes_attributes_nothing():
    assert ps.part_for_point("galaxy", (0.8, 0.0, -0.4)) is None


# ── Accumulation and threshold ───────────────────────────────────────────────

def _wing_hit(ship, amount):
    # iid None = headless: the sim-side detach still runs, visuals are skipped.
    return ps.record_hit(ship, None, (0.8, 0.0, -0.4), amount)


def test_damage_accumulates_on_the_part_it_landed_on():
    ship = _Ship()
    _wing_hit(ship, 100.0)
    _wing_hit(ship, 150.0)
    assert ps.damage_on(ship, "left wing01") == pytest.approx(250.0)
    assert ps.damage_on(ship, "left wing") == 0.0


def test_the_wing_shears_at_twenty_percent_of_max_hull():
    """4000 hull x 0.20 = 800. Cumulative: eight 100-point hits, not one big
    one — the whole point of the rule is that chipping away works."""
    ship = _Ship(hull=4000.0)
    for _ in range(7):
        assert _wing_hit(ship, 100.0) is None      # 700: still attached
    assert _wing_hit(ship, 100.0) == "left wing01"  # 800: gone
    assert ps.is_detached(ship, "left wing01")


def test_the_other_wing_is_unaffected():
    ship = _Ship()
    _wing_hit(ship, 5000.0)
    assert ps.is_detached(ship, "left wing01")
    assert not ps.is_detached(ship, "left wing")


def test_a_part_never_severs_twice():
    """`sever` marks detached BEFORE destroying subsystems, so a re-entrant hit
    arriving from a subsystem-destruction event cannot shed the same wing
    again (which would spawn a second chunk)."""
    ship = _Ship()
    assert _wing_hit(ship, 5000.0) == "left wing01"
    assert _wing_hit(ship, 5000.0) is None
    assert ps.sever(ship, None, "left wing01") is None


def test_a_non_detachable_part_accumulates_nothing():
    """The head is inside PART_BOXES but absent from DETACHABLE, so it can be
    hit forever and never come off. The body must never detach either."""
    ship = _Ship()
    for _ in range(50):
        assert ps.record_hit(ship, None, (0.0, 0.85, 0.0), 500.0) is None
    assert ps.damage_on(ship, "head") == 0.0
    assert not ps.is_detached(ship, "head")


def test_unattributed_damage_does_not_accumulate_anywhere():
    ship = _Ship()
    ps.record_hit(ship, None, (0.20, -0.5, -0.03), 5000.0)   # ambiguous wing root
    assert ps.damage_on(ship, "left wing01") == 0.0
    assert not ps.is_detached(ship, "left wing01")


def test_zero_and_negative_damage_are_ignored():
    ship = _Ship()
    assert _wing_hit(ship, 0.0) is None
    assert _wing_hit(ship, -10.0) is None
    assert ps.damage_on(ship, "left wing01") == 0.0


def test_a_ship_with_no_detachable_parts_is_untouched():
    """The overwhelmingly common case, and it must cost almost nothing: a hull
    with no authored parts returns before any geometry is considered."""
    ship = _Ship()
    ship._articulation_leaf = "galaxy"
    assert _wing_hit(ship, 100000.0) is None
    assert ps.damage_on(ship, "left wing01") == 0.0


def test_a_ship_without_a_hull_never_severs():
    """A hull-less object would give max_hull 0; a 0 limit must NOT read as
    'already exceeded', or every prop would shed parts on its first scratch."""
    ship = _Ship()
    ship._hull = None
    ship.GetHull = lambda: None
    assert _wing_hit(ship, 100000.0) is None


# ── Subsystems ───────────────────────────────────────────────────────────────

def test_a_severed_wing_destroys_the_cannon_mounted_on_it():
    """Star Cannon is authored at (1.008, 0.450, -0.670) — on the starboard
    wing. A gun that has left the ship cannot keep firing."""
    star = _Sub("Star Cannon", (1.008, 0.450, -0.670))
    port = _Sub("Port Cannon", (-1.009, 0.450, -0.670))
    body = _Sub("Warp Core", (0.0, -0.33, 0.0))
    ship = _Ship(subs=(star, port, body))

    _wing_hit(ship, 5000.0)

    assert star.condition == 0.0, "the cannon on the severed wing must die"
    assert port.condition == 100.0, "the other wing's cannon is untouched"
    assert body.condition == 100.0, "body subsystems are untouched"


def test_reset_clears_damage_and_detachments():
    ship = _Ship()
    _wing_hit(ship, 5000.0)
    ps.reset_ship(ship)
    assert ps.damage_on(ship, "left wing01") == 0.0
    assert not ps.is_detached(ship, "left wing01")


# ── The authored data ────────────────────────────────────────────────────────

def test_only_the_wings_are_detachable():
    d = articulation.detachable_for(LEAF)
    assert set(d) == {"left wing", "left wing01"}
    assert all(v == pytest.approx(0.20) for v in d.values())


def test_every_detachable_part_has_a_box():
    """A part that can shear but has no geometry would accumulate nothing and
    silently never detach."""
    for leaf, parts in articulation.DETACHABLE.items():
        boxes = articulation.part_boxes_for(leaf)
        for name in parts:
            assert name in boxes, (leaf, name)
