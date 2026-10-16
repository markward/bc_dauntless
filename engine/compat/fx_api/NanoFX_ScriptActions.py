"""Custom.NanoFXv2.NanoFX_ScriptActions on Dauntless systems
(spec 2026-10-16 §8.4). Script-action functions return 0 (BC: "completed").
CreateControllerFX / SetupController are added in a later task."""
import App

from engine.appc import glow_maps


def DestroyTGSequence(pAction, pSequence):
    destroy = getattr(pSequence, "Destroy", None)
    if callable(destroy):
        destroy()
    return 0


def SetGameSpeed(pAction, fSpeed):
    import SimpleAPI
    SimpleAPI.Speed(fSpeed)
    return 0


def TurnOffLights(pAction, pObject):
    pObject.DisableGlowAlphaMaps()
    return 0


def TurnOnLights(pAction):
    # Global glow off then on: relights every ship (spec §6.3 assumption).
    App.g_kLODModelManager.SetGlowMapsEnabled(0)
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    return 0


def SetShipGlow(pAction, pShip, iOn):
    """Dauntless-internal: one ship's glow on (1) or off (0). Used by
    NanoFX_Lib.CreateFlickerSeq so a flicker never relights other ships."""
    if pShip is None:
        return 0
    if iOn:
        glow_maps.enable_object(pShip)
    else:
        glow_maps.disable_object(pShip)
    return 0


def NanoDamageShip(pAction, pObject, vEmitPos, fRadius, fDamage):
    pObject.AddDamage(vEmitPos, fRadius * 0.4, fDamage)
    return 0


def SetNanoRotation(pAction, pShip, fRotation, fSpeed):
    rnd = App.g_kSystemWrapper.GetRandomNumber
    if fSpeed:
        v = App.TGPoint3()
        v.SetXYZ(fSpeed, fSpeed, fSpeed)
        pShip.SetVelocity(v)
    if fRotation:
        kick = App.TGPoint3()
        kick.SetXYZ((rnd(20001) - 10000) / 10000.0,
                    (rnd(20001) - 10000) / 10000.0,
                    (rnd(20001) - 10000) / 10000.0)
        spin = pShip.GetAngularVelocityTG()
        spin.Add(kick)
        spin.Unitize()
        spin.Scale(fRotation * App.HALF_PI / 180.0)
        pShip.SetAngularVelocity(spin, App.PhysicsObjectClass.DIRECTION_WORLD_SPACE)
    return 0


def _keys(c, colours, alphas, sizes):
    for k in colours:
        c.AddColorKey(*k)
    for k in alphas:
        c.AddAlphaKey(*k)
    for k in sizes:
        c.AddSizeKey(*k)


def SetupController(sType, fSize, fLifeTime, fRed, fGreen, fBlue, fBrightness):
    """A particle controller for one of NanoFX's controller types. Key shapes
    follow NanoFX's documented types so callers' effects keep their timing
    and shape; textures come from the sprite library (spec §7)."""
    r, g, b = fRed / 255.0, fGreen / 255.0, fBlue / 255.0
    rnd = App.g_kSystemWrapper.GetRandomNumber
    if sType == "Plume":
        c = App.AnimTSParticleController_Create()
        s = fSize + rnd(20) * 0.01
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)], [(0.0, s), (1.0, s)])
    elif sType == "Blinker":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, fSize), (1.0, fSize)])
    elif sType == "StaticBlinker":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, r, g, b)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, fSize), (1.0, fSize)])
    elif sType == "Debris":
        life = fLifeTime
        c = App.DebrisParticleController_Create(
            life * (1.1295 - life * 0.00003) + rnd(10) * 0.001, life, 0.005)
        c.SetEmitLifeVariance(life / 4.0)
        k = (rnd(5) + 5) * fSize * 0.01
        _keys(c, [(0.0, 1.0, 1.0, 1.0), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 0.8 + rnd(3) * 0.1), (1.0, 0.0)],
              [(0.0, 0.01), (0.2, k), (0.7, k), (1.0, 0.01)])
    elif sType in ("ExpSparks", "DamageSparks"):
        if sType == "ExpSparks":
            life = 3.0 + rnd(100) * 0.01
            c = App.SparkParticleController_Create(life * 1.1345 + rnd(25) * 0.001, life, 0.005)
            c.SetTailLength(0.05 * (rnd(2) + 1))
        else:
            life = fLifeTime
            c = App.SparkParticleController_Create(life, 1.0, 0.5)
            c.SetTailLength(0.02)
        c.SetEmitLifeVariance(life / 4.0)
        _keys(c, [(0.0, 1.0, 1.0, 0.9), (0.6, 1.0, 0.8, 0.5), (1.0, 0.5, 0.2, 0.0)],
              [(0.0, 1.0), (0.6, 0.5), (1.0, 0.0)],
              [(0.0, 0.01), (0.2, 0.03 * fSize * 0.75), (0.8, 0.05 * fSize * 0.75), (1.0, 0.01)])
    elif sType == "Atmosphere":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, 2.0 * fSize), (1.0, 2.0 * fSize)])
    else:   # "Normal", "Plasma", and anything unknown
        c = App.AnimTSParticleController_Create()
        s = fSize + rnd(10) * 0.01
        _keys(c, [(0.1, 1.0, 1.0, 1.0), (fBrightness, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)], [(0.0, s), (1.0, s)])
    return c


