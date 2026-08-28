"""ShieldSubsystem._charge_accum is real instance state, not a getattr default.

BC's shield generator charges on a 0.5 s cadence, and `_charge_accum` is the
carry between frames. It used to be reached only as
`getattr(self, "_charge_accum", 0.0)`, which works but leaves the attribute
absent from a fresh instance's `__dict__` — so it is invisible to anything that
serialises state by walking `__dict__`, and a save/restore silently resets the
carry instead of preserving it. Per CLAUDE.md 39 SDK classes round-trip through
`__getstate__`/`__setstate__`, so "invisible to a state walk" is a live
property, not a stylistic one.
"""
from engine.appc.subsystems import ShieldSubsystem, SHIELD_CHARGE_PERIOD_S


def test_charge_accum_exists_on_a_fresh_instance():
    s = ShieldSubsystem("shields")
    assert "_charge_accum" in vars(s)
    assert s._charge_accum == 0.0


def test_charge_accum_survives_a_dict_state_round_trip():
    """The round trip a __getstate__/__setstate__ pair performs, on an
    instance that has NOT ticked yet. A `__dict__`-walking save of a
    just-constructed generator has to carry the field, or a restore lands on
    an object where the attribute is missing again."""
    s = ShieldSubsystem("shields")

    state = dict(vars(s))
    restored = ShieldSubsystem.__new__(ShieldSubsystem)
    vars(restored).update(state)

    assert "_charge_accum" in vars(restored)
    assert restored._charge_accum == s._charge_accum


def test_the_carry_is_what_crosses_the_cadence_threshold():
    """Guards the test above from being vacuous: the accumulator has to be the
    thing that decides when the 0.5 s tick fires."""
    s = ShieldSubsystem("shields")
    s.SetMaxShields(0, 100.0)
    s.SetCurrentShields(0, 0.0)
    s.SetShieldChargePerSecond(0, 10.0)

    half = SHIELD_CHARGE_PERIOD_S * 0.5
    s.Update(half)
    assert s.GetCurrentShields(0) == 0.0        # still banking
    s.Update(half)
    assert s.GetCurrentShields(0) > 0.0         # threshold crossed
    assert s._charge_accum == 0.0               # and the carry was consumed
