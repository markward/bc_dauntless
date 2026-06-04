"""Bug E regression: ship render scale is the flat ``BC_MODEL_SCALE``,
NOT ``ship.GetRadius() / NIF_extent``.

The previous derivation assumed BC scaled each ship class to its
gameplay GetRadius value.  In fact BC stores a single NIF→world
constant (``ModelScale = 0.01`` in MPE's registry file) and treats
GetRadius as a *gameplay* value (splash radius, AI threat range).
The bogus ``NIF_TO_WORLD = 4.3665 / 403.258`` constant was a one-class
calibration that happened to be close to the truth because Galaxy's
MPE-authored GetRadius coincidentally landed near 0.01 × the NIF
extent.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug E" for the full investigation.
"""
import importlib

from engine import host_loop


def test_bc_model_scale_constant_is_flat_zero_zero_one():
    """MPE's registry-stored preview scale is exactly 0.01."""
    assert host_loop.BC_MODEL_SCALE == 0.01


def test_nif_to_world_constant_removed():
    """Confirms the bogus calibration constant has been retired so a
    re-import can't accidentally reintroduce a per-class divergence."""
    importlib.reload(host_loop)
    assert not hasattr(host_loop, "NIF_TO_WORLD")


def test_mission_session_drops_per_ship_scale_cache():
    """ships no longer carry a per-object natural_scale — BC_MODEL_SCALE
    is constant across the entire scene."""
    sess = host_loop.MissionSession("test")
    assert not hasattr(sess, "ship_natural_scale")
    # Planets still use a per-object cache because their radii vary
    # widely across mission scenes.
    assert hasattr(sess, "planet_natural_scale")
