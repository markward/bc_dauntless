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
    fills in `render_instance` (see host_loop._realize_bridge_model). Not a
    `_LoudStub` — it is real, so it drops off the bridge-stub summary."""
    def __init__(self, nif):
        self.nif = nif
        self.translate = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 1.0, 0.0, 0.0)   # angle, x, y, z
        self.render_instance = None            # host fills this in
        # DBridgeProperties.LoadPropertySet(pPropertySet) still runs against a
        # chainable stub; faithful hardpoint loading is a later step.
        self._property_set = _LoudStub()

    def GetPropertySet(self):
        return self._property_set

    def SetTranslateXYZ(self, x, y, z):
        self.translate = (x, y, z)

    def SetAngleAxisRotation(self, a, x, y, z):
        self.rotation = (a, x, y, z)

    def GetAnimNode(self):
        # Animation playback is not implemented headlessly; return None so the
        # SDK's PutGuestChairOut() / PutGuestChairIn() pass safely through the
        # App.TGAnimPosition_Create stub without crashing.
        return None


class ViewScreenObject(_LoudStub):
    """SDK viewscreen object. Core data is real (nif, render_instance, the
    RemoteCam/IsOn feed state consumed later by 5c RTT); the unbuilt
    station-menu/handler surface (SetMenu, ToggleRemoteCam,
    AddPythonFuncHandlerForInstance, IsStaticOn, MenuDown, ...) falls through
    _LoudStub.__getattr__ as a silent no-op so missions that touch it don't
    crash. The HOST reads this object after LoadBridge.Load and fills in
    render_instance (see host_loop._realize_viewscreen), mirroring
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


class CameraObjectClass:
    """A set camera. Built either from an embedded NiCamera
    (CameraObjectClass_CreateFromNiCamera) or from explicit coordinates
    (CameraObjectClass_Create). Real, stateful data: the viewscreen's
    SetRemoteCam consumes it. Comm-set rendering through it is not yet
    built (flagged loudly under developer mode)."""
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


def CameraObjectClass_CreateFromNiCamera(niCamera, name):
    left, right, top, bottom = niCamera.frustum
    frustum = _NiFrustum(left, right, top, bottom, niCamera.near, niCamera.far)
    orientation = TGMatrix3()
    orientation.Set(*niCamera.rotation)      # row-major args
    return CameraObjectClass(name, niCamera.position, orientation,
                             frustum, niCamera.near, niCamera.far)


def CameraObjectClass_Create(x, y, z, a, ax, ay, az, name):
    """Fallback camera from explicit coords + angle-axis orientation. The SDK
    overrides near/far via SetNearAndFarDistance; frustum starts default."""
    orientation = TGMatrix3().MakeRotation(a, TGPoint3(ax, ay, az))
    return CameraObjectClass(name, (x, y, z), orientation,
                             _NiFrustum(), 1.0, 800.0)


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
