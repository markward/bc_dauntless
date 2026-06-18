"""Control-flow-correct shims for the SDK bridge-load sequence.

The real sdk/Build/scripts/LoadBridge.py + Bridge/<name>.py call a swath of
Appc surface that does not yet exist in our shim. Rather than let App.py's
permissive `_NamedStub` swallow them silently (and break control flow —
`BridgeSet_Cast` returning a truthy stub makes Load skip crew creation), we
register explicit, control-flow-correct implementations here, so the sequence
runs end-to-end. The bridge config/object/viewscreen/camera objects are real,
stateful data the host and SDK consume; only the large engine-side
menu/handler/camera-mode surface stays a silent `_LoudStub` no-op.

These are registered into the `App` namespace by App.py (explicit module
attributes shadow App.py's `__getattr__` catch-all).
"""
from pathlib import Path as _Path

from engine.appc.sets import SetClass
from engine.appc.math import TGMatrix3, TGPoint3

# bridge_set.py lives at engine/appc/ -> project root is two parents up.
_GAME_ROOT = _Path(__file__).resolve().parent.parent.parent / "game"


class _LoudStub:
    """A truthy placeholder for a deferred engine object (bridge object,
    viewscreen, camera).

    Calls to undefined methods return ``None`` — which is control-flow-correct
    for the SDK's bridge-load path (e.g. `pViewScreen.GetRemoteCam()` must be
    falsey so the `if pCamera != None:` guard skips). It stays truthy via
    `__bool__` so guards like `if pViewScreen:` don't short-circuit.
    """
    def __getattr__(self, name):
        return lambda *a, **k: None
    def __bool__(self):
        return True


class BridgeObjectClass:
    """The bridge model object the SDK config script creates and adds to the
    bridge set as "bridge". A pure, headless data object: it carries the NIF
    path and transform the SDK sets; the HOST reads it after LoadBridge.Load and
    fills in `render_instance` (see host_loop.realize_set). Not a
    `_LoudStub` — it is real, so it drops off the bridge-stub summary."""
    def __init__(self, nif):
        self.nif = nif
        self.translate = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 1.0, 0.0, 0.0)   # angle, x, y, z
        self.render_instance = None            # host fills this in
        # DBridgeProperties.LoadPropertySet(pPropertySet) still runs against a
        # chainable stub; faithful hardpoint loading is a later step.
        self._property_set = _LoudStub()
        self._anim_node = None

    def GetPropertySet(self):
        return self._property_set

    def SetTranslateXYZ(self, x, y, z):
        self.translate = (x, y, z)

    def SetAngleAxisRotation(self, a, x, y, z):
        self.rotation = (a, x, y, z)

    def GetAnimNode(self):
        # Real recording node (kind="object"): the door TGAnimAction targets
        # this. PutGuestChairOut/In still only build a TGAnimPosition from it,
        # which is safe. Was previously None.
        if getattr(self, "_anim_node", None) is None:
            from engine.appc.anim_node import TGAnimNode
            self._anim_node = TGAnimNode(owner=self, kind="object")
        return self._anim_node


class ViewScreenObject(_LoudStub):
    """SDK viewscreen object. Core data is real (nif, render_instance, the
    RemoteCam/IsOn feed state consumed later by 5c RTT); the unbuilt
    station-menu/handler surface (SetMenu, ToggleRemoteCam,
    AddPythonFuncHandlerForInstance, IsStaticOn, MenuDown, ...) falls through
    _LoudStub.__getattr__ as a silent no-op so missions that touch it don't
    crash. The HOST reads this object after LoadBridge.Load and fills in
    render_instance (see host_loop.realize_set), mirroring
    BridgeObjectClass. Kept a _LoudStub (unlike BridgeObjectClass) precisely
    because that menu/handler surface is large and not yet built."""
    def __init__(self, nif):
        self.nif = nif
        self.render_instance = None    # host fills this in
        self._remote_cam = None
        self._is_on = 0

    def GetRemoteCam(self):
        return self._remote_cam

    def SetRemoteCam(self, cam):
        # ViewscreenOn sets a comm set's maincamera; ViewscreenOff reverts to the
        # player camera. The host's _active_comm_feed identity-matches the remote
        # cam back to a comm set, falling back to the forward view for anything
        # else — so a plain store gives the correct comm-then-revert behavior now
        # that action-sequence timing holds the comm scene for the dialogue.
        self._remote_cam = cam

    def SetIsOn(self, on):
        self._is_on = on

    def IsOn(self):
        return self._is_on


