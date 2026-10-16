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
