import re
from functools import lru_cache

from engine.appc.events import TGEventHandlerObject


@lru_cache(maxsize=1)
def _systems_tgl():
    """The Systems.TGL localization database (system + region display names),
    or None if it can't be loaded (e.g. game/ not installed). Cached."""
    try:
        from engine.appc.localization import TGLocalizationManager
        return TGLocalizationManager().Load("data/TGL/Systems.TGL")
    except Exception:
        return None


def SetClass_MakeDisplayName(set_name):
    """App.SetClass_MakeDisplayName — human-readable label for a set/region
    name. Mirrors real Appc: look the set name up in Systems.TGL (e.g.
    'Vesuvi4' -> 'Vesuvi Dust Cloud', 'Multi1' -> 'Asteroids'); fall back to
    inserting a space before a trailing digit run ('Albirea1' -> 'Albirea 1')
    for the planet regions that have no localized name. Always a real str (never
    a _NamedStub), so the baked catalog and the live SDK menu produce identical
    labels for the same set."""
    name = str(set_name)
    db = _systems_tgl()
    if db is not None and db.HasString(name):
        return str(db.GetString(name))
    return re.sub(r"(?<=\D)(\d+)$", r" \1", name)


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


class SetEffectRoot:
    """The set's effect-attach node — returned by SetClass.GetEffectRoot().

    SDK contract (all 9 call sites, e.g. Effects.py:616/784, E1M2.py:3111):
    only ever passed to a particle controller's AttachEffect(root); no method
    is ever called ON it. Controllers store it in _attach_node, which the
    renderer does not read — this object exists for identity/fidelity (one
    stable handle per set, mirroring the NiNodePtr the real engine returns)
    and as the hook for future set-scoped effect lifetime. Deliberately NOT
    a scene-graph node, and deliberately has NO __getattr__ fallback (a
    permissive fallback is how this was silently broken before).
    """
    __slots__ = ("_set",)

    def __init__(self, owner_set):
        self._set = owner_set

    def GetSet(self):
        return self._set

    def __repr__(self):
        return "<SetEffectRoot %r>" % (self._set.GetName(),)


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
        # Lens flares — populated by App.LensFlare_Create(pSet). Stored in
        # insertion order; the renderer aggregator walks this list.
        self._lens_flares: 'list["LensFlare"]' = []
        # Subscriber list for add/remove notifications. See subscribe().
        self._subscribers: list = []
        # Lazily-created SetEffectRoot handle. See GetEffectRoot().
        self._effect_root: "SetEffectRoot | None" = None

    def subscribe(self, callback) -> None:
        """Register a callback notified on every AddObjectToSet /
        RemoveObjectFromSet / DeleteObjectFromSet. Callback signature:
        ``callback(event: str, obj, identifier: str)`` where event is
        ``"added"`` or ``"removed"``.

        Used by the target-menu layer to track ship comings-and-goings
        without polling.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        """Remove a previously-subscribed callback.

        Silent if the callback isn't currently subscribed.
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _fire(self, event: str, obj, identifier: str) -> None:
        # Snapshot the subscriber list so a callback that unsubscribes
        # during dispatch doesn't disturb the iteration.
        for cb in list(self._subscribers):
            try:
                cb(event, obj, identifier)
            except Exception:
                # One broken subscriber must not break the chain. Real
                # production reporting could log this; for the headless
                # shim we swallow and continue.
                pass

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

    def GetDisplayName(self, out_string=None):
        """SDK out-param idiom: ``kName = App.TGString();
        pSet.GetDisplayName(kName)`` (HelmMenuHandlers.py:405 "Entering
        <system>" banner, BridgeHandlers.py:1403 helm tooltip). Derived from
        the set name via SetClass_MakeDisplayName (Systems.TGL lookup, digit
        fallback), matching real Appc. Previously fell through __getattr__ to
        a _RendererStub, which silently left the out-param untouched."""
        from engine.appc.localization import TGString
        name = SetClass_MakeDisplayName(self._name)
        if out_string is not None:
            out_string.SetString(name)
            return out_string
        return TGString(name)

    def GetEffectRoot(self) -> SetEffectRoot:
        """SDK SetClass_GetEffectRoot (App.py:3536) — the node transient VFX
        (debris, explosions, sparks) are parented to. Lazy, cached: one stable
        SetEffectRoot per set for the set's lifetime (NiNodePtr semantics —
        the same handle every call). Previously fell through __getattr__ to a
        fresh _RendererStub per call."""
        if self._effect_root is None:
            self._effect_root = SetEffectRoot(self)
        return self._effect_root

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
        from engine.appc.ships import ShipClass
        from engine.appc import ship_lifecycle
        if isinstance(obj, ShipClass):
            ship_lifecycle.publish_added(obj)
            self._resolve_player_identity_before_broadcast(obj, identifier)
        self._fire("added", obj, identifier)
        # BC broadcasts ET_ENTERED_SET whenever a ship is added to a set. Mission
        # region state machines (E2M2.EnterSet -> TrackPlayer, etc.) hang off it;
        # without it every set-transition-gated beat and viewscreen cutscene stays
        # dead. _containing_set is already set above so EnterSet's
        # GetContainingSet().GetName() resolves. See _broadcast_set_transition.
        self._broadcast_set_transition(obj, entered=True)
        return True

    @staticmethod
    def _resolve_player_identity_before_broadcast(obj, identifier: str) -> None:
        """MissionLib.CreatePlayerShip (SDK, unchanged) always does
        ``loadspacehelper.CreateShip(...)`` — which lands here via
        ``AddObjectToSet`` — *before* calling ``pGame.SetPlayer(pPlayer)``.
        Every SDK call site creates the player's ship with the identifier
        literally ``"player"`` (or ``"Player"`` in QuickBattle.py:2888) —
        confirmed by grepping every ``CreatePlayerShip(`` call in the SDK.

        Region scripts that auto-configure on the player's *initial* set
        entry (e.g. Systems/Starbase12/Starbase12_S.py:EnterSet, which
        enables Bridge's Dock button once Graff's control room is built)
        read ``App.Game_GetCurrentPlayer()`` to confirm the entering ship is
        the player. Because our event dispatch is synchronous (ET_ENTERED_SET
        fires inline, not queued), that read happens *before* the SDK's own
        SetPlayer call — so GetPlayer() is still None, the identity check
        raises AttributeError, and EnterSet bails out silently, leaving the
        Dock button permanently disabled (E6M2 Starbase 12 repro).

        Resolve the player identity here, before the broadcast, so it's
        already correct when EnterSet-style handlers read it. The SDK's own
        later SetPlayer(pPlayer) call becomes a harmless re-assignment to the
        same object (already a tolerated pattern — HelmMenuHandlers.SetPlayer
        already runs once from CreateMenus() and again from ET_SET_PLAYER)."""
        if identifier.lower() != "player":
            return
        import App
        pGame = App.Game_GetCurrentGame()
        if pGame is not None and pGame.GetPlayer() is not obj:
            pGame.SetPlayer(obj)

    def GetObject(self, name: str):
        return self._objects.get(name)

    def RemoveObjectFromSet(self, name: str):
        obj = self._objects.get(name)
        if obj is not None:
            self._fire("removed", obj, name)
            self._broadcast_set_transition(obj, entered=False)
        return self._objects.pop(name, None)

    def DeleteObjectFromSet(self, name: str) -> None:
        obj = self._objects.get(name)
        if obj is not None:
            self._fire("removed", obj, name)
            self._broadcast_set_transition(obj, entered=False)
        self._objects.pop(name, None)

    def _broadcast_set_transition(self, obj, *, entered: bool) -> None:
        """Post ET_ENTERED_SET / ET_EXITED_SET for a ship joining/leaving this
        set, mirroring BC's set-membership broadcasts that drive mission region
        state machines.

        Only ShipClass objects broadcast (BC's ET_*_SET handlers all cast the
        destination via ShipClass_Cast and bail on None — grids, waypoints, and
        characters never trigger region logic). The exit event carries this set's
        name as a CString because ExitSet reads pEvent.GetCString() (the object's
        containing-set may already point at its next set by dispatch time).

        The internal warp-transit set (an engine artifact BC has no equivalent
        for) is suppressed so a warp doesn't inject a spurious region entry/exit
        between the real source and destination sets.
        """
        from engine.appc.ships import ShipClass
        if not isinstance(obj, ShipClass):
            return
        from engine.appc.warp import _WARP_TRANSIT_SET_NAME
        if self._name == _WARP_TRANSIT_SET_NAME:
            return
        import App
        if entered:
            event = App.TGEvent_Create()
            event.SetEventType(App.ET_ENTERED_SET)
        else:
            event = App.TGStringEvent_Create()
            event.SetEventType(App.ET_EXITED_SET)
            event.SetString(self._name)
        event.SetDestination(obj)
        App.g_kEventManager.AddEvent(event)

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
            # Lazy import can raise at interpreter shutdown: GC'd SDK
            # conditions (ConditionInRange.__del__) call RemoveAndDelete →
            # GetProximityManager after sys.meta_path is torn down
            # ("ImportError: sys.meta_path is None"). Degrade to None —
            # the shutdown-time caller (ai.py RemoveAndDelete) null-checks.
            try:
                from engine.appc.planet import ProximityManager
            except ImportError:
                return None
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

    def DeleteCameraFromSet(self, name: str) -> None:
        # Real SDK wires this onto the base SetClass, not just BridgeSet
        # (sdk/Build/scripts/App.py:3598: SetClass.DeleteCameraFromSet =
        # Appc.SetClass_DeleteCameraFromSet). CutsceneCameraEnd calls it on
        # arbitrary space sets, not only the bridge set.
        self.RemoveCameraFromSet(name)

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

    def SetBackgroundModel(self, nif, x=0.0, y=0.0, z=0.0):
        # SDK: comm/bridge sets declare their room geometry here. Recorded so
        # the host's realize_set can load + render it. (Was a _RendererStub no-op.)
        self._background_model = (str(nif), (float(x), float(y), float(z)))

    def GetBackgroundModelNIF(self):
        bm = getattr(self, "_background_model", None)
        return bm[0] if bm else None

    def CreateAmbientLight(self, r, g, b, dimmer, name):
        """SDK signature: pSet.CreateAmbientLight(r, g, b, range_or_dimmer, name).

        The 4th arg is "range" in some calls (MissionLib bridge: 19.0) and
        "dimmer" in others (LoadBridge: 0.7). For ambient light, range is
        meaningless (no falloff), so we treat it as dimmer uniformly,
        clamped to [0, 1]. The clamp protects against MissionLib's
        outlier 19.0 — a literal 19× color multiply would blow the bridge
        out to pure white; saturating at 1× is the most visually sensible
        interpretation absent better evidence. (Decision documented during
        the 2026-05-15 bridge-lighting work; see
        docs/superpowers/specs/2026-05-15-bridge-lighting-materials-design.md
        deferred-work item #9 — the true semantics of the 4th arg are
        still unconfirmed.)
        """
        from engine.appc.lights import Light
        clamped_dimmer = min(max(float(dimmer), 0.0), 1.0)
        self._ambient = (float(r), float(g), float(b), clamped_dimmer)
        light = Light(Light.KIND_AMBIENT, name, r, g, b, clamped_dimmer)
        self._lights.append(light)
        self._lights_by_name[name] = light
        return light

    def GetAmbient(self):
        return getattr(self, "_ambient", None)

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

    # ── Class-typed object queries ──────────────────────────────────────────
    # SDK pattern (AI/Preprocessors.SelectTarget.GetTargetRating, line ~1577):
    #   lpShips = pSet.GetClassObjectList(App.CT_SHIP)
    #   for pShip in lpShips: ...
    # In the original engine, CT_SHIP is an enum tag and GetClassObjectList
    # returns C++ ObjectClass pointers filtered by that tag. In Phase 1 we
    # represent CT_* as Python classes (see App.py around line 224), but
    # CT_SHIP is bound to ShipProperty (the property template, used for the
    # property-set lookup path). The object-iteration path actually wants
    # ShipClass instances. Map the property classes back to their object
    # equivalents on the fly, then isinstance-filter _objects.
    def GetClassObjectList(self, class_type):
        # Lazy import — engine.appc.sets is imported very early and we want
        # to avoid an import cycle through ships/properties at module load.
        from engine.appc.properties import ShipProperty
        from engine.appc.ships import ShipClass
        # CT_SHIP maps to ShipProperty (the property template) but the SDK's
        # object-iteration sites want live ShipClass instances. Translate.
        if class_type is ShipProperty:
            class_type = ShipClass
        if not isinstance(class_type, type):
            return []
        return [obj for obj in self._objects.values() if isinstance(obj, class_type)]

    def GetNebula(self):
        """First CT_NEBULA object in this set, or None (SDK SetClass_GetNebula)."""
        from App import Nebula
        for obj in self._objects.values():
            if isinstance(obj, Nebula):
                return obj
        return None

    def GetObjectList(self):
        """Return all objects in this set as a list.

        Engine-internal helper used by bulk-rebuild paths (e.g.
        STTargetMenu.RebuildShipMenus). The SDK does not expose this on the
        SWIG surface; use GetFirstObject/GetNextObject for SDK-visible
        iteration.
        """
        return list(self._objects.values())

    def GetNavPoints(self):
        """Nav points defined in this set (SDK SetClass_GetNavPoints), consumed
        by HelmMenuHandlers.SetupNavPointsMenuFromSet. Headless models no
        nav-point objects yet, so return an empty list — a real, ITERABLE
        result. Must not fall through __getattr__ (which vends a non-iterable
        _RendererStub and crashes the SDK's `for pNavPoint in lNavPoints` loop,
        a path now reached once Game.SetPlayer fires ET_SET_PLAYER and the Helm
        orbit/nav handlers repopulate)."""
        return []


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

    def GetAllSets(self) -> list:
        """Every registered set (SWIG surface). SDK MissionLib.SetDisplayNames
        and other campaign-wide passes iterate this."""
        return list(self._sets.values())

    def iter_sets(self):
        """(name, SetClass) pairs for every registered set.

        Engine-internal accessor (not on the SWIG surface) used by the host's
        realize_all_sets to enumerate every SDK-created set after mission load.
        """
        return self._sets.items()

    def GetRenderedSet(self) -> "SetClass | None":
        # BC semantics (SDK-facing): while the bridge is visible the bridge
        # IS the rendered set — MissionLib.EndCutscene compares
        # str(GetSet("bridge")) against str(GetRenderedSet()) to decide
        # whether to restore bridge or tactical view (MissionLib.py:790),
        # and E1M1 relies on the same comparison. Engine-internal code that
        # needs the explicit MakeRenderedSet target (exterior lighting,
        # in-space cutscene camera, warp guards) must use
        # get_explicit_rendered_set() instead.
        from engine.appc.top_window import bridge_flag
        if bridge_flag():
            bridge = self._sets.get("bridge")
            if bridge is not None:
                return bridge
        return self.get_explicit_rendered_set()

    def get_explicit_rendered_set(self) -> "SetClass | None":
        """Raw MakeRenderedSet-name lookup, ignoring the bridge-visible
        flag. Engine-internal surface — not part of the SDK App API."""
        if self._rendered_set_name is None:
            return None
        return self._sets.get(self._rendered_set_name)

    def ClearRenderedSet(self) -> None:
        # SDK QuickBattleGame.Initialize calls this before loading the initial
        # episode to drop whatever set was on the viewscreen (e.g. the main
        # menu). Headless: just clear the rendered-set focus; GetRenderedSet
        # then returns None until the next MakeRenderedSet.
        self._rendered_set_name = None

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