class ZoomCameraObjectClass(_LoudStub):
    """SDK bridge camera ("maincamera"). Core data is real (captain-chair
    position, angle-axis orientation, zoom min/max/time); the engine's
    camera-mode + zoom-transform surface (GetNamedCameraMode, PushCameraMode,
    Update, ToggleZoom, Zoom, IsZoomed, LookForward, ...) stays a silent
    _LoudStub no-op — that geometry lived in Appc and is not reconstructed
    here. The host reads `position` + the zoom getters after LoadBridge.Load to
    drive _BridgeCamera (see host_loop). Kept a _LoudStub (unlike
    BridgeObjectClass) precisely because that camera-mode surface is large and
    not built."""
    def __init__(self, x, y, z, qw, qx, qy, qz, name):
        self.position = (x, y, z)
        self.orientation = (qw, qx, qy, qz)   # angle, axis-x, axis-y, axis-z
        self._name = name
        self._min_zoom = 1.0
        self._max_zoom = 1.0
        self._zoom_time = 0.0
        self._anim_node = None   # lazily created TGAnimNode (kind="camera")

    def GetAnimNode(self):
        # Real recording node (kind="camera"): the cutscene controller reads
        # the camera-path clip a TGAnimAction queues on it. Was previously a
        # _LoudStub no-op returning None, which crashed E1M1 Briefing().
        if self._anim_node is None:
            from engine.appc.anim_node import TGAnimNode
            self._anim_node = TGAnimNode(owner=self, kind="camera")
        return self._anim_node

    def SetMinZoom(self, v):  self._min_zoom = v
    def SetMaxZoom(self, v):  self._max_zoom = v
    def SetZoomTime(self, v): self._zoom_time = v
    def GetMinZoom(self):  return self._min_zoom
    def GetMaxZoom(self):  return self._max_zoom
    def GetZoomTime(self): return self._zoom_time
    def SetTranslateXYZ(self, x, y, z): self.position = (x, y, z)


class _NiFrustum:
    """Mutable frustum bounds, mirroring the engine's NiFrustum struct.
    MissionLib.SetupBridgeSet reads these, scales each by 0.5, and writes
    them back via SetNiFrustum."""
    def __init__(self, left=0.0, right=0.0, top=0.0, bottom=0.0,
                 near=0.0, far=0.0):
        self.m_fLeft = left
        self.m_fRight = right
        self.m_fTop = top
        self.m_fBottom = bottom
        self.m_fNear = near
        self.m_fFar = far


class NiCameraData:
    """Opaque handle the SDK passes from CloneCamera to
    CameraObjectClass_CreateFromNiCamera. Holds the camera placement +
    frustum parsed out of a set NIF (game units; rotation row-major,
    column-vector convention)."""
    def __init__(self, position, rotation, frustum, near, far, source=""):
        self.position = tuple(position)      # (x, y, z) world, game units
        self.rotation = tuple(rotation)      # 9 floats, row-major storage
        self.frustum = tuple(frustum)        # (left, right, top, bottom)
        self.near = near
        self.far = far
        self.source = source


