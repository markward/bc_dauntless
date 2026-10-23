import ast
import re
import types

import engine.appc.hardpoint_override_writer as w
from engine.appc import attach_templates

SPEC = {"position": (0.5, 1.0, -0.25), "color": (1.0, 0.25, 0.2),
        "radius": 1.0, "period": 3.0, "duration": 0.5}

CREATE_BLOCK = '''    if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 2:
        port_nav_light = App.BlinkingLightProperty_Create("Port Nav Light")
        port_nav_light.SetPosition(0.5, 1.0, -0.25)
        port_nav_light_color = App.TGColorA()
        port_nav_light_color.SetRGBA(1.0, 0.25, 0.2, 1.0)
        port_nav_light.SetColor(port_nav_light_color)
        port_nav_light.SetRadius(1.0)
        port_nav_light.SetPeriod(3.0)
        port_nav_light.SetDuration(0.5)
        App.g_kModelPropertyManager.RegisterLocalTemplate(port_nav_light)
        App.DauntlessAttachTemplate(port_nav_light)'''


def _create(models, name="Port Nav Light", spec=SPEC, leaf="galaxy"):
    w.apply_edit(models, leaf, (name, "__running_light__",
                                {"spec": dict(spec), "new": True}))


def test_create_light_emits_exact_block():
    m = {}
    _create(m)
    assert CREATE_BLOCK in w.emit(m)


def test_create_light_round_trips():
    m = {}
    _create(m)
    assert w.read_models_from_source(w.emit(m)) == m


def test_edit_light_emits_find_block_with_colour():
    m = {}
    w.apply_edit(m, "galaxy", ("Port Nav Light", "__running_light__",
                               {"spec": dict(SPEC), "new": False}))
    text = w.emit(m)
    assert '    p = find("Port Nav Light")' in text
    assert "App.TGColorA()" in text
    assert "c.SetRGBA(1.0, 0.25, 0.2, 1.0)" in text
    assert "p.SetColor(c)" in text
    assert "App.DAUNTLESS_ENV >= 2" in text
    assert w.read_models_from_source(text) == m


def test_remove_of_created_light_drops_entry():
    m = {}
    _create(m)
    w.apply_edit(m, "galaxy", ("Port Nav Light", "__running_light__",
                               {"spec": None, "new": False}))
    assert w._LIGHTS_KEY not in m["galaxy"]
    assert "Port Nav Light" not in w.emit(m)


def test_remove_of_existing_light_emits_remove_template():
    m = {}
    w.apply_edit(m, "galaxy", ("Port Nav Light", "__running_light__",
                               {"spec": None, "new": False}))
    text = w.emit(m)
    assert "RemoveTemplate(p)" in text
    assert w.read_models_from_source(text) == m


def test_create_blocks_precede_find_blocks():
    m = {}
    _create(m)
    w.apply_edit(m, "galaxy", ("Port Nav Light", "SetPhysicalParent", ("hull",)))
    lines = w.emit(m).splitlines()
    ci = next(i for i, l in enumerate(lines) if "BlinkingLightProperty_Create" in l)
    fi = next(i for i, l in enumerate(lines) if 'find("Port Nav Light")' in l)
    assert ci < fi


def test_light_name_is_quoted_and_identifier_safe():
    m = {}
    for n in ('Port "Nav"', "class", "Ünïcode", "a b", "a-b",
              "print", "exec"):
        _create(m, name=n)
    text = w.emit(m)
    ast.parse(text)
    for kw in ("print", "exec"):
        assert not re.search(r"^\s+%s = " % kw, text, re.M)
    assert w.read_models_from_source(text) == m
    assert "a_b_2" in text


def test_emitted_lights_are_py15_safe():
    m = {}
    _create(m)
    w.apply_edit(m, "galaxy", ("X", "__running_light__",
                               {"spec": dict(SPEC), "new": False}))
    w.apply_edit(m, "galaxy", ("Y", "__running_light__",
                               {"spec": None, "new": False}))
    text = w.emit(m)
    assert not re.search(r"\b(True|False)\b", text)
    assert not re.search(r"\bf[\"']", text)
    assert " as " not in text


def test_executing_emit_attaches_light():
    import App
    m = {}
    _create(m, leaf="zzlights")
    mod = types.ModuleType("_lights_exec")
    exec(compile(w.emit(m), "<x>", "exec"), mod.__dict__)
    attach_templates.drain()
    mod.apply("zzlights")
    q = attach_templates.drain()
    try:
        assert len(q) == 1
        p = q[0]
        c = p.GetColor()
        assert (c.r, c.g, c.b, c.a) == (1.0, 0.25, 0.2, 1.0)
        assert (p.GetRadius(), p.GetPeriod(), p.GetDuration()) == (1.0, 3.0, 0.5)
    finally:
        App.g_kModelPropertyManager.RemoveTemplate(q[0])


