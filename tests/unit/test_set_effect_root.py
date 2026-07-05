# tests/unit/test_set_effect_root.py
"""SetClass.GetEffectRoot returns a real per-set SetEffectRoot handle.

Previously GetEffectRoot fell through SetClass.__getattr__ to a fresh
_RendererStub per call, so E1M2's asteroid-death debris (E1M2.py:3111/3114)
parented its particle controllers to a throwaway stub. The SDK contract
(App.py:3536, all 9 call sites) is a stable NiNodePtr per set whose only
downstream use is controller.AttachEffect(root).
"""
from engine.appc import particles as P
from engine.appc.sets import SetClass, SetEffectRoot, _RendererStub


def _make_set(name="TestSet"):
    s = SetClass()
    s.SetName(name)
    return s


def test_effect_root_is_stable_per_set():
    pSet = _make_set()
    assert pSet.GetEffectRoot() is pSet.GetEffectRoot()


def test_effect_root_distinct_per_set_with_backref():
    a, b = _make_set("Alpha"), _make_set("Beta")
    ra, rb = a.GetEffectRoot(), b.GetEffectRoot()
    assert ra is not rb
    assert ra.GetSet() is a
    assert rb.GetSet() is b
    assert ra
    assert "Alpha" in repr(ra)


def test_effect_root_is_not_the_renderer_stub():
    root = _make_set().GetEffectRoot()
    assert isinstance(root, SetEffectRoot)
    assert not isinstance(root, _RendererStub)
    # No permissive __getattr__: the Effects.py:691 DeathExplosionDamage
    # guard `hasattr(pEmitPos, "INVALID")` style probe must stay False.
    assert not hasattr(root, "INVALID")


def test_debris_explosion_attaches_to_real_root():
    """The E1M2 asteroid-death path: CreateDebrisExplosion parents its
    controller to pSet.GetEffectRoot() via AttachEffect."""
    import Effects

    P.reset()
    pSet = _make_set()
    action = Effects.CreateDebrisExplosion(10.0, 1.5, (1.0, 2.0, 3.0), 1,
                                           pSet.GetEffectRoot())
    action.Start()
    controller = action.GetController()
    assert controller in P._active
    assert controller._attach_node is pSet.GetEffectRoot()
    assert isinstance(controller._attach_node, SetEffectRoot)


def test_getattr_fallback_survives_for_other_renderer_methods():
    pSet = _make_set()
    # Any still-undefined renderer method keeps the chainable stub behaviour.
    result = pSet.SomeUndefinedRendererMethod("x")
    assert isinstance(result, _RendererStub)
