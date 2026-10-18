"""Physical parents: the one answer to "which part is this property on"."""
import pytest

from engine.appc import articulation, part_severance, physical_parents as pp
from engine.appc.properties import TGModelProperty

_LEAF = "pptestleaf"
_BOXES = {"hull": ((0, 0, 0), (1, 1, 1)), "birdofprey": ((0, 0, 0), (1, 1, 1))}
_PT = (0.1, 0.2, 0.3)


@pytest.fixture
def auto(monkeypatch):
    calls = []

    def fake(leaf, point, iid=None):
        calls.append((leaf, point, iid))
        return "hull"

    monkeypatch.setattr(part_severance, "part_for_mount", fake)
    monkeypatch.setitem(articulation._derived_boxes, _LEAF, _BOXES)
    return calls


def _prop(name="Port Phaser", parent=None):
    p = TGModelProperty(name)
    p.SetPhysicalParent(parent)
    return p


def test_unset_falls_through_to_part_for_mount(auto):
    assert pp.part_for_property(_LEAF, _prop(), _PT, 5) == "hull"
    assert auto == [(_LEAF, _PT, 5)]


def test_set_wins(auto):
    assert pp.part_for_property(_LEAF, _prop(parent="birdofprey"), _PT) == "birdofprey"
    assert auto == []


def test_missing_falls_to_auto(auto):
    assert pp.part_for_property(_LEAF, _prop(parent="nope"), _PT) == "hull"
    assert len(auto) == 1


def test_missing_warns_once(auto, capsys):
    p = _prop(parent="nope")
    for _ in range(100):
        pp.part_for_property(_LEAF, p, _PT)
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1
    assert _LEAF in err[0] and "Port Phaser" in err[0] and "nope" in err[0]


def test_headless_trusts_name(auto):
    assert pp.part_for_property("unknownleaf", _prop(parent="anything"), _PT) == "anything"
    assert auto == []


def test_preview_overrides_baked(auto):
    pp.set_preview(_LEAF, {"Port Phaser": "birdofprey"})
    assert pp.part_for_property(_LEAF, _prop(parent="hull"), _PT) == "birdofprey"


def test_preview_none_means_auto(auto):
    pp.set_preview(_LEAF, {"Port Phaser": None})
    assert pp.part_for_property(_LEAF, _prop(parent="birdofprey"), _PT) == "hull"
    assert len(auto) == 1


def test_clear_preview_restores_baked(auto):
    p = _prop(parent="birdofprey")
    pp.set_preview(_LEAF, {"Port Phaser": None})
    pp.clear_preview(_LEAF)
    assert pp.part_for_property(_LEAF, p, _PT) == "birdofprey"
    pp.set_preview(_LEAF, {"Port Phaser": None})
    pp.clear_preview()
    assert pp.explicit_parent(_LEAF, p) == "birdofprey"


def test_preview_is_per_leaf(auto):
    pp.set_preview(_LEAF, {"Port Phaser": "hull"})
    assert pp.explicit_parent("otherleaf", _prop(parent="birdofprey")) == "birdofprey"


def test_preview_leaf_is_lowercased(auto):
    pp.set_preview("PPTestLeaf", {"Port Phaser": "hull"})
    assert pp.explicit_parent(_LEAF, _prop(parent="birdofprey")) == "hull"
    assert pp.explicit_parent("PPTESTLEAF", _prop(parent="birdofprey")) == "hull"


def test_source_for(auto):
    assert pp.source_for(_LEAF, _prop(parent="birdofprey")) == "set"
    assert pp.source_for(_LEAF, _prop()) == "auto"
    assert pp.source_for(_LEAF, _prop(parent="nope")) == "missing"


def test_property_of_unwraps_subsystem():
    prop = _prop()

    class Sub:
        def GetProperty(self):
            return prop

    assert pp.property_of(Sub()) is prop
    assert pp.property_of(prop) is prop


def test_propref(auto):
    ref = pp.PropRef("Port Phaser", "birdofprey")
    assert ref.GetName() == "Port Phaser" and ref.GetPhysicalParent() == "birdofprey"
    assert pp.part_for_property(_LEAF, ref, _PT) == "birdofprey"
