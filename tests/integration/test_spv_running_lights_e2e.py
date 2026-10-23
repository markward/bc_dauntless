"""SPV running lights end to end through the real loader hook (spec
docs/superpowers/specs/2026-10-22-spv-running-lights-design.md S6, S3.7, S4.1).

A light created in the SPV is saved by the real stock writer
(`HardpointOverridesFileTarget`, pointed at a COPY of the overrides file),
which refreshes the live `hardpoint_overrides` module in place. The next
real `loadspacehelper.CreateShip("Galaxy")` -- SDK hardpoint exec, the
`sdk_overrides` hook, the attach queue, `LoadPropertySet` -- must carry the
light with its look and physical parent, and a different class must not.

The real overrides file is never written, and the live module's OVERRIDES
are restored in a `finally` whatever happens."""
import shutil

import pytest

import App
import tools.mission_harness as mh
from engine.appc import hardpoint_overrides, override_routing, running_lights

_SPEC = {"position": (1.0, 2.0, 0.5), "color": (1.0, 0.0, 0.0),
         "radius": 1.25, "period": 3.0, "duration": 0.5}


def _reset_sets():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    mh.setup_sdk()
    _reset_sets()
    yield
    _reset_sets()


def _create(cls, name):
    import loadspacehelper
    pset = App.SetClass_Create()
    pset.SetName("S")
    App.g_kSetManager._sets["S"] = pset
    return loadspacehelper.CreateShip(cls, pset, name, None, 0, 0)


def test_saved_light_reaches_the_next_galaxy_only(tmp_path):
    real = override_routing._PATH
    with open(real, "rb") as fh:
        real_bytes = fh.read()
    copy = tmp_path / "hardpoint_overrides.py"
    shutil.copy(real, copy)
    saved_overrides = hardpoint_overrides.OVERRIDES
    try:
        before = _create("Galaxy", "Before")
        assert "Port Nav" not in [s.name for s in
                                  running_lights.lights_for(before)]

        target = override_routing.HardpointOverridesFileTarget(
            str(copy), live_module=hardpoint_overrides)
        target.write("galaxy", [
            ("Port Nav", "__running_light__", {"spec": _SPEC, "new": True}),
            ("Port Nav", "SetPhysicalParent", ("saucer",)),
        ])

        galaxy = _create("Galaxy", "After")
        lights = {s.name: s for s in running_lights.lights_for(galaxy)}
        assert "Port Nav" in lights
        light = lights["Port Nav"]
        assert light.pos == pytest.approx(_SPEC["position"])
        assert light.rgb == pytest.approx(_SPEC["color"])
        assert light.size == pytest.approx(_SPEC["radius"])
        assert light.period == pytest.approx(_SPEC["period"])
        assert light.duration == pytest.approx(_SPEC["duration"])
        assert light.physical_parent == "saucer"

        sovereign = _create("Sovereign", "Other")
        assert running_lights.lights_for(sovereign) == []
    finally:
        hardpoint_overrides.OVERRIDES = saved_overrides
    assert hardpoint_overrides.OVERRIDES is saved_overrides
    with open(real, "rb") as fh:
        assert fh.read() == real_bytes


def test_created_light_is_renameable_and_renames_through_the_loader(tmp_path):
    """The attach queue records the created light for the leaf (what makes
    it renameable in the SPV); a saved rename reaches the next build under
    the new name, its physical parent with it."""
    from engine.appc import attach_templates
    real = override_routing._PATH
    with open(real, "rb") as fh:
        real_bytes = fh.read()
    copy = tmp_path / "hardpoint_overrides.py"
    shutil.copy(real, copy)
    saved_overrides = hardpoint_overrides.OVERRIDES
    try:
        target = override_routing.HardpointOverridesFileTarget(
            str(copy), live_module=hardpoint_overrides)
        target.write("galaxy", [
            ("Zz Rename Nav", "__running_light__", {"spec": _SPEC, "new": True}),
            ("Zz Rename Nav", "SetPhysicalParent", ("saucer",)),
        ])
        _create("Galaxy", "Before")
        assert "Zz Rename Nav" in attach_templates.attached_names("galaxy")
        target.write("galaxy", [
            ("Zz Rename Nav", "__rename_light__", "Zz Renamed Nav")])
        galaxy = _create("Galaxy", "After")
        lights = {s.name: s for s in running_lights.lights_for(galaxy)}
        assert "Zz Rename Nav" not in lights
        assert lights["Zz Renamed Nav"].physical_parent == "saucer"
        assert lights["Zz Renamed Nav"].pos == pytest.approx(_SPEC["position"])
        assert "Zz Renamed Nav" in attach_templates.attached_names("galaxy")
        assert "Zz Rename Nav" not in attach_templates.attached_names("galaxy")
    finally:
        hardpoint_overrides.OVERRIDES = saved_overrides
    with open(real, "rb") as fh:
        assert fh.read() == real_bytes
