"""The per-test reset must leave no module split between sys.modules and its
parent package's attribute, and must clear the dash's module globals.

Several fixtures swap Bridge.HelmMenuHandlers for a fresh import
(``sys.modules.pop`` -> ``import Bridge.HelmMenuHandlers`` -> restore the
saved entry). The restore puts the OLD module back in sys.modules but leaves
the ``Bridge`` package attribute on the NEW one. Code that imports it binds
the new module and runs CreateMenus on it, while the event manager resolves
the SDK's string handlers ("Bridge.HelmMenuHandlers.ObjectEnteredSet")
through sys.modules -- the old module, whose g_dCommandableFleet was never
set: NameError in every later mission test (the in-system-warp E2E, run
after tests/unit/test_dash_set_course.py). Two tests, ordered by name, stand
in for that pair here."""
import sys


def test_a_leaves_a_swapped_module_split_like_a_fixture_restore():
    import Bridge.HelmMenuHandlers  # noqa: F401
    saved = sys.modules.pop("Bridge.HelmMenuHandlers")
    import Bridge.HelmMenuHandlers as fresh
    sys.modules["Bridge.HelmMenuHandlers"] = saved
    assert sys.modules["Bridge"].HelmMenuHandlers is fresh is not saved

    from engine import dash_vfx
    from engine.appc import dash_helm
    dash_vfx.get().engage(0.0)
    dash_helm._cache = ("Helm", [], object())


def test_b_sees_the_package_attribute_resynced_and_the_dash_reset():
    import Bridge
    assert Bridge.HelmMenuHandlers is sys.modules["Bridge.HelmMenuHandlers"], (
        "conftest._reset_leakable_engine_globals leaves a swapped module's "
        "package attribute pointing at a different module than sys.modules")
    from engine import dash_vfx
    from engine.appc import dash_helm
    dash_vfx.get().tick(10.0)
    assert dash_vfx.get().dash_intensity() == 0.0, "dash_vfx not reset"
    assert dash_helm._cache is None, "dash_helm._cache not reset"
