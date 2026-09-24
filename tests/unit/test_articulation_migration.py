"""The move from hardcoded dicts to authored templates stays done.

The migration's VALUE tests (pivots, axes, angle signs, warp == cruise, 20%
shear) used to live here and read the real hardpoint_overrides.py. That file
is authored data the SPV rewrites, so those tests broke on every legitimate
edit. The migrated numbers are now frozen in conftest.bop_fixture_rig, which
the mechanism tests run against, and the real file is checked for invariants
only by test_authored_part_data.py.
"""
from engine.appc import articulation


def test_the_hardcoded_dicts_are_GONE():
    """The whole point of the migration. Leaving them would give two sources
    of truth that silently disagree."""
    assert not hasattr(articulation, "_RIGS")
    assert not hasattr(articulation, "PART_BOXES")
    assert not hasattr(articulation, "DETACHABLE")
