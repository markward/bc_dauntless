from engine.appc.anim_node import TGAnimNode


def test_records_use_animation_position():
    node = TGAnimNode(owner="cam", kind="camera")
    assert node.position_clip is None
    node.UseAnimationPosition("WalkCameraToCaptD")
    assert node.position_clip == "WalkCameraToCaptD"
    assert node.owner == "cam"
    assert node.kind == "camera"


def test_is_truthy_and_chainable():
    node = TGAnimNode()
    assert node                       # truthy guard (if pAnimNode:)
    assert node.Copy() is node
    assert node.GetRootNode() is node
    assert node.FindNode("x") is node


def test_records_animations_and_blend_time():
    node = TGAnimNode()
    node.UseAnimation("twitch")
    assert node.last_animation == "twitch"
    node.SetExclusiveAnimation("standing")
    assert node.last_animation == "standing"
    node.SetBlendTime(0.25)
    assert node.GetBlendTime() == 0.25
    # No-op surface must not raise.
    node.StopNonExclusiveAnimation()
    node.SetExclusiveAnimationUseDefault()
    node.Stop()
    assert node.IsAnimate() == 0
