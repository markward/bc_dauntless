"""``App.UtopiaModule_ConvertGameUnitsToKilometers`` — BC's one display-boundary
unit conversion.

It was never bound, so it resolved to a truthy ``App._NamedStub`` whose ``int()``
coerces to 0. That is silent by construction, and it made BC's helm tooltip
useless: BridgeHandlers.py:1389 builds the line as

    fVel = App.UtopiaModule_ConvertGameUnitsToKilometers(
               pShip.GetVelocity().Length()) * 3600.0
    fImp = pShip.GetImpulse() * 9 + 0.1
    pcLine = str(int(fImp)) + " : " + str(int(fVel)) + " " + "kph"

so ``int(fVel)`` was ALWAYS 0 and the officer tooltip always read "N : 0 kph"
however fast the ship was going. Live telemetry had it at docs/stub_heatmap.md
rank 63, 256 hits over 23/233 runs.

It cost real diagnostic time too: undocking from Starbase 12, the tooltip read
"2 : 0 kph" and was taken as evidence the ship was not moving, when the ship was
fine and only the readout was dead.

The factor is not a guess. engine/units.py was derived FROM this call site: a
Galaxy's ``SetMaxSpeed(6.3)`` GU/s is displayed as 3969 kph by stock BC, so
ConvertGameUnitsToKilometers(6.3) must be 1.1025 km, i.e. 1 GU = 175 m.
"""
import App
import pytest

from engine.units import GU_TO_KM

_convert = App.UtopiaModule_ConvertGameUnitsToKilometers


def test_is_a_real_function_not_a_named_stub():
    """The whole bug class: a _NamedStub is truthy and callable, so the call
    site never errors — it just silently yields 0 through int()."""
    assert not isinstance(_convert, App._NamedStub)
    assert isinstance(_convert(1.0), float)


def test_galaxy_max_speed_reads_3969_kph_as_in_stock_bc():
    """THE anchor value, and the one engine/units.py's factor was derived
    from. This is the exact arithmetic BridgeHandlers.py:1389 performs."""
    assert _convert(6.3) == pytest.approx(1.1025)
    assert int(_convert(6.3) * 3600.0) == 3969


@pytest.mark.parametrize("gu, kph", [
    (6.3,  3969),   # Galaxy max impulse — the anchor
    (3.15, 1984),   # half impulse
    (1.4,   882),   # FlyForward's 2/9 impulse, the post-undock coast
    (0.7,   441),
])
def test_displayed_integer_matches_bc_through_the_sdks_truncation(gu, kph):
    """The SDK caller TRUNCATES — `str(int(fVel))` — so a last-bit rounding
    error one below the true value costs a whole displayed km/h. The obvious
    `gu * 0.175` gets 3 of these 4 wrong (3968/881/440). This pins the
    association order chosen in App.py; if that line is refactored on the
    assumption the algebra is equivalent, these fail."""
    assert int(_convert(gu) * 3600.0) == kph


def test_matches_the_engine_side_constant():
    """One factor, two consumers: SDK scripts go through this function, engine
    code through engine.units. They must not drift."""
    for gu in (0.0, 1.4, 6.3, 250.0):
        assert _convert(gu) == pytest.approx(gu * GU_TO_KM)


def test_zero_converts_to_zero():
    assert _convert(0.0) == 0.0


def test_a_moving_ship_no_longer_reads_zero_kph():
    """Regression guard shaped like the defect: under the stub EVERY speed
    formatted as 0. FlyForward's 2/9 impulse on a Galaxy is 1.4 GU/s."""
    assert int(_convert(1.4) * 3600.0) == 882
    assert int(_convert(1.4) * 3600.0) != 0
