"""BC's damage-geometry switches must not survive a mission swap.

`damage_geometry._state` is module-level and lives for the whole process.
`_drain_pending_swap` explicitly resets ~20 other module-level states for
exactly this reason -- a mission that disables damage geometry for a cutscene
(E3M1.py:3001-3003 does exactly this) must not leave it off for whatever
mission is swapped in next. `damage_geometry.reset()` existed
(`engine/appc/damage_geometry.py:49` even says "For test isolation and
mission swaps" in its docstring) but was only ever called from
`tests/conftest.py` -- never from the actual mission-swap path.
"""
from engine.appc import damage_geometry


def _swap(controller_module=None):
    """Drive the REAL _drain_pending_swap, not a re-run of its body, so
    deleting the reset line from the production block fails this test."""
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    return h


def test_mission_swap_restores_damage_geometry_defaults():
    damage_geometry.set_damage_geometry_enabled(0)
    damage_geometry.set_volume_damage_geometry_enabled(0)
    damage_geometry.set_breakable_components_enabled(0)
    assert damage_geometry.is_damage_geometry_enabled() == 0
    assert damage_geometry.is_volume_damage_geometry_enabled() == 0
    assert damage_geometry.is_breakable_components_enabled() == 0

    _swap()

    assert damage_geometry.is_damage_geometry_enabled() == 1
    assert damage_geometry.is_volume_damage_geometry_enabled() == 1
    assert damage_geometry.is_breakable_components_enabled() == 1
