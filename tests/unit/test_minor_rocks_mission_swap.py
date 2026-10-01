"""A mission swap drops every minor cloud (minor-rocks spec §1): the registry
forgets its clouds AND native is cleared, so the next mission's reconcile
re-adds from nothing (and re-pushes the fragment tables minors_clear wiped).
Drives the REAL HostController._drain_pending_swap
(tests/unit/test_dash_mission_swap.py's pattern)."""
import inspect

from engine.rocks import minors


def _swap(renderer):
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    h = HostController()
    h.renderer = renderer
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()


def test_a_mission_swap_clears_the_minor_registry_and_native():
    cleared = []

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass
        def minors_clear(self):
            cleared.append(1)

    minors.register_free_cloud(minors.FreeCloudSpec(
        "Rock", None, (0, 0, 0), (0, 0, 0), 0.0, "silicate", (), 4.0))
    minors._ids["halo:Old"] = 3
    _swap(_FakeRenderer())
    assert cleared == [1]
    assert minors.native_ids() == {}
    assert minors._pending_free == []


def test_boot_registers_the_minor_dial_group_beside_the_nebula_dials():
    from engine import host_loop
    src = inspect.getsource(host_loop.run)
    neb = src.find("dev_nebula_dials.register(_h)")
    mnr = src.find("_minor_dials.register()")
    assert neb >= 0 and mnr >= 0
    assert 0 < mnr - neb < 400, "register the minors group beside the nebula's"
