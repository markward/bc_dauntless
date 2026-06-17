"""TGAnimNode — the animation node returned by an object's GetAnimNode().

Real (recording) replacement for the per-class GetAnimNode stubs. The SDK
asks an object for its anim node and then either positions it
(UseAnimationPosition) or builds a TGAnimAction(node, clip) to play a clip
on it. Headless we cannot render, so this node RECORDS what it is told and
carries enough identity (owner + kind) for the cutscene controller to
discover what to play and where. See
docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.

Surface mirrors sdk/Build/scripts/App.py:587-598 (TGAnimNode methods).
"""


class TGAnimNode:
    def __init__(self, owner=None, kind: str = "object"):
        self.owner = owner
        self.kind = str(kind)          # "camera" | "object"
        self.position_clip = None      # last UseAnimationPosition name
        self.last_animation = None     # last Use/SetExclusiveAnimation name
        self._blend_time = 0.0

    # ── recording surface ────────────────────────────────────────────────
    def UseAnimationPosition(self, name, *a):
        self.position_clip = str(name)

    def UseAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetExclusiveAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetNonExclusiveAnimation(self, name, *a):
        self.last_animation = str(name)

    def SetBlendTime(self, t, *a):
        self._blend_time = float(t)

    def GetBlendTime(self):
        return self._blend_time

    # ── chainable / no-op surface ────────────────────────────────────────
    def StopNonExclusiveAnimation(self, *a):
        pass

    def SetExclusiveAnimationUseDefault(self, *a):
        pass

    def Stop(self, *a):
        pass

    def IsAnimate(self, *a):
        return 0

    def Copy(self, *a):
        return self

    def SetRootNode(self, *a):
        pass

    def GetRootNode(self, *a):
        return self

    def FindNode(self, *a):
        return self

    def __bool__(self):
        return True
