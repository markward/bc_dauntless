"""A mission swap mid-dash must not leave the dash VFX held at full.

The dash's intensity only ramps down from its drop-out; a swap tears the
player down with no drop-out, so without a reset the dust smear cap and the
nacelle glow would stay at the dash's full intensity in the next mission.
Drives the REAL HostController._drain_pending_swap (tests/unit/
test_dof_mission_swap.py's pattern)."""
from engine import dash_vfx


def _swap():
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


def test_a_mission_swap_mid_dash_drops_the_dash_vfx():
    vfx = dash_vfx.get()
    vfx.engage(0.0)
    vfx.tick(5.0)
    assert vfx.dash_intensity() == 1.0
    _swap()
    vfx.tick(5.0)
    assert vfx.dash_intensity() == 0.0
    assert vfx.flash_intensity() == 0.0
