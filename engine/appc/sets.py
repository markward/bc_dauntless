from engine.appc.events import TGEventHandlerObject


class _RendererStub:
    """Returned by SetClass for renderer-only methods not needed in Phase 1.

    Chainable: pSet.GetLight("x").AddIlluminatedObject(y) succeeds silently.
    Truthy: SDK guards like `if pCamera:` don't short-circuit.
    """
    def __getattr__(self, name: str):
        return self
    def __call__(self, *args, **kwargs):
        return _RendererStub()
    def __bool__(self):
        return True
    def __repr__(self):
        return "<_RendererStub>"


class SetClass(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self._name: str = ""
        self._objects: dict[str, object] = {}
        # Camera registry — driven by AddCameraToSet / SetActiveCamera.
        # CutsceneCameraBegin (sdk/.../Actions/CameraScriptActions.py) checks
        # `if not pSet.GetCamera(sCamera):` to decide whether to add a new
        # cutscene camera, so GetCamera must return None until something is
        # actually added.  Returning a truthy renderer stub triggers the
        # "already been called" KeyError on first invocation.
        self._cameras: dict[str, object] = {}
        self._active_camera_name: "str | None" = None
        # Lights — populated by App.LightPlacement_Create + Config*Light or by
        # the pSet.Create*Light shortcut methods below. _lights_by_name is the
        # GetLight index; _lights preserves insertion order for aggregation.
        # Forward-quoted to avoid an import cycle (engine.appc.lights imports
        # from engine.appc.placement which imports from engine.appc.objects).
        self._lights: 'list["Light"]' = []
        self._lights_by_name: 'dict[str, "Light"]' = {}
        # Backdrops — populated by pSet.AddBackdropToSet(). Ordered list
        # (insertion order = draw order); names aren't indexed because BC
        # scripts only ever pass them positionally to AddBackdropToSet,
        # never look them up later.
        self._backdrops: 'list["Backdrop"]' = []

    def __getattr__(self, name: str):
        """Return a chainable stub for renderer-specific methods not needed in Phase 1
        (CreateAmbientLight, SetBackgroundModel, GetLight, etc.)."""
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: _RendererStub()

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def SetRegionModule(self, module_name: str) -> None:
        pass

    def SetProximityManagerActive(self, active: int) -> None:
        pass

    def AddObjectToSet(self, obj, identifier: str) -> bool:
        if hasattr(obj, "SetName"):
            obj.SetName(identifier)
        if hasattr(obj, "_containing_set"):
            obj._containing_set = self
        self._objects[identifier] = obj
        return True

    def GetObject(self, name: str):
        return self._objects.get(name)

    def RemoveObjectFromSet(self, name: str):
        return self._objects.pop(name, None)

    def DeleteObjectFromSet(self, name: str) -> None:
        self._objects.pop(name, None)

    def IsLocationEmptyTG(self, point, radius: float, flag: int = 1) -> int:
        """Phase 1 stub — always reports the location as empty."""
        return 1

    # ── Object iteration ─────────────────────────────────────────────────────
    # SDK pattern (MissionLib.HideCharacters):
    #   pObject = pSet.GetFirstObject()
    #   pFirstObject = pObject
    #   while not App.IsNull(pObject):
    #       pObject = pSet.GetNextObject(pObject.GetObjID())
    #       if (pObject.GetObjID() == pFirstObject.GetObjID()):
    #           pObject = App.CharacterClass_CreateNull()  # exit
    # Real iteration must terminate — empty sets return None, populated sets
    # walk and wrap so the wrap-detection branch fires.

    def GetFirstObject(self):
        if not self._objects:
            return None
        return next(iter(self._objects.values()))

    def GetNextObject(self, obj_id):
        # Iterate _objects in insertion order, find the one whose GetObjID()
        # matches obj_id, and return the next one (wrapping to first).
        items = list(self._objects.values())
        for i, obj in enumerate(items):
            if hasattr(obj, "GetObjID") and obj.GetObjID() == int(obj_id):
                # Wrap to the head — caller's wrap-detection branch will fire.
                return items[(i + 1) % len(items)]
        return None

    # ── Proximity manager ───────────────────────────────────────────────────
    # SDK pattern (E6M4): pSet.GetProximityManager().AddObject(pProbe).
    # Lazy-create a single per-set instance so AddObject calls accumulate
    # rather than dropping into fresh stubs each call.
    def GetProximityManager(self):
        if not hasattr(self, "_proximity_manager") or self._proximity_manager is None:
            from engine.appc.planet import ProximityManager
            self._proximity_manager = ProximityManager(self)
        return self._proximity_manager

    # ── Cameras ──────────────────────────────────────────────────────────────
    # Mirror sdk/.../App.py:3548-3555.  CutsceneCameraBegin/End rely on the
    # presence/absence semantics; mission scripts also call GetActiveCamera
    # to copy its position when adding a new cutscene camera.

    def GetCamera(self, name: str):
        return self._cameras.get(name)

    def AddCameraToSet(self, camera, name: str) -> None:
        self._cameras[name] = camera

    def RemoveCameraFromSet(self, name: str) -> None:
        self._cameras.pop(name, None)
        if self._active_camera_name == name:
            self._active_camera_name = None

    def GetActiveCamera(self):
        if self._active_camera_name is None:
            return None
        return self._cameras.get(self._active_camera_name)

    def SetActiveCamera(self, name: str) -> None:
        self._active_camera_name = name

    # ── Lights ──────────────────────────────────────────────────────────────
    # Two SDK call paths populate _lights:
    #   1. App.LightPlacement_Create + kThis.Config*Light (engine/appc/lights.py)
    #   2. pSet.Create*Light (these methods, the shortcut form)
    # GetLight returns the named Light or None — must be None (not a stub) so
    # that scripts using `if pLight: ...` short-circuit for misses.

    def CreateAmbientLight(self, r, g, b, dimmer, name):
        """SDK signature: pSet.CreateAmbientLight(r, g, b, range_or_dimmer, name).

        The 4th arg is "range" in some calls (MissionLib bridge: 19.0) and
        "dimmer" in others (LoadBridge: 0.7). For ambient light range is
        meaningless (no falloff), so we treat it as dimmer uniformly.
        Bridge-rendering follow-up (deferred-work) will revisit the
        high-dimmer bridge case once bridge interiors actually render.
        """
        from engine.appc.lights import Light
        light = Light(Light.KIND_AMBIENT, name, r, g, b, dimmer)
        self._lights.append(light)
        self._lights_by_name[name] = light
        return light

    def CreateDirectionalLight(self, r, g, b, dimmer, dx, dy, dz, name):
        """SDK signature observed in DeepSpace.py:
            pSet.CreateDirectionalLight(1, 1, 1, 1, 1, 0, 0, "light1")
        i.e. (r, g, b, dimmer, dx, dy, dz, name).
        """
        from engine.appc.lights import Light
        light = Light(Light.KIND_DIRECTIONAL, name, r, g, b, dimmer)
        light._direction_world = (float(dx), float(dy), float(dz))
        self._lights.append(light)
        self._lights_by_name[name] = light
        return light

    def GetLight(self, name):
        return self._lights_by_name.get(name)

    # ── Backdrops ──────────────────────────────────────────────────────────
    # SDK signature: pSet.AddBackdropToSet(obj, name).
    # Insertion order is draw order: StarSphere first, nebula overlays
    # alpha-blended on top in registration order.

    def AddBackdropToSet(self, backdrop, name):
        if hasattr(backdrop, "SetName"):
            backdrop.SetName(name)
        self._backdrops.append(backdrop)
        return None


class SetManager:
    def __init__(self):
        self._sets: dict[str, SetClass] = {}
        self._rendered_set_name: "str | None" = None

    def AddSet(self, pSet: SetClass, name: str) -> None:
        pSet.SetName(name)
        self._sets[name] = pSet

    def GetSet(self, name: str) -> "SetClass | None":
        return self._sets.get(name)

    def RemoveSet(self, name: str) -> None:
        self._sets.pop(name, None)

    def DeleteSet(self, name: str) -> None:
        self._sets.pop(name, None)

    def DeleteAllSets(self) -> None:
        self._sets.clear()

    def GetNumSets(self) -> int:
        return len(self._sets)

    def GetRenderedSet(self) -> "SetClass | None":
        if self._rendered_set_name is None:
            return None
        return self._sets.get(self._rendered_set_name)

    def MakeRenderedSet(self, name: str) -> None:
        # Switches the camera/render focus to the named set.  Phase 1 has no
        # renderer, but the SDK CameraScriptActions.ChangeRenderedSet calls
        # this during cinematic transitions and the lookup result is fed
        # back through GetRenderedSet — so we record the name for round-trip.
        self._rendered_set_name = name


class _NullSet(SetClass):
    """Searches all registered sets when GetObject is called.

    Mirrors the real engine's SetClass_GetNull() behaviour — the null set
    is a global search handle, not a real set with objects in it.
    """
    def GetObject(self, name: str):
        from engine.appc.sets import _get_set_manager
        sm = _get_set_manager()
        if sm is None:
            return None
        for pSet in sm._sets.values():
            obj = pSet._objects.get(name)
            if obj is not None:
                return obj
        return None


def _get_set_manager():
    """Late-binding accessor so sets.py doesn't import App at module load time."""
    try:
        import App
        return App.g_kSetManager
    except ImportError:
        return None


_null_set = _NullSet()


def SetClass_GetNull() -> "_NullSet":
    return _null_set


def SetClass_Create() -> SetClass:
    return SetClass()
