"""Phase-1 light objects: Light + LightPlacement.

BC scripts call:
    kThis = App.LightPlacement_Create(name, set_name, parent)
    kThis.SetTranslateXYZ(x, y, z)
    kThis.AlignToVectors(forward, up)
    kThis.ConfigAmbientLight(r, g, b, dimmer)        # or ConfigDirectionalLight
    kThis.Update(0)

LightPlacement inherits PlacementObject (which inherits ObjectClass) so
SetTranslateXYZ / AlignToVectors / Update / GetWorldRotation come for free.
ConfigAmbientLight / ConfigDirectionalLight materialise a Light into the
containing SetClass._lights list and _lights_by_name index.
"""
from engine.appc.objects import ObjectClass
from engine.appc.placement import PlacementObject


class Light(ObjectClass):
    """Phase-1 light object stored in SetClass._lights and returned by
    GetLight(). Inherits ObjectClass for two reasons:
      1. SDK code treats lights as objects (set membership, naming).
      2. Save/load (deferred) round-trips Light state via the same
         pickling pathway as other Appc objects.
    The unused event-handler / object-id machinery on ObjectClass is
    incidental cost that pays off when those features land.
    """
    KIND_AMBIENT = "ambient"
    KIND_DIRECTIONAL = "directional"

    def __init__(self, kind, name, r, g, b, dimmer):
        super().__init__()
        self.SetName(name)
        self._kind = kind
        self._color = (float(r), float(g), float(b))
        self._dimmer = float(dimmer)
        # Overwritten by LightPlacement.ConfigDirectionalLight or by
        # SetClass.CreateDirectionalLight; harmless default for ambients.
        self._direction_world = (0.0, 1.0, 0.0)
        # Set when this Light was materialised through a LightPlacement;
        # direction_world() then re-reads the placement's forward axis on
        # every call so post-Config rotation changes (e.g. a second
        # AlignToVectors, or animation controllers in future work) flow
        # through. None for the 8-arg pSet.CreateDirectionalLight path,
        # where direction is given directly and no placement exists.
        self._placement: "LightPlacement | None" = None

    def direction_world(self):
        """Resolve current world-space 'where the light shines' direction.

        For LightPlacement-backed lights, queries the placement's
        rotation matrix on each call. For direct-creation lights, returns
        the static value provided at construction.
        """
        if self._placement is not None:
            rot = self._placement.GetWorldRotation()
            fwd = rot.GetRow(1)
            return (fwd.x, fwd.y, fwd.z)
        return self._direction_world

    def AddIlluminatedObject(self, _obj):
        # Phase 1 doesn't filter per-object lighting; every light affects
        # every object in its set. SDK callers chain the result; returning
        # None is fine (their next call would be on the receiver, which
        # they discard via `pLight = pSet.GetLight(...)` reassignment).
        return None


class LightPlacement(PlacementObject):
    def ConfigAmbientLight(self, r, g, b, dimmer):
        self._make_light(Light.KIND_AMBIENT, r, g, b, dimmer)

    def ConfigDirectionalLight(self, r, g, b, dimmer):
        # No need to snapshot the forward at this moment: Light._placement
        # points back at us, and Light.direction_world() re-reads
        # GetWorldRotation().GetRow(1) on every call. This means later
        # AlignToVectors invocations or animation controllers attached to
        # the placement flow through to the renderer without any extra
        # bookkeeping at the call sites.
        self._make_light(Light.KIND_DIRECTIONAL, r, g, b, dimmer)

    def _make_light(self, kind, r, g, b, dimmer):
        light = Light(kind, self.GetName(), r, g, b, dimmer)
        light._placement = self
        if self._containing_set is not None:
            self._containing_set._lights.append(light)
            self._containing_set._lights_by_name[self.GetName()] = light
        return light


def LightPlacement_Create(name, set_name, parent=None):
    p = LightPlacement()
    p.SetName(name)
    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        s.AddObjectToSet(p, name)  # populates p._containing_set
    return p