class CameraObjectClass(_LoudStub):
    """A set camera. Built either from an embedded NiCamera
    (CameraObjectClass_CreateFromNiCamera) or from explicit coordinates
    (CameraObjectClass_Create). Real, stateful data: the viewscreen's
    SetRemoteCam consumes it. The host renders a comm set through this camera
    when the bridge viewscreen is showing it.

    The unbuilt camera-mode/control surface (GetNamedCameraMode, PushCameraMode,
    LookForward, AddModeHierarchy, etc.) degrades to no-ops via _LoudStub.__getattr__
    — exactly like ZoomCameraObjectClass. This prevents AttributeError from
    aborting the SDK's SendActivationEvent → ViewscreenOn chain before
    SetRemoteCam fires. Real explicit methods (GetNiFrustum, SetTranslate,
    AlignToVectors, GetWorldLocation, GetWorldRotation, ...) take precedence
    over the fallthrough."""
    def __init__(self, name, position, orientation, frustum, near, far):
        self._name = name
        self.position = tuple(position)
        self.orientation = orientation       # TGMatrix3 (column-vector)
        self._frustum = frustum              # _NiFrustum
        self._near = near
        self._far = far

    def GetNiFrustum(self):
        return self._frustum

    def SetNiFrustum(self, frustum):
        self._frustum = frustum

    def SetNearAndFarDistance(self, near, far):
        self._near = near
        self._far = far

    def GetNearDistance(self):
        return self._near

    def GetFarDistance(self):
        return self._far

    # ── Activation-path placement (CameraScriptActions) ──────────────────────
    # SetCameraPositionAndFacing / CutsceneCameraBegin (Actions/
    # CameraScriptActions.py:122-123, 158) call SetTranslate + AlignToVectors +
    # UpdateNodeOnly on the set "maincamera" during the viewscreen/dock
    # activation event chain. Without these, the AttributeError raised here is
    # swallowed by characters.STButton.SendActivationEvent, which kills the
    # whole activation chain (SetRemoteCam may never fire, so the comm feed
    # never engages). These keep .position / .orientation faithful so the
    # comm-feed camera params (_comm_camera_params) read the posed camera.

    def SetTranslate(self, point):
        """Place the camera at a TGPoint3 (game units). Mirrors
        ObjectClass.SetTranslate; updates the tuple the feed reads."""
        self.position = (float(point.x), float(point.y), float(point.z))

    def AlignToVectors(self, forward, up):
        """Build the orientation TGMatrix3 from forward/up, column-vector
        right-handed convention (col0=right, col1=forward, col2=up). Mirrors
        ObjectClass.AlignToVectors verbatim (right = forward × up, det = +1;
        see CLAUDE.md ↦ rotation matrix convention)."""
        fwd = TGPoint3(forward.x, forward.y, forward.z)
        fwd.Unitize()
        u = TGPoint3(up.x, up.y, up.z)
        dot = fwd.Dot(u)
        u = TGPoint3(u.x - dot * fwd.x, u.y - dot * fwd.y, u.z - dot * fwd.z)
        u.Unitize()
        right = fwd.Cross(u)
        right.Unitize()
        m = TGMatrix3()
        m.SetCol(0, right)
        m.SetCol(1, fwd)
        m.SetCol(2, u)
        self.orientation = m

    def SetMatrixRotation(self, matrix):
        """Set the camera's orientation directly from a TGMatrix3.

        Mirrors BaseObjectClass.SetMatrixRotation (App.py:3884) and
        ObjectClass.SetMatrixRotation (engine/appc/objects.py:108): it stores
        the matrix verbatim — same column-vector right-handed convention
        GetWorldRotation returns and AlignToVectors builds (CLAUDE.md ↦
        rotation matrix convention). CutsceneCameraBegin
        (Actions/CameraScriptActions.py:154) calls this with the active
        camera's GetWorldRotation() to seed the cutscene camera's start
        orientation; without a real method here it fell through
        _LoudStub.__getattr__ to a silent no-op and the rotation was never
        copied."""
        self.orientation = matrix

    def UpdateNodeOnly(self):
        """No-op: Phase 1 has no live scene-graph node to flush the transform
        into. The .position / .orientation set above are read directly by the
        host. Faithful to the SDK call (it only forces a node-transform update;
        no return value)."""
        return None

    # ── World-transform getters ──────────────────────────────────────────────
    # CutsceneCameraBegin (CameraScriptActions.py:158) calls
    # GetWorldLocation + GetWorldRotation to seed the cutscene camera start
    # pose. Return the real placement data we already hold; more faithful than
    # the _LoudStub None fallthrough and lets the cutscene path read the actual
    # camera origin (important for comm-feed camera continuity).

    def GetWorldLocation(self):
        """Return camera position as a TGPoint3 (game units)."""
        x, y, z = self.position
        return TGPoint3(x, y, z)

    def GetWorldRotation(self):
        """Return the stored orientation TGMatrix3 (column-vector)."""
        return self.orientation

    # ── Camera-mode stack ─────────────────────────────────────────────────────
    # Real replacement for the _LoudStub no-ops so the SDK's Camera.NewMode
    # (sdk/Build/scripts/Camera.py) can push live modes. The mode's Update()
    # then drives the rendered exterior view (host_loop._active_cutscene_camera).
    # AddModeHierarchy stays a no-op — the mode-fallback tree is out of v1 scope.

    _MODE_FACTORY = {
        "Locked": ("LockedMode", {}),
        "Chase": ("ChaseMode", {}),
        "ReverseChase": ("ChaseMode", {"reverse": True}),
        "Target": ("TargetMode", {}),
    }

    def GetNamedCameraMode(self, name, *args):
        if "_named_modes" not in self.__dict__:
            self._named_modes = {}
            self._mode_stack = []
        if name in self._named_modes:
            return self._named_modes[name]
        spec = self._MODE_FACTORY.get(name)
        if spec is None:
            return None
        from engine.appc import camera_modes
        cls = getattr(camera_modes, spec[0])
        mode = cls(**spec[1])
        self._named_modes[name] = mode
        return mode

    def _ensure_stack(self):
        if "_mode_stack" not in self.__dict__:
            self._named_modes = {}
            self._mode_stack = []
        return self._mode_stack

    def PushCameraMode(self, mode):
        stack = self._ensure_stack()
        R = self.GetWorldRotation()
        loc = self.GetWorldLocation()
        fwd = R.GetCol(1)
        up = R.GetCol(2)
        mode.set_initial_pose((loc.x, loc.y, loc.z),
                              (fwd.x, fwd.y, fwd.z), (up.x, up.y, up.z))
        stack.append(mode)

    def PopCameraMode(self, mode=None):
        stack = self._ensure_stack()
        if not stack:
            return None
        if mode is None:
            return stack.pop()
        # Named/object pop: remove the matching mode wherever it sits.
        for i in range(len(stack) - 1, -1, -1):
            if stack[i] is mode or (
                    hasattr(mode, "GetObjID") and stack[i].GetObjID() == mode.GetObjID()):
                return stack.pop(i)
        return None

    def GetCurrentCameraMode(self, *args):
        stack = self._ensure_stack()
        return stack[-1] if stack else None

    def AddModeHierarchy(self, *args):
        return None