def _emit_source(pEmitFrom, pAttachTo):
    """The object to emit from. A stub (e.g. the result of
    App.TGModelUtils_CastNodeToAVObject, which stays a stub so stock effects
    are unchanged) or None falls back to the owner of pAttachTo when that is
    an object's GetNode() handle; a set effect root means world space."""
    from engine.appc.objects import _ObjectNodeRef
    if pEmitFrom is not None and not isinstance(pEmitFrom, App._Stub):
        return pEmitFrom
    if isinstance(pAttachTo, _ObjectNodeRef):
        return pAttachTo._owner()      # a weakref to the owning object
    return None


def CreateControllerFX(sFile, pEmitFrom, pAttachTo, fSize=1.0, vEmitPos=None,
                       vEmitDir=None, bInheritVel=0, bDetach=0, fFrequency=0.2,
                       fLifeTime=0.1, fEmitVel=None, fVariance=None, fDamping=None,
                       vGravity=None, iTiming=32, sType="Normal", fRed=255.0,
                       fGreen=255.0, fBlue=255.0, fBrightness=0.6):
    """NanoFX's one-call effect builder (spec 2026-10-16 §8.4). `iTiming` is
    in 1/15 s; `fBrightness` is the TIME of the tint colour key. `vGravity`
    and `bDetach` are accepted and ignored (spec §8.4)."""
    c = SetupController(sType, fSize, fLifeTime, fRed, fGreen, fBlue, fBrightness)
    emit_life = iTiming / 15.0
    if sType not in ("ExpSparks", "DamageSparks", "Debris"):
        c.SetEmitLife(emit_life)
        c.SetEmitFrequency(fFrequency)
        c.SetEffectLifeTime(emit_life + fLifeTime)
    c.CreateTarget(sFile)
    if fEmitVel:
        c.SetEmitVelocity(fEmitVel)
    if fVariance:
        c.SetAngleVariance(fVariance)
        c.SetEmitRadius(fSize / 4.0)
    if fDamping:
        c.SetDamping(fDamping)
    if sType in ("Normal", "Plasma", "Blinker", "StaticBlinker", "Atmosphere"):
        c.SetTargetAlphaBlendModes(0, 0 if sType != "Atmosphere" else 7)
    source = _emit_source(pEmitFrom, pAttachTo)
    if source is not None:
        c.SetEmitFromObject(source)
    c.SetEmitPositionAndDirection(vEmitPos if vEmitPos is not None else App.NiPoint3(0.0, 0.0, 0.0),
                                  vEmitDir if vEmitDir is not None else App.NiPoint3(0.0, 0.0, 0.0))
    c.SetInheritsVelocity(bInheritVel)
    c.SetDetachEmitObject(bDetach)
    c.AttachEffect(pAttachTo)
    return App.EffectAction_Create(c)
