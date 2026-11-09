"""The SDK-facing DauntlessWings module (claimed namespace)."""
import pytest

from engine.wings import roster, service


@pytest.fixture(autouse=True)
def _clean():
    service.reset_all()
    service.reset_dev()
    yield
    service.reset_all()


class _Group:
    def GetNameTuple(self):
        return ()


def _dw():
    import DauntlessWings
    return DauntlessWings


NAMES = ("CreateWing", "AddMember", "ArmWing", "WrapTree", "GetWing",
         "GetCommander", "IsCommander", "IsLeaderless", "GetWingTargets",
         "RegisterDecision", "IsEnabled")


def test_surface_exists():
    dw = _dw()
    for n in NAMES:
        assert callable(getattr(dw, n)), n


def test_roster_reflected(monkeypatch):
    from engine.wings import brain
    monkeypatch.setattr(brain, "arm_chain", lambda w: setattr(w, "commander", "Lead"))
    dw = _dw()
    dw.CreateWing("W", _Group())
    dw.AddMember("W", "Lead")
    dw.AddMember("W", "Wing2")
    dw.ArmWing("W")
    assert dw.GetWing("Lead") == "W"
    assert dw.GetCommander("Wing2") == "Lead"
    assert dw.IsCommander("Lead") and not dw.IsCommander("Wing2")
    assert not dw.IsLeaderless("Lead")
    assert dw.GetWing("Nobody") is None
    assert dw.GetCommander("Nobody") is None


def test_wrap_tree_passthrough_when_disabled_or_nonmember(monkeypatch):
    dw = _dw()
    tree = object()

    class Ship:
        def GetName(self):
            return "X"
    assert dw.WrapTree(Ship(), tree) is tree          # not a member
    dw.CreateWing("W", _Group())
    dw.AddMember("W", "X")
    monkeypatch.setenv("DAUNTLESS_WINGS", "0")
    assert dw.WrapTree(Ship(), tree) is tree          # disabled
    assert not dw.IsEnabled()


def test_wrap_tree_wraps_member(monkeypatch):
    from engine.wings import tree as wtree
    dw = _dw()
    dw.CreateWing("W", _Group())
    dw.AddMember("W", "X")
    out = object()
    seen = []
    monkeypatch.setattr(wtree, "wrap_tree",
                        lambda s, t, w: seen.append(w.wing_id) or out)

    class Ship:
        def GetName(self):
            return "X"
    assert dw.WrapTree(Ship(), "stock") is out and seen == ["W"]


def test_wing_targets_ordered():
    dw = _dw()
    w = roster.create_wing("W", _Group())
    dw.AddMember("W", "X")

    class G:
        def GetNameTuple(self):
            return ("a", "b", "c")

        def __getitem__(self, k):
            return {"a": {"Priority": 1.5}, "b": {"Priority": 3.0},
                    "c": {"Priority": 0.0}}[k]
    w.target_group = G()
    assert dw.GetWingTargets("X") == ("b", "a")