def CameraObjectClass_CreateFromNiCamera(niCamera, name):
    left, right, top, bottom = niCamera.frustum
    frustum = _NiFrustum(left, right, top, bottom, niCamera.near, niCamera.far)
    # niCamera.rotation is the set camera's WORLD node rotation (row-major), whose
    # basis columns (gbCol0/1/2) are the world images of the node's local +X/+Y/+Z.
    #
    # The documented Gamebryo-1.2 camera convention (view down local -Z, up local
    # +Y) does NOT hold for BC's NetImmerse 3.x/4.x content: on the real E1M1 Liu
    # hail, -gbCol2 aimed the camera at a side wall and lost the admiral
    # (live-refuted 2026-06-18). The frame that actually matches the authored shot
    # is VIEW DOWN LOCAL +X, UP LOCAL +Y — gbCol0 aims from the eye toward the
    # seated subject and gbCol1 is level. (BC's directional lights likewise shine
    # down local +X — cleanroom SDK §10 — so a +X-forward set camera is consistent
    # with that NetImmerse-era family. up = +gbCol1 still matches the documented
    # Gamebryo up axis exactly; only forward/right are cyclically shifted.)
    #
    # CameraObjectClass.orientation is the BC-OBJECT convention (col0=right,
    # col1=forward, col2=up) — the frame AlignToVectors builds and that
    # _comm_camera_params / CameraObjectClass_Create / GetWorldRotation all read.
    # Convert with a cyclic column shift:
    #     object forward = +gbCol0   (the camera's view direction)
    #     object up      = +gbCol1
    #     object right   = +gbCol2   (= forward × up; gbCol0 × gbCol1 == gbCol2)
    # The result is a proper right-handed rotation (det +1) with right = fwd × up.
    gb = TGMatrix3()
    gb.Set(*niCamera.rotation)                # row-major args -> columns = gb basis
    orientation = TGMatrix3()
    orientation.SetCol(0, gb.GetCol(2))       # right
    orientation.SetCol(1, gb.GetCol(0))       # forward
    orientation.SetCol(2, gb.GetCol(1))       # up
    return CameraObjectClass(name, niCamera.position, orientation,
                             frustum, niCamera.near, niCamera.far)


def CameraObjectClass_Create(x, y, z, a, ax, ay, az, name):
    """Fallback camera from explicit coords + angle-axis orientation. The SDK
    overrides near/far via SetNearAndFarDistance; frustum starts default.

    The host renders a comm set through this camera when the bridge viewscreen
    is showing it (host_loop._active_comm_feed / _comm_camera_params)."""
    orientation = TGMatrix3().MakeRotation(a, TGPoint3(ax, ay, az))
    return CameraObjectClass(name, (x, y, z), orientation,
                             _NiFrustum(), 1.0, 800.0)


def CameraObjectClass_Cast(obj):
    """Downcast to a camera, mirroring BridgeSet_Cast / the SDK's *_Cast.

    Bridge.Characters.CommonAnimations.WalkCameraToCaptOnD/OnE do
    ``pCamera = App.CameraObjectClass_Cast(pCharacter)`` then build the
    camera-move TGAnimAction on ``pCamera.GetAnimNode()``. The ZoomCamera the
    SDK passes in IS a camera (ZoomCameraObjectClass derives from
    CameraObjectClass in the original engine), so return it; anything else is
    not a camera. Without this, App's module __getattr__ hands back a
    _NamedStub, the anim node loses kind="camera", and the walk-on never routes
    to the cutscene controller (it instant-completes). Control-flow-correct: a
    non-camera returns None so ``if pCamera:`` guards behave."""
    return obj if isinstance(obj, (CameraObjectClass, ZoomCameraObjectClass)) else None