def _stable(m):
    first = w.emit(m)
    return w.emit(w.read_models_from_source(first)) == first


def test_emit_is_stable_with_mixed_edit_and_remove():
    m = {}
    w.apply_edit(m, "galaxy", ("A", "__running_light__",
                               {"spec": dict(SPEC), "new": False}))
    w.apply_edit(m, "galaxy", ("B", "__running_light__", {"spec": None, "new": False}))
    assert _stable(m)


def test_partial_spec_is_rejected():
    import pytest
    for new in (True, False):
        for drop in w._LIGHT_FIELDS:
            spec = dict(SPEC)
            del spec[drop]
            with pytest.raises(ValueError):
                w.apply_edit({}, "galaxy", ("X", "__running_light__",
                                            {"spec": spec, "new": new}))
    with pytest.raises(ValueError):
        w.apply_edit({}, "galaxy", ("X", "__running_light__",
                                    {"spec": dict(SPEC, radius=None), "new": True}))


def test_emit_is_stable_with_physical_parent_on_edited_light():
    m = {}
    for n in ("A", "B"):
        w.apply_edit(m, "galaxy", (n, "__running_light__",
                                   {"spec": dict(SPEC), "new": False}))
    w.apply_edit(m, "galaxy", ("B", "SetPhysicalParent", ("hull",)))
    assert _stable(m)


# --- renames (follow-up 2026-10-23) -----------------------------------------

def _rename(models, old, new, leaf="galaxy"):
    w.apply_edit(models, leaf, (old, "__rename_light__", new))


def test_rename_of_created_light_rekeys_it_and_its_physical_parent():
    m = {}
    _create(m, name="A")
    _create(m, name="B")
    w.apply_edit(m, "galaxy", ("A", "SetPhysicalParent", ("saucer",)))
    _rename(m, "A", "Renamed")
    lights = m["galaxy"][w._LIGHTS_KEY]
    assert list(lights) == ["Renamed", "B"]           # stable order
    assert lights["Renamed"]["op"] == "create"
    assert "A" not in m["galaxy"]
    assert m["galaxy"]["Renamed"] == [("SetPhysicalParent", ("saucer",))]
    text = w.emit(m)
    assert 'BlinkingLightProperty_Create("Renamed")' in text
    assert 'find("Renamed")' in text
    assert '"A"' not in text
    assert w.read_models_from_source(text) == m
    assert w.emit(w.read_models_from_source(text)) == text


def test_rename_onto_an_emptied_setter_list_keeps_the_moved_parent():
    """An unset earlier in the same write leaves `[]` under the new name,
    AFTER the old name in the dict: it must not overwrite the moved list."""
    m = {}
    _create(m, name="A")
    w.apply_edit(m, "galaxy", ("A", "SetPhysicalParent", ("saucer",)))
    w.apply_edit(m, "galaxy", ("B", "SetPhysicalParent", ("hull",)))
    w.apply_edit(m, "galaxy", ("B", "__unset__", "SetPhysicalParent"))
    assert m["galaxy"]["B"] == []
    _rename(m, "A", "B")
    assert m["galaxy"]["B"] == [("SetPhysicalParent", ("saucer",))]
    assert 'find("B")' in w.emit(m)


def test_rename_onto_an_existing_name_is_refused():
    import pytest
    for setup in (lambda m: _create(m, name="B"),
                  lambda m: w.apply_edit(m, "galaxy", ("B", "SetPhysicalParent", ("hull",))),
                  lambda m: w.apply_edit(m, "galaxy", ("B", "__running_light__",
                                                       {"spec": None, "new": False}))):
        m = {}
        _create(m, name="A")
        setup(m)
        before = w.emit(m)
        with pytest.raises(ValueError):
            _rename(m, "A", "B")
        assert w.emit(m) == before


def test_rename_of_a_non_created_light_is_refused():
    import pytest
    m = {}
    w.apply_edit(m, "galaxy", ("Strobe", "__running_light__",
                               {"spec": dict(SPEC), "new": False}))
    with pytest.raises(ValueError):
        _rename(m, "Strobe", "Renamed")
    with pytest.raises(ValueError):
        _rename(m, "Nowhere", "Renamed")
    assert "Renamed" not in m["galaxy"].get(w._LIGHTS_KEY, {})


def test_rename_then_edit_under_the_new_name_stays_a_create():
    m = {}
    _create(m, name="A")
    _rename(m, "A", "B")
    w.apply_edit(m, "galaxy", ("B", "__running_light__",
                               {"spec": dict(SPEC, radius=2.0), "new": False}))
    assert m["galaxy"][w._LIGHTS_KEY]["B"]["op"] == "create"
    assert m["galaxy"][w._LIGHTS_KEY]["B"]["radius"] == 2.0
