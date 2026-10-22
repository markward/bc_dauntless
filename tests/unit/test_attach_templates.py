"""engine.appc.attach_templates: attach queue for Dauntless-created hardpoint
templates (running-lights spec 2026-10-22 section 4.1)."""
import importlib
import sys

import App
from engine.appc import attach_templates
from engine.appc.properties import TGModelPropertySet


def setup_function(_f):
    attach_templates.drain()


def _module():
    class M:
        @staticmethod
        def LoadPropertySet(pObj):
            pObj.AddToSet("Scene Root", App.ShipProperty_Create("Hull"))
    return M


def _names(pset):
    return [p.GetName() for p in
            pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY)]


def test_queued_light_is_added_after_load_property_set():
    m = _module()
    attach_templates.queue(App.BlinkingLightProperty_Create("Port"))
    attach_templates.wrap_load_property_set(m, attach_templates.drain())
    pset = TGModelPropertySet()
    m.LoadPropertySet(pset)
    assert _names(pset) == ["Port"]


def test_drain_empties_queue():
    p = App.BlinkingLightProperty_Create("Port")
    attach_templates.queue(p)
    assert attach_templates.drain() == [p]
    assert attach_templates.drain() == []


def test_unqueued_registered_template_is_not_attached():
    m = _module()
    App.g_kModelPropertyManager.RegisterLocalTemplate(
        App.BlinkingLightProperty_Create("Strobe"))
    attach_templates.queue(App.BlinkingLightProperty_Create("Port"))
    attach_templates.wrap_load_property_set(m, attach_templates.drain())
    pset = TGModelPropertySet()
    m.LoadPropertySet(pset)
    App.g_kModelPropertyManager.ClearLocalTemplates()
    assert _names(pset) == ["Port"]


def test_already_present_prop_not_added_twice():
    p = App.BlinkingLightProperty_Create("Port")

    class M:
        @staticmethod
        def LoadPropertySet(pObj):
            pObj.AddToSet("Scene Root", p)
    attach_templates.wrap_load_property_set(M, [p])
    pset = TGModelPropertySet()
    M.LoadPropertySet(pset)
    assert _names(pset) == ["Port"]


def test_dauntless_env_is_2():
    assert App.DAUNTLESS_ENV == 2
    assert App.DauntlessAttachTemplate is attach_templates.queue


def test_kessoklight_build_unchanged():
    import tools.mission_harness as mh
    mh.setup_sdk()
    sys.modules.pop("ships.Hardpoints.kessoklight", None)
    mod = importlib.import_module("ships.Hardpoints.kessoklight")
    pset = TGModelPropertySet()
    mod.LoadPropertySet(pset)
    assert _names(pset) == []
    assert len(list(pset.GetPropertyList())) > 0
