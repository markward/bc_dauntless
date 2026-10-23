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


def test_record_remembers_the_attached_names_per_leaf():
    attach_templates.record("zzleaf", [App.BlinkingLightProperty_Create("Port"),
                                       App.BlinkingLightProperty_Create("Star")])
    attach_templates.record("zzother", [])
    try:
        assert attach_templates.attached_names("zzleaf") == {"Port", "Star"}
        assert attach_templates.attached_names("zzother") == set()
        assert attach_templates.attached_names("zznever") == set()
        # The next exec of the leaf replaces, never accumulates.
        attach_templates.record("zzleaf", [App.BlinkingLightProperty_Create("Keel")])
        assert attach_templates.attached_names("zzleaf") == {"Keel"}
        # A copy: the caller cannot edit the record.
        attach_templates.attached_names("zzleaf").add("X")
        assert attach_templates.attached_names("zzleaf") == {"Keel"}
    finally:
        attach_templates.record("zzleaf", [])
        attach_templates.record("zzother", [])


def test_leak_probe_1_records_without_cleanup():
    """Leaves a record behind on purpose: the conftest autouse reset must
    clear it before the next test (probe 2)."""
    attach_templates.record("zzleakleaf", [App.BlinkingLightProperty_Create("Port")])
    assert attach_templates.attached_names("zzleakleaf") == {"Port"}


def test_leak_probe_2_starts_with_no_records():
    assert attach_templates.attached_names("zzleakleaf") == set()
    assert attach_templates._attached == {}


def test_sdk_hook_records_the_queued_names_for_the_leaf():
    from engine.appc import sdk_overrides

    class M:
        @staticmethod
        def LoadPropertySet(pObj):
            pass
    attach_templates.queue(App.BlinkingLightProperty_Create("Port"))
    sdk_overrides.on_sdk_module_exec(M, "ships.Hardpoints.zzhookleaf")
    try:
        assert attach_templates.attached_names("zzhookleaf") == {"Port"}
        # A later exec that queues nothing clears the leaf's record.
        sdk_overrides.on_sdk_module_exec(M, "ships.Hardpoints.zzhookleaf")
        assert attach_templates.attached_names("zzhookleaf") == set()
    finally:
        attach_templates.record("zzhookleaf", [])
