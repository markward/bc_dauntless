"""Every overlapping subsystem takes the FULL post-shield damage, not a share.

BC offers each subsystem inside the splash the full damage and sums the
residuals; we applied a distance-weighted share instead. Named as a real
divergence, deliberately deferred, in
``docs/superpowers/specs/2026-08-16-shield-system-redesign-design.md`` 12.

⚠️ **Evidence grade.** The BC side is a `reviewed-not-tested` binary reading —
the routine was read, never executed — and that same spec records that our own
probe q05 data is **non-discriminating** between the two models. What tips it
is Mark's live observation (2026-08-20) that Dauntless shows less subsystem
damage than it should. Do not cite this as measured BC behaviour.

**Measured before changing anything**, sampling 200k hull hits against the real
Galaxy hardpoint (34 subsystems carrying both a position and a radius):

    hits overlapping NO subsystem   58.2%   (phaser r_hit = 0.15 GU)
    mean subsystems overlapped      0.64
    of overlaps, already weight 1.0 62%
    full-damage model vs current    1.26x

So the weighted share was never the main reason subsystem damage is scarce:
the weight is clamped to 1.0 for any hit inside the subsystem's own radius, and
only falls off in the thin shell between ``r_sub`` and ``r_sub + r_hit``. The
dominant factor is the ~59% of hits that overlap nothing at all, because the
catchment is tiny against the hull. This change is a fidelity fix worth ~25%,
not a fix for the scarcity.
"""
import pytest

from engine.appc.combat import apply_hit
from engine.appc.math import TGPoint3


class _Sub:
    """Minimal subsystem: a position, a catchment radius, a condition."""

    def __init__(self, name, pos, radius, condition=100000.0):
        self._name = name
        self._pos = TGPoint3(*pos)
        self._radius = radius
        self._condition = condition

    def GetName(self):      return self._name
    def GetPosition(self):  return self._pos
    def GetRadius(self):    return self._radius
    def GetCondition(self): return self._condition
    def SetCondition(self, v): self._condition = max(0.0, float(v))
    def GetMaxCondition(self): return 100000.0


class _Ship:
    """Fake ship exposing only what the attribution resolver walks.

    Deliberately NOT ShipClass_Create: that pre-populates ten subsystems at
    the origin with radius 0, every one of which overlaps a splash centred
    there — which silently made an earlier draft of these tests measure
    ten subsystems instead of the two under test.
    """

    def __init__(self, hull, children):
        self._hull = hull
        self._children = list(children)
        self._loc = TGPoint3(0, 0, 0)
        self._dying = False

    def GetShields(self): return None          # unshielded: damage reaches subs
    def GetHull(self): return self._hull
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i): return self._children[i]
    def GetWorldLocation(self): return self._loc
    def IsDying(self): return 1 if self._dying else 0
    def SetDying(self, v): self._dying = bool(v)

    def DamageSystem(self, subsystem, amount, source=None):
        if subsystem is None:
            return
        subsystem.SetCondition(subsystem.GetCondition() - float(amount))


def _ship_with(subs):
    return _Ship(_Sub("Hull", (0.0, 0.0, 0.0), 0.0), subs)


def _damage_calls(ship, monkeypatch):
    """Record every (subsystem_name, amount) DamageSystem receives."""
    calls = []
    original = ship.DamageSystem

    def spy(subsystem, amount, source=None):
        name = subsystem.GetName() if hasattr(subsystem, "GetName") else "?"
        calls.append((name, amount))
        return original(subsystem, amount, source)

    monkeypatch.setattr(ship, "DamageSystem", spy)
    return calls


def test_two_overlapping_subsystems_each_take_the_full_damage(monkeypatch):
    """Not half each. BC offers the full damage to every subsystem in the
    splash and sums the residuals."""
    a = _Sub("Alpha", (0.0, 0.0, 0.0), 0.25)
    b = _Sub("Beta", (0.05, 0.0, 0.0), 0.25)
    ship = _ship_with([a, b])
    calls = _damage_calls(ship, monkeypatch)

    apply_hit(ship, 400.0, TGPoint3(0.0, 0.0, 0.0), source=None,
              splash_radius=0.15)

    got = {n: amt for n, amt in calls if n in ("Alpha", "Beta")}
    assert got == {"Alpha": pytest.approx(400.0), "Beta": pytest.approx(400.0)}


def test_a_subsystem_in_the_falloff_shell_also_takes_the_full_damage(monkeypatch):
    """The actual behaviour change. Inside its own radius a subsystem already
    got weight 1.0; it is the outer shell (r_sub .. r_sub + r_hit) that was
    scaled down, and 38% of real overlaps land there."""
    r_sub, r_hit = 0.25, 0.15
    d = r_sub + 0.5 * r_hit          # weight was (r_sub + r_hit - d)/r_hit = 0.5
    far = _Sub("Far", (d, 0.0, 0.0), r_sub)
    ship = _ship_with([far])
    calls = _damage_calls(ship, monkeypatch)

    apply_hit(ship, 400.0, TGPoint3(0.0, 0.0, 0.0), source=None,
              splash_radius=r_hit)

    assert [amt for n, amt in calls if n == "Far"] == [pytest.approx(400.0)]


def test_a_subsystem_outside_the_splash_still_takes_nothing(monkeypatch):
    """The overlap test is unchanged — only the AMOUNT moved. This is the
    guard that the change did not turn into 'everything takes everything'."""
    near = _Sub("Near", (0.0, 0.0, 0.0), 0.25)
    outside = _Sub("Outside", (0.45, 0.0, 0.0), 0.25)   # d > r_sub + r_hit
    ship = _ship_with([near, outside])
    calls = _damage_calls(ship, monkeypatch)

    apply_hit(ship, 400.0, TGPoint3(0.0, 0.0, 0.0), source=None,
              splash_radius=0.15)

    assert [n for n, _ in calls if n == "Outside"] == []
    assert [n for n, _ in calls if n == "Near"] == ["Near"]


def test_the_vfx_primary_subsystem_is_still_the_closest_one(monkeypatch):
    """`_pick_primary_subsystem_for_dispatch` ranks on the splash WEIGHT, which
    still varies with distance even though the damage no longer does. If the
    weight stopped being recorded, the impact VFX would start naming an
    arbitrary subsystem."""
    seen = {}
    import engine.appc.hit_feedback as hf
    monkeypatch.setattr(hf, "dispatch",
                        lambda **kw: seen.update(subsystem=kw.get("subsystem")))

    close = _Sub("Close", (0.0, 0.0, 0.0), 0.25)
    edge = _Sub("Edge", (0.35, 0.0, 0.0), 0.25)
    ship = _ship_with([edge, close])      # deliberately not in distance order

    apply_hit(ship, 400.0, TGPoint3(0.0, 0.0, 0.0), source=None,
              splash_radius=0.15)

    assert seen["subsystem"] is not None
    assert seen["subsystem"].GetName() == "Close"


def test_absorbed_subsystem_total_sums_the_full_amounts(monkeypatch):
    """What hit_feedback receives, and what severity classification reads."""
    seen = {}
    import engine.appc.hit_feedback as hf
    monkeypatch.setattr(hf, "dispatch",
                        lambda **kw: seen.update(
                            absorbed=kw.get("absorbed_subsystem")))

    subs = [_Sub(f"S{i}", (0.02 * i, 0.0, 0.0), 0.25) for i in range(3)]
    ship = _ship_with(subs)

    apply_hit(ship, 400.0, TGPoint3(0.0, 0.0, 0.0), source=None,
              splash_radius=0.15)

    assert seen["absorbed"] == pytest.approx(3 * 400.0)