class ModelManager:
    """Real (no longer a loud stub): our renderer loads NIFs lazily at instance
    creation, host-side. LoadModel's faithful equivalent is to remember the
    texture/env path the SDK pre-loads each NIF with, so the host can search the
    right detail directory (Low/Medium/High) when it realizes the mesh. It loads
    nothing into the renderer itself."""
    def __init__(self):
        self._env = {}                       # nif path -> texture/env path

    def LoadModel(self, path, a=None, env=None):
        self._env[path] = env
        return None

    def CloneCamera(self, path):
        """Return the camera embedded in the set NIF, or None when the model
        has none / the renderer isn't present.

        Some set NIFs carry a camera (e.g. starbasecontrolRM.nif has
        'Camera01'); the player bridges do not (DBridge/EBridge), which is
        why MissionLib.SetupBridgeSet hardcodes their coords in the None
        branch. Parsing happens C++-side via the parse-only host binding; in
        headless tests (no compiled module) we return None and the SDK takes
        its fallback branch."""
        try:
            import _dauntless_host
        except ImportError:
            return None
        if _dauntless_host is None or not hasattr(_dauntless_host,
                                                  "parse_set_camera"):
            return None
        nif_abs = str(_GAME_ROOT / path)
        data = _dauntless_host.parse_set_camera(nif_abs)
        if data is None:
            return None
        return NiCameraData(
            position=data["position"],
            rotation=data["rotation"],
            frustum=data["frustum"],
            near=data["near"],
            far=data["far"],
            source=path,
        )

    def env_for(self, path):
        return self._env.get(path)


class BridgeSet(SetClass):
    """The bridge SetClass. Crew/light/object registration is inherited REAL
    from SetClass; only the bridge-config/viewscreen/camera-delete surface is
    overridden so it is stateful — faithful plumbing the host/SDK consume
    instead of silently stubbed."""
    def __init__(self):
        super().__init__()
        self._config = ""
        self._viewscreen = None

    def IsSameConfig(self, name):
        return 1 if self._config == name else 0

    def GetConfig(self):
        return self._config

    def SetConfig(self, name):
        self._config = name

    def GetViewScreen(self):
        return self._viewscreen

    def SetViewScreen(self, viewscreen, name="viewscreen"):
        self._viewscreen = viewscreen
        self.AddObjectToSet(viewscreen, name)

    def DeleteCameraFromSet(self, name):
        self.RemoveCameraFromSet(name)


def BridgeSet_Create():
    return BridgeSet()


def BridgeSet_Cast(obj):
    # Control-flow-correct: Load() does `if BridgeSet_Cast(GetSet("bridge")) == None`.
    return obj if isinstance(obj, BridgeSet) else None


def BridgeObjectClass_Create(nif):
    return BridgeObjectClass(nif)              # real, stateful data object


def ViewScreenObject_Create(nif):
    return ViewScreenObject(nif)               # real, stateful data object


def ZoomCameraObjectClass_Create(x, y, z, qw, qx, qy, qz, name):
    return ZoomCameraObjectClass(x, y, z, qw, qx, qy, qz, name)  # real -> off summary


def ZoomCameraObjectClass_GetObject(pSet, name):
    # Return the real camera added via AddCameraToSet. The _LoudStub fallback
    # (camera absent) keeps ConfigureCharacters' SetTranslateXYZ from crashing.
    cam = pSet.GetCamera(name) if pSet is not None else None
    return cam if cam is not None else _LoudStub()


def CameraObjectClass_GetObject(pSet, name):
    """Look up a named camera in a set, mirroring App.py's real
    CameraObjectClass_GetObject (which returns the Appc camera or a falsey
    null).

    Unlike ZoomCameraObjectClass_GetObject, a MISS returns None (not a
    _LoudStub): every SDK caller guards the result with ``if pCamera == None``
    / ``if not pCamera`` (Actions/CameraScriptActions.py:65,76,109,473,519,560;
    WarpSequence.py:530), so a truthy stub on miss would defeat those guards
    and drive camera-mode calls against a fake object. None is both faithful
    and control-flow-correct.

    This backs CutsceneCameraEnd and the cutscene camera-mode functions; it was
    previously absent, so App.CameraObjectClass_GetObject fell through App.py's
    module __getattr__ to a *truthy* _NamedStub."""
    return pSet.GetCamera(name) if pSet is not None else None
