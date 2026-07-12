"""Regression: the lift-door drain must NOT be gated on bridge view.

LiftDoorAction's own TGSoundAction plays view-independently the instant its
builder sequence fires (the door step's 0.125s schedule delay, e.g.
PicardAnimations.MoveFromL1ToP1). Before this fix, the door DRAW was only
drained inside ``if view_mode.is_bridge:`` (cutscene.update()'s camera half
needs the bridge view; the door half does not). An AT_MOVE fired from
EXTERIOR view (the same E1M1 UndockCutscene beat that motivates
_pump_walk_controller) played the door sound on schedule but left the door
itself queued until the player next entered bridge view -- where it swung
open with nobody there.

``_pump_bridge_doors`` is the view-independent seam that drains
BridgeCutsceneController._pending_doors every unpaused frame regardless of
view. These tests drive it directly, with no view_mode anywhere.
"""
import App
from engine.bridge_cutscene import BridgeCutsceneController
from engine.host_loop import _pump_bridge_doors


class _RecordingRenderer:
    def __init__(self):
        self.node_clips = []      # (iid, path, loop, reverse)

    def play_instance_node_clip(self, iid, path, loop, reverse):
        self.node_clips.append((iid, path, loop, reverse))


class _FakeAction:
    def __init__(self):
        self.completed = 0

    def Completed(self):
        self.completed += 1


class _FakeNode:
    def __init__(self, owner):
        self.owner = owner
        self.kind = "object"


class _FakeBridge:
    render_instance = 42


def _queued_door(resolver=None):
    ctrl = BridgeCutsceneController(asset_resolver=resolver or (lambda rel: "/game/" + rel))
    App.g_kAnimationManager.LoadAnimation("data/animations/db_door_l1.nif", "doorl1")
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_FakeBridge()), "doorl1")
    return ctrl, act


def test_door_drains_through_the_view_independent_pump():
    """No view_mode, no bridge view -- the door still plays and completes."""
    ctrl, act = _queued_door()
    r = _RecordingRenderer()

    _pump_bridge_doors(ctrl, r, paused=False)

    assert r.node_clips == [(42, "/game/data/animations/db_door_l1.nif", False, False)]
    assert act.completed == 1


def test_pump_skipped_while_paused():
    """A paused frame must not drain the queued door."""
    ctrl, act = _queued_door()
    r = _RecordingRenderer()

    _pump_bridge_doors(ctrl, r, paused=True)

    assert r.node_clips == []
    assert act.completed == 0
