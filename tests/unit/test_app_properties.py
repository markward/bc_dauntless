import App
from engine.appc.properties import (
    TGModelPropertyManager, ShieldProperty, HullProperty,
)


def test_app_exposes_real_manager():
    assert isinstance(App.g_kModelPropertyManager, TGModelPropertyManager)


def test_app_exposes_factories():
    p = App.ShieldProperty_Create("Shield Generator")
    assert isinstance(p, ShieldProperty)
    assert p.GetName() == "Shield Generator"


def test_app_exposes_class_constants():
    assert App.TGModelPropertyManager.LOCAL_TEMPLATES == 0
    assert App.ShieldProperty.FRONT_SHIELDS == 0
    assert App.WeaponSystemProperty.WST_TORPEDO == 2


def test_round_trip_through_app_namespace():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    hull = App.HullProperty_Create("Hull")
    hull.SetMaxCondition(7000.0)
    App.g_kModelPropertyManager.RegisterLocalTemplate(hull)
    found = App.g_kModelPropertyManager.FindByName(
        "Hull", App.TGModelPropertyManager.LOCAL_TEMPLATES
    )
    assert found is hull
    assert found.GetMaxCondition() == 7000.0
    App.g_kModelPropertyManager.ClearLocalTemplates()
