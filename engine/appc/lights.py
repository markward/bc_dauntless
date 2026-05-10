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
        light = self._make_light(Light.KIND_DIRECTIONAL, r, g, b, dimmer)
        # Row 1 of the world rotation is the placement's forward axis after
        # AlignToVectors. BC's directional light shines in this direction;
        # the renderer wants direction-toward-light, which the host loop
        # negates at marshalling time.
        rot = self.GetWorldRotation()
        fwd = rot.GetRow(1)
        light._direction_world = (fwd.x, fwd.y, fwd.z)

    def _make_light(self, kind, r, g, b, dimmer):
        light = Light(kind, self.GetName(), r, g, b, dimmer)
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
