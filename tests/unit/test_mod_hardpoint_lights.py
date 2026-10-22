"""Running-light edits land in the mod hardpoint's managed block, never in the
author's own text (spec 2026-10-22 4.2-4.3). Fixture text is synthetic."""
import sys
import types

import pytest

import App
from engine.appc import attach_templates
from engine.appc import mod_hardpoint_writer as mw
from engine.appc.properties import TGModelPropertySet

SRC = '''import App

NavA = App.BlinkingLightProperty_Create("Nav A")
NavA.SetPosition(1.000000, 2.000000, 3.000000)
NavAColor = App.TGColorA()
NavAColor.SetRGBA(0.100000, 0.200000, 0.300000, 1.0)
NavA.SetColor(NavAColor)
NavA.SetRadius(0.500000)
App.g_kModelPropertyManager.RegisterLocalTemplate(NavA)

NavB = App.BlinkingLightProperty_Create("Nav B")
NavB.SetPosition(-1.000000, 2.000000, 3.000000)
NavB.SetRadius(0.500000)
App.g_kModelPropertyManager.RegisterLocalTemplate(NavB)

def LoadPropertySet(pObj):
    prop = App.g_kModelPropertyManager.FindByName("Nav A", App.TGModelPropertyManager.LOCAL_TEMPLATES)
    if (prop != None):
        pObj.AddToSet("Scene Root", prop)
    prop = App.g_kModelPropertyManager.FindByName("Nav B", App.TGModelPropertyManager.LOCAL_TEMPLATES)
    if (prop != None):
        pObj.AddToSet("Scene Root", prop)
'''

NEW = {"name": "Nav C", "position": (4.0, 5.0, 6.0), "color": (1.0, 0.5, 0.25),
       "radius": 2.0, "period": 3.0, "duration": 0.5}


def _edit(name, spec, new):
    return (name, "__running_light__", {"spec": spec, "new": new})


@pytest.fixture(autouse=True)
def _clean():
    attach_templates.drain()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    yield
    attach_templates.drain()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _load(text):
    """Exec the file as a hardpoint module, then do what the SDK hook does
    (drain + wrap) and run its LoadPropertySet. Returns {name: prop}."""
    mod = types.ModuleType("ships.Hardpoints.synth")
    exec(compile(text, "synth.py", "exec"), mod.__dict__)
    attach_templates.wrap_load_property_set(mod, attach_templates.drain())
    pset = TGModelPropertySet()
    mod.LoadPropertySet(pset)
    return dict((p.GetName(), p) for p in
                pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY))


def test_add_light_goes_to_block_and_loads():
    out = mw.rewrite(SRC, "synth", [_edit("Nav C", dict(NEW), True)])
    author, block = mw.split_block(out)
    assert author == SRC and "Nav C" in block
    lights = _load(out)
    assert sorted(lights) == ["Nav A", "Nav B", "Nav C"]
    assert lights["Nav C"].GetRadius() == 2.0


def test_remove_mod_light_absent_after_load():
    out = mw.rewrite(SRC, "synth", [_edit("Nav B", None, False)])
    assert sorted(_load(out)) == ["Nav A"]


def test_edit_mod_light_colour_and_position():
    spec = dict(NEW, name="Nav A", position=(9.0, 8.0, 7.0), color=(0.9, 0.8, 0.7))
    out = mw.rewrite(SRC, "synth", [_edit("Nav A", spec, False)])
    p = _load(out)["Nav A"]
    pos = p.GetPosition()
    assert (pos.x, pos.y, pos.z) == (9.0, 8.0, 7.0)
    c = p.GetColor()
    assert (c.r, c.g, c.b) == (0.9, 0.8, 0.7)


def test_author_lines_untouched():
    out = mw.rewrite(SRC, "synth", [_edit("Nav A", None, False),
                                    _edit("Nav C", dict(NEW), True)])
    assert mw.split_block(out)[0] == SRC
    assert mw.rewrite(out, "synth", []) == out


def test_stock_bc_skips_light_blocks():
    out = mw.rewrite(SRC, "synth", [_edit("Nav C", dict(NEW), True),
                                    _edit("Nav A", None, False)])

    class Prop:
        def __getattr__(self, _n):
            return lambda *a, **k: None

    class StockApp:
        created = []

        class g_kModelPropertyManager:
            @staticmethod
            def RegisterLocalTemplate(p): pass

            @staticmethod
            def FindByName(*a): return None

        class TGModelPropertyManager:
            LOCAL_TEMPLATES = 0

        @classmethod
        def BlinkingLightProperty_Create(cls, name):
            cls.created.append(name)
            return Prop()

        @staticmethod
        def TGColorA(): return Prop()

    prev = sys.modules.get("App")
    sys.modules["App"] = StockApp
    try:
        exec(compile(out, "synth.py", "exec"), {"__name__": "synth"})
    finally:
        sys.modules["App"] = prev
    assert StockApp.created == ["Nav A", "Nav B"]   # the author's own only


def test_non_finite_light_spec_rejected():
    with pytest.raises(ValueError):
        mw.rewrite(SRC, "synth", [_edit("Nav C", dict(NEW, radius=float("nan")), True)])
