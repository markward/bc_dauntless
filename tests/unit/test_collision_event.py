"""``CollisionEvent`` / ``ET_OBJECT_COLLISION`` — BC's collision notification.

Neither existed: ``App.ET_OBJECT_COLLISION`` was an undefined ``_NamedStub`` and
there was no event class at all, so every SDK consumer of a collision was dead.
Live telemetry has the constant twice — docs/stub_heatmap.md rank 118 (``App``,
65 hits over 62/233 runs) and rank 137 (``EventType``, 60 hits over 57/233). The
``EventType`` row is the engine logging a real SDK handler registration made
against the stub, i.e. the script side is already wired and only the engine half
was missing.

What it unblocks: ``Effects.CollisionEffect`` (an explosion at each contact point
plus the collision sound), ``MissionLib.FriendlyFireCollisionHandler`` (ramming a
friendly is a game over), and E7M2's ``ShipsCollided``.

Two contracts here are ground truth rather than invention.

* **Delivery.** MissionLib.py:3905-3907 says it outright: *"Only need to check
  either the source or the destination, since there's an event sent for each."*
  It reads ``GetDestination()`` as the ship that collided and ``GetSource()`` as
  what it hit. So a collision posts TWO events, one per object, swapped.

* **Shape.** From the clean-room reference (grade reviewed-not-tested, read from
  the binary): ``CollisionEvent`` is ``sizeof 0x44`` holding an embedded NiTArray
  of ``NiPoint3*`` plus a float collision force at +0x40, and ``GetNumPoints``
  returns ``m_uiESize`` (+0x38). The producer at 0x00594840 caps the set at two:
  if exactly one contact was gathered it stores that one, **otherwise it keeps
  the pair with the greatest separation and discards the rest**. Neither accessor
  bounds-checks — an out-of-range index is a fault, not an error return.

That reduction is also why we know BC's collision is shape-aware: sphere-vs-sphere
yields exactly one contact, so there would be no longer list to reduce and
"greatest separation" would be meaningless. Our own detection is still a single
sphere pair and supplies one point; the cap is implemented now so it is correct
by construction when per-mesh bounds land.
"""
import App
import pytest

from engine.appc.math import TGPoint3


def _pt(x, y=0.0, z=0.0):
    return TGPoint3(float(x), float(y), float(z))


# ── The constant ─────────────────────────────────────────────────────────────

def test_event_type_is_a_real_distinct_int():
    assert type(App.ET_OBJECT_COLLISION) is int
    assert App.ET_OBJECT_COLLISION < 1200        # below the allocator floor
    assert App.ET_OBJECT_COLLISION != App.ET_CLOAKED_COLLISION


# ── The event object ─────────────────────────────────────────────────────────

def test_new_event_has_no_points():
    evt = App.CollisionEvent_Create()
    assert evt.GetNumPoints() == 0


def test_a_single_contact_is_kept_as_one_point():
    """The producer's first branch: exactly one contact gathered => store it,
    with no reduction."""
    evt = App.CollisionEvent_Create()
    evt.SetPoints([_pt(3.0, 4.0, 5.0)])

    assert evt.GetNumPoints() == 1
    p = evt.GetPoint(0)
    assert (p.x, p.y, p.z) == (3.0, 4.0, 5.0)


def test_more_than_two_contacts_reduce_to_the_most_separated_pair():
    """THE reduction, and the reason we know BC is shape-aware. Points along a
    line at 0, 1 and 10: the widest pair is (0, 10) and the middle one goes."""
    evt = App.CollisionEvent_Create()
    evt.SetPoints([_pt(0.0), _pt(1.0), _pt(10.0)])

    assert evt.GetNumPoints() == 2
    kept = sorted(evt.GetPoint(i).x for i in range(evt.GetNumPoints()))
    assert kept == [0.0, 10.0]


