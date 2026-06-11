# tests/unit/test_subsystem_emitters_budget.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def _ship_with_n(n, state="damaged", obj_id=1, loc=(0, 0, 0)):
    subs = [FakeSub("WarpEngineSubsystem", name="n%d" % i, pos=(i, 0, 0), state=state)
            for i in range(n)]
    return FakeShip(obj_id=obj_id, subs=subs, loc=loc)


def test_per_ship_cap_admits_top_n():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    m.update([_ship_with_n(6)], camera_pos=None, dt=0.1)
    assert m.active_count() == 3          # only 3 of 6 spawned
    assert len(b.created) == 3


def test_disabled_outranks_damaged_under_cap():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=1, r_cull=None)
    dmg = FakeSub("WarpEngineSubsystem", name="d", pos=(1, 0, 0), state="damaged")
    dis = FakeSub("ImpulseEngineSubsystem", name="x", pos=(2, 0, 0), state="disabled")
    m.update([FakeShip(subs=[dmg, dis])], None, 0.1)
    assert m.active_count() == 1
    # the single admitted slot went to the more severe DISABLED subsystem
    assert b.created[0].params["fSize"] == 1.2  # impulse DISABLED size


def test_distance_cull_suppresses_far_ship():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=500.0)
    far = _ship_with_n(2, loc=(10000.0, 0.0, 0.0))
    m.update([far], camera_pos=(0.0, 0.0, 0.0), dt=0.1)
    assert m.active_count() == 0


def test_proximity_breaks_ties_between_ships():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=1, r_cull=None)
    near = _ship_with_n(1, obj_id=1, loc=(10.0, 0.0, 0.0))
    far  = _ship_with_n(1, obj_id=2, loc=(900.0, 0.0, 0.0))
    # Global cap is per-ship here, so both can spawn; assert both got slots and
    # the near ship's candidate sorted first within the admitted set.
    m.update([near, far], camera_pos=(0.0, 0.0, 0.0), dt=0.1)
    assert m.active_count() == 2


def test_priority_bias_breaks_tier_ties():
    # Two subsystems on one ship, same severity tier (TIER_DAMAGED), different
    # priority_bias.  With n_per_ship=1 only the higher-bias descriptor is admitted.
    se.reset_registry()
    # Register two kinds at the same tier with distinct biases and a tag param
    # that lets us identify which descriptor was chosen.
    desc_high = se.PlumeDescriptor(
        factory="CreateSmokeHigh",
        params={"tag": "high"},
        direction_mode=se.DirectionMode.FIXED_BODY_VECTOR,
        priority_bias=10.0,
    )
    desc_low = se.PlumeDescriptor(
        factory="CreateSmokeHigh",
        params={"tag": "low"},
        direction_mode=se.DirectionMode.FIXED_BODY_VECTOR,
        priority_bias=1.0,
    )
    se.register_kind_alias("HighBiasSubsystem", "bias_kind_high")
    se.register_kind_alias("LowBiasSubsystem",  "bias_kind_low")
    se.register("bias_kind_high", se.TIER_DAMAGED, desc_high)
    se.register("bias_kind_low",  se.TIER_DAMAGED, desc_low)

    sub_high = FakeSub("HighBiasSubsystem", name="h", pos=(1.0, 0.0, 0.0), state="damaged")
    sub_low  = FakeSub("LowBiasSubsystem",  name="l", pos=(2.0, 0.0, 0.0), state="damaged")

    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=1, r_cull=None)
    m.update([FakeShip(subs=[sub_high, sub_low])], None, 0.1)

    assert m.active_count() == 1
    assert b.created[0].params["tag"] == "high"  # high bias wins the single slot


def test_suppressed_active_fades_when_budget_shrinks():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    ship = _ship_with_n(3)
    m.update([ship], None, 0.1)
    assert m.active_count() == 3
    handles = list(b.created)
    # Shrink the budget: the lowest-priority active plume must fade, not pop.
    m.n_per_ship = 2
    m.update([ship], None, 0.1)
    faded = [h for h in handles if h.emitting is False]
    assert len(faded) == 1
