"""The Quick Battle setup screen is prewarmed while Quick Battle boots, so its
first open from the XO menu does not stall (1.5 s measured 2026-10-17)."""
import inspect


def test_prewarm_helper_runs_the_panel_prewarm():
    import engine.host_loop as hl
    calls = []

    class Panel:
        def prewarm(self):
            calls.append(1)
    hl._prewarm_quick_battle_panel(Panel())
    assert calls == [1]


def test_a_failing_prewarm_never_stops_boot():
    import engine.host_loop as hl

    class Panel:
        def prewarm(self):
            raise RuntimeError("broken mod hardpoint")
    hl._prewarm_quick_battle_panel(Panel())          # must not raise


def test_quickbattle_boot_prewarms_the_panel_after_constructing_it():
    import engine.host_loop as hl
    src = inspect.getsource(hl)
    i_built = src.index("controller.quick_battle_setup_panel = quick_battle_setup_panel")
    i_warm = src.index("_prewarm_quick_battle_panel(quick_battle_setup_panel)")
    assert i_built < i_warm
    guard = src.rindex("if boot_quickbattle:", 0, i_warm)
    assert guard > i_built, "prewarm only on the Quick Battle boot"