def test_reduction_is_by_separation_not_by_arrival_order():
    """Guard against 'keep the first two', which passes the test above by luck
    if the widest pair happens to arrive first."""
    evt = App.CollisionEvent_Create()
    evt.SetPoints([_pt(0.0), _pt(0.5), _pt(0.25), _pt(9.0)])

    kept = sorted(evt.GetPoint(i).x for i in range(evt.GetNumPoints()))
    assert kept == [0.0, 9.0]


def test_exactly_two_contacts_are_both_kept():
    evt = App.CollisionEvent_Create()
    evt.SetPoints([_pt(1.0), _pt(2.0)])
    assert evt.GetNumPoints() == 2


def test_points_are_copies_not_aliases():
    """Elements are separate heap allocations in BC (NiPoint3*, each its own
    0xc-byte block). A caller mutating the point it handed in must not reach
    inside the event."""
    src = _pt(1.0, 2.0, 3.0)
    evt = App.CollisionEvent_Create()
    evt.SetPoints([src])
    src.x = 99.0
    assert evt.GetPoint(0).x == 1.0


def test_out_of_range_index_raises_rather_than_returning_a_stub():
    """BC does not bounds-check and faults. The one thing we must NOT do is
    hand back a truthy stub that reads as a valid point."""
    evt = App.CollisionEvent_Create()
    evt.SetPoints([_pt(1.0)])
    with pytest.raises(IndexError):
        evt.GetPoint(5)


def test_collision_force_round_trips():
    evt = App.CollisionEvent_Create()
    evt.SetCollisionForce(12.5)
    assert evt.GetCollisionForce() == pytest.approx(12.5)


def test_collision_force_defaults_to_zero():
    assert App.CollisionEvent_Create().GetCollisionForce() == 0.0


# ── Delivery: one event per object, source/destination swapped ───────────────

def _colliding_pair():
    """Two ships on a closing course, overlapping enough to register."""
    from engine.appc.ships import ShipClass_Create
    a = ShipClass_Create("Galaxy")
    b = ShipClass_Create("Galaxy")
    for s in (a, b):
        s.SetRadius(10.0)
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    b.SetTranslateXYZ(12.0, 0.0, 0.0)
    a.SetVelocity(TGPoint3(5.0, 0.0, 0.0))     # closing
    b.SetVelocity(TGPoint3(-5.0, 0.0, 0.0))
    return a, b


def _capture_collision_events():
    received = []

    def _on(dest, event):
        received.append(event)

    globals()["_on_collision"] = _on
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_OBJECT_COLLISION, None, __name__ + "._on_collision")
    return received


def test_a_collision_posts_one_event_per_object_with_source_and_destination_swapped():
    """MissionLib.py:3906 relies on this exactly: it reads GetDestination() as
    the colliding ship and GetSource() as the collidee, and says an event is
    sent for each."""
    from engine.appc.collisions import resolve_collisions

    received = _capture_collision_events()
    a, b = _colliding_pair()

    resolve_collisions([a, b])

    pairs = {(id(e.GetDestination()), id(e.GetSource())) for e in received}
    assert pairs == {(id(a), id(b)), (id(b), id(a))}


def test_the_posted_event_carries_a_contact_point_and_a_force():
    from engine.appc.collisions import resolve_collisions

    received = _capture_collision_events()
    a, b = _colliding_pair()

    resolve_collisions([a, b])

    assert received, "no collision event posted"
    for evt in received:
        assert evt.GetNumPoints() >= 1
        assert evt.GetCollisionForce() > 0.0


def test_a_non_collision_posts_nothing():
    """Receding ships are debounced by _respond_pair and must stay silent."""
    from engine.appc.collisions import resolve_collisions

    received = _capture_collision_events()
    a, b = _colliding_pair()
    a.SetVelocity(TGPoint3(-5.0, 0.0, 0.0))    # receding
    b.SetVelocity(TGPoint3(5.0, 0.0, 0.0))

    resolve_collisions([a, b])

    assert received == []
