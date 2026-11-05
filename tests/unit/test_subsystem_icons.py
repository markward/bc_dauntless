from engine.ui import subsystem_icons as si
from engine.appc import subsystems as ss


def test_class_keys():
    assert si.icon_key_for(ss.SensorSubsystem("S")) == "radar"
    assert si.icon_key_for(ss.ImpulseEngineSubsystem("I")) == "chevrons-up"
    assert si.icon_key_for(ss.WarpEngineSubsystem("W")) == "margin-horizontal"
    assert si.icon_key_for(ss.ShieldSubsystem("G")) == "shield-plus"
    assert si.icon_key_for(ss.PowerSubsystem("P")) == "zap"
    assert si.icon_key_for(ss.CloakingSubsystem("C")) == "eye-off"
    assert si.icon_key_for(ss.HullSubsystem("H")) == "hull"


def test_unknown_and_none_fall_back():
    assert si.icon_key_for(None) == "boxes-linked"
    assert si.icon_key_for(ss.ShipSubsystem("x")) == "boxes-linked"


def test_engine_pods_follow_their_parent():
    impulse = ss.ImpulseEngineSubsystem("Impulse Engines")
    warp = ss.WarpEngineSubsystem("Warp Engines")
    impulse_pod = ss.ShipSubsystem("Port Impulse")
    warp_pod = ss.ShipSubsystem("Port Warp")
    impulse.AddChildSubsystem(impulse_pod)
    warp.AddChildSubsystem(warp_pod)
    assert si.icon_key_for(impulse_pod) == "chevrons-up"
    assert si.icon_key_for(warp_pod) == "warp-pod"


def test_every_key_has_a_file():
    assert len(si.ICON_KEYS) == 13
    for key in si.ICON_KEYS:
        assert si.svg_for_key(key).lstrip().startswith(("<!--", "<svg"))
    assert si.svg_for_key("nope") is None
