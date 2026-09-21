"""Disabled shield generator → Update(dt) drops every face to zero and
regenerates nothing, without mutating _charge_per_second. Repair restores
regen at the original rates, refilling from zero. Measured on the original
exe (stbc-oracle bible §5.3 S6, `regen_gen{50,20}_face50`): below the
generator's DisabledPercentage all six faces read 0 immediately."""
from engine.appc.subsystems import ShieldSubsystem


def _generator(condition=100.0, max_condition=100.0, disabled_percentage=0.75):
    """A six-face shield generator with all faces at max.

    Powered on (IsOn=True) by default — these tests exercise the
    damaged-vs-functional gate; alert-level gating is covered separately
    in test_shield_subsystem.test_update_powered_down_still_regenerates.
    """
    s = ShieldSubsystem("ShieldGen")
    s.TurnOn()
    s._max_condition = max_condition
    s._condition = condition
    s._disabled_percentage = disabled_percentage
    for f in range(s.NUM_SHIELDS):
        s.SetMaxShields(f, 1000.0)
        s.SetShieldChargePerSecond(f, 50.0)
    # Drain front face so regen has somewhere to go.
    s.SetCurrentShields(s.FRONT_SHIELDS, 500.0)
    return s


def test_healthy_generator_regens():
    s = _generator()
    s.Update(dt=1.0)
    # 500 + 50*1 = 550, clamped to 1000 max
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 550.0


def test_disabled_generator_drops_every_face_and_skips_regen():
    s = _generator()
    s.SetCondition(10.0)  # 10 <= 0.75 * 100 = 75 -> disabled
    assert s.IsDisabled() == 1
    s.Update(dt=1.0)
    assert [s.GetCurrentShields(f) for f in range(s.NUM_SHIELDS)] == [0.0] * 6
    s.Update(dt=1.0)
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 0.0


def test_destroyed_generator_drops_every_face_and_skips_regen():
    s = _generator()
    s.SetCondition(0.0)
    assert s.IsDestroyed() == 1
    s.Update(dt=1.0)
    assert [s.GetCurrentShields(f) for f in range(s.NUM_SHIELDS)] == [0.0] * 6


def test_disabled_generator_preserves_charge_per_second():
    """Gate is read-time: the stored regen rates are not mutated.
    Repair restores regen at the original values, refilling from zero."""
    s = _generator()
    s.SetCondition(10.0)
    s.Update(dt=1.0)
    assert s.GetShieldChargePerSecond(s.FRONT_SHIELDS) == 50.0
    # Repair.
    s.SetCondition(100.0)
    assert s.IsDisabled() == 0
    s.Update(dt=1.0)
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 50.0


def test_disabled_generator_still_takes_damage():
    """ApplyDamage is independent of Update — drain still works on whatever
    charge is stored (Update has not run here, so the face still holds)."""
    s = _generator()
    s.SetCondition(10.0)
    overflow = s.ApplyDamage(s.FRONT_SHIELDS, 200.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(s.FRONT_SHIELDS) == 300.0