# Maximum directional lights the renderer (opaque.frag) can consume per
# frame. Mirrors `renderer::Lighting::MaxDirectionals` in the C++ side.
MAX_DIRECTIONALS = 4


def aggregate_for_renderer(pSet, default_ambient, default_directionals):
    """Collapse SetClass._lights into (ambient_rgb, [directionals × ≤4]).

    Pure: takes a SetClass (or None) plus the caller's chosen defaults,
    returns the tuple the renderer wants. Lives next to Light /
    LightPlacement because the projection from BC's storage to the
    renderer's data shape is light-domain knowledge, not host-loop
    sequencing.

    Ambient: last-wins across configured ambients, color × dimmer.
    Directionals: in insertion order, capped at MAX_DIRECTIONALS (with a
        per-set one-shot warning when more were configured), filtering
        out zero-length directions. Each is
            ((dx_to_light, dy_to_light, dz_to_light), (r, g, b))
    Returns the supplied defaults when pSet is None or has no usable
    lights after filtering.
    """
    if pSet is None:
        return default_ambient, default_directionals

    ambient: tuple = (0.0, 0.0, 0.0)
    found_ambient = False
    directionals: list = []
    overflowed = False

    for light in pSet._lights:
        if light._kind == Light.KIND_AMBIENT:
            r, g, b = light._color
            d = light._dimmer
            ambient = (r * d, g * d, b * d)
            found_ambient = True
        elif light._kind == Light.KIND_DIRECTIONAL:
            dx, dy, dz = light.direction_world()
            mag2 = dx * dx + dy * dy + dz * dz
            if mag2 < 1e-12:
                continue  # zero-vector guard
            # BC forward = direction light shines; shader wants TOWARD light.
            dir_to_light = (-dx, -dy, -dz)
            r, g, b = light._color
            dim = light._dimmer
            color = (r * dim, g * dim, b * dim)
            if len(directionals) < MAX_DIRECTIONALS:
                directionals.append((dir_to_light, color))
            else:
                overflowed = True

    if overflowed and not getattr(pSet, "_light_overflow_warned", False):
        # Once-per-set warning. The aggregation runs every tick, so an
        # unconditional print would flood stdout at 60Hz. The boolean is
        # attached to the SetClass so set-level reload (re-Initialize)
        # creates a fresh SetClass and re-arms the warning.
        print(f"[lights] dropped extra directional lights from set "
              f"{pSet.GetName()!r} (>{MAX_DIRECTIONALS} configured)",
              flush=True)
        pSet._light_overflow_warned = True

    if not found_ambient and not directionals:
        # Active set was selected but had only filtered-out junk; treat as
        # "no usable lights" → defaults.
        return default_ambient, default_directionals

    return ambient, directionals


def _resolve_bridge_set():
    """Return the bridge SetClass, or None.

    BC's convention (sdk/Build/scripts/LoadBridge.py:64): the bridge set
    is registered under the literal name "bridge" via
    g_kSetManager.AddSet(pBridgeSet, "bridge"). LoadBridge.py is the
    only producer; the Phase 1 LoadBridge shim mirrors this. There is no
    per-ship-class disambiguation at this layer — bridge variants
    (DBridge, FBridge, ...) are selected upstream when LoadBridge runs.
    """
    import App
    return App.g_kSetManager.GetSet("bridge")


def aggregate_bridge_for_renderer(default_ambient, default_directionals):
    """Bridge-pass counterpart of aggregate_for_renderer.

    Pulls lighting from the bridge SetClass (resolved by name) so the
    bridge interior renders against its own authored ambient, not the
    space scene's. Returns (ambient, directionals) in the same shape as
    aggregate_for_renderer, so the binding signature is identical.

    Stock BC bridges author only CreateAmbientLight (no directionals);
    aggregate_for_renderer's directional handling is mechanically
    correct for the bridge case too, so we reuse it without modification.
    """
    pSet = _resolve_bridge_set()
    return aggregate_for_renderer(pSet, default_ambient, default_directionals)
