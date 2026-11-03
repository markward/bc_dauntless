"""ObjectClass.IsTypeOf — SDK runtime class check (pObject.IsTypeOf(CT_X)).

CT_ constants are Python classes (CT_PLANET=Planet, CT_SUN=Sun). Sun(Planet),
so GetClassObjectList(CT_PLANET) returns planets AND suns and BC filters suns
back out with IsTypeOf(CT_SUN) — the check that empties/populates the Helm
"Orbit Planet" menu (HelmMenuHandlers.SetupOrbitMenuFromSet).
"""
import App
from engine.appc.objects import ObjectClass
from engine.appc.planet import Planet, Sun, Planet_Create, Sun_Create


def test_plain_planet_is_not_a_sun():
    p = Planet_Create(200.0, "colony.nif")
    assert p.IsTypeOf(App.CT_SUN) == 0


def test_sun_is_a_sun():
    s = Sun_Create(2000.0, 2000, 500)
    assert s.IsTypeOf(App.CT_SUN) == 1


def test_sun_is_also_a_planet():
    """Sun(Planet): a Sun matches CT_PLANET too (why GetClassObjectList(CT_PLANET)
    returns suns and BC must filter them with IsTypeOf(CT_SUN))."""
    s = Sun_Create(2000.0, 2000, 500)
    assert s.IsTypeOf(App.CT_PLANET) == 1


def test_planet_is_a_planet():
    p = Planet_Create(200.0, "colony.nif")
    assert p.IsTypeOf(App.CT_PLANET) == 1


def test_non_class_argument_returns_zero():
    """A fall-through _NamedStub for an unmapped CT_ (or any non-class) must
    return 0, not raise from isinstance(self, <non-class>)."""
    p = Planet_Create(200.0, "colony.nif")
    assert p.IsTypeOf(5) == 0
    fake_ct = App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST
    assert isinstance(fake_ct, App._NamedStub)
    assert p.IsTypeOf(fake_ct) == 0


def test_base_object_class_gets_the_method():
    """IsTypeOf lives on ObjectClass, so bare objects answer too."""
    o = ObjectClass()
    assert o.IsTypeOf(App.CT_OBJECT) == 1
    assert o.IsTypeOf(App.CT_PLANET) == 0


# ── cached IsTypeOf (native proximity phase 1, task 2) ──────────────────────

from engine.appc import object_types


def test_istypeof_matches_resolve_class_for_every_registered_tag():
    from engine.appc.ships import ShipClass
    objs = [Planet_Create(200.0, "colony.nif"), Sun_Create(2000.0, 2000, 500),
            ObjectClass(), ShipClass()]
    for obj in objs:
        for tag in object_types.registered_tags():
            want = 1 if isinstance(obj, object_types.class_for(tag)) else 0
            assert obj.IsTypeOf(tag) == want
            assert obj.IsTypeOf(tag) == want  # second call hits the cache


def test_istypeof_sees_a_class_registered_after_the_first_call():
    o = ObjectClass()
    tag = 987654
    assert o.IsTypeOf(tag) == 0
    saved = dict(object_types._BY_TAG), dict(object_types._BY_CLASS)
    try:
        object_types.register(tag, type(o))
        assert o.IsTypeOf(tag) == 1
    finally:
        object_types._BY_TAG.clear(); object_types._BY_TAG.update(saved[0])
        object_types._BY_CLASS.clear(); object_types._BY_CLASS.update(saved[1])
        object_types._GENERATION += 1


def test_istypeof_accepts_a_class_argument():
    s = Sun_Create(2000.0, 2000, 500)
    assert s.IsTypeOf(Planet) == 1
    assert Planet_Create(200.0, "c.nif").IsTypeOf(Sun) == 0


def test_istypeof_bool_and_named_stub_answer_zero():
    o = ObjectClass()
    assert o.IsTypeOf(True) == 0
    assert o.IsTypeOf(False) == 0
    assert o.IsTypeOf(App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST) == 0


def test_istypeof_unhashable_argument_falls_back_uncached():
    assert ObjectClass().IsTypeOf([1, 2]) == 0
    assert ObjectClass().IsTypeOf({}) == 0


def test_istypeof_keys_by_runtime_type():
    class A(ObjectClass):
        pass
    class B(A):
        pass
    a = A()
    assert a.IsTypeOf(A) == 1 and a.IsTypeOf(B) == 0
    a.__class__ = B  # reclassify at runtime
    assert a.IsTypeOf(B) == 1


def test_object_types_generation_increases_on_register():
    g = object_types.generation()
    tag = 987655
    saved = dict(object_types._BY_TAG), dict(object_types._BY_CLASS)
    try:
        object_types.register(tag, ObjectClass)
        assert object_types.generation() > g
    finally:
        object_types._BY_TAG.clear(); object_types._BY_TAG.update(saved[0])
        object_types._BY_CLASS.clear(); object_types._BY_CLASS.update(saved[1])
        object_types._GENERATION += 1


def test_istypeof_int_float_bool_do_not_share_cache_entries():
    from engine.appc import objects
    tag = object_types.tag_for(ObjectClass)
    for order in ((tag, float(tag)), (float(tag), tag)):
        objects._ISTYPEOF_CACHE.clear()
        got = {}
        for a in order:
            got[type(a)] = ObjectClass().IsTypeOf(a)
        assert got[int] == 1 and got[float] == 0
    objects._ISTYPEOF_CACHE.clear()
    assert ObjectClass().IsTypeOf(1) == ObjectClass().IsTypeOf(1)
    one = ObjectClass().IsTypeOf(True)
    assert one == 0


def test_istypeof_fresh_named_stubs_do_not_grow_the_cache():
    from engine.appc import objects
    o = ObjectClass()
    o.IsTypeOf(ObjectClass)  # prime the generation
    n = len(objects._ISTYPEOF_CACHE)
    for _ in range(5):
        assert o.IsTypeOf(App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST) == 0
    assert len(objects._ISTYPEOF_CACHE) == n
