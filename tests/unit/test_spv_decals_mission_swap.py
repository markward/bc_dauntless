"""A mission swap must drop the SPV's live decal override BEFORE the session
(and the instance the override is keyed on) is torn down.

Drives the REAL HostController._drain_pending_swap (tests/unit/
test_dash_mission_swap.py's pattern): the host registers the panel's
`on_mission_swap` in `pre_swap_hooks`."""


def test_pre_swap_hooks_run_before_the_session_teardown():
    from engine.host_loop import HostController, MissionSession

    order = []

    class _StubLoader:
        def load(self, name):
            order.append("load")
            return MissionSession(mission_name=name)

    class _Session(MissionSession):
        def teardown(self, renderer):
            order.append("teardown")

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = _Session(mission_name="prev")
    h.pre_swap_hooks.append(lambda: order.append("hook"))
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()

    assert order == ["hook", "teardown", "load"]


def test_a_raising_pre_swap_hook_does_not_block_the_swap():
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    h = HostController()
    h.loader = _StubLoader()

    def _boom():
        raise RuntimeError("boom")
    h.pre_swap_hooks.append(_boom)
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()

    assert h.session is not None and h.session.mission_name == "Next.Mission"
