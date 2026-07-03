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
