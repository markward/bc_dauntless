"""A saved mod hardpoint file loads the way a hardpoint file loads (exec with
the real App shim) and the edits reach the property templates; and the same
file runs under a stock-BC App without touching any Dauntless-only surface."""
import sys

import pytest

import App
import engine.appc.override_routing as r

SRC = ('import App\n'
       'PortWarp = App.EngineProperty_Create("Port Warp")\n'
       'PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)\n'
       'PortWarp.SetRadius(1.200000)\n'
       'App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)\n')

EDITS = [
    ("Port Warp", "SetPosition", (1.0, 2.0, 3.0)),
    ("Port Warp", "SetRadius", (0.5,)),
    ("Port Warp", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))]),
    ("wing", "__part__", [("SetTransitionSeconds", (2.0,))]),
]


@pytest.fixture
def saved(tmp_path):
    f = tmp_path / "refit.py"
    f.write_text(SRC)
    r.ModHardpointFileTarget(str(f)).write("refit", EDITS)
    return f.read_text()


@pytest.fixture
def clean_templates():
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    yield mgr
    mgr.ClearLocalTemplates()


def test_edits_reach_the_templates(saved, clean_templates):
    exec(compile(saved, "refit.py", "exec"), {"__name__": "refit"})
    scope = App.TGModelPropertyManager.LOCAL_TEMPLATES
    p = clean_templates.FindByName("Port Warp", scope)
    pos = p.GetPosition()
    assert (pos.x, pos.y, pos.z) == (1.0, 2.0, 3.0)
    assert p.GetRadius() == 0.5
    assert p.GetGlowRegionShape(0) == "Box"
    assert clean_templates.FindByName("wing", scope) is not None


class _StockProp:
    """Only the SDK surface a stock property has."""
    def __init__(self, name):
        self.name, self.calls = name, []
    def SetPosition(self, *a): self.calls.append(("SetPosition", a))
    def SetRadius(self, *a): self.calls.append(("SetRadius", a))


class _StockApp:
    created = []
    class g_kModelPropertyManager:
        @staticmethod
        def RegisterLocalTemplate(p): pass
    @classmethod
    def EngineProperty_Create(cls, name):
        p = _StockProp(name); cls.created.append(p); return p


def test_stock_bc_runs_the_file_and_applies_only_sdk_edits(saved):
    prev = sys.modules.get("App")
    sys.modules["App"] = _StockApp
    try:
        exec(compile(saved, "refit.py", "exec"), {"__name__": "refit"})   # must not raise
    finally:
        sys.modules["App"] = prev
    (p,) = _StockApp.created
    assert p.calls == [("SetPosition", (1.0, 2.0, 3.0)), ("SetRadius", (0.5,))]
