"""Custom.NanoFXv2.NanoFX_Lib -- NanoFX 2.0's public helper API rebuilt on
Dauntless systems (spec 2026-10-16 §8.2). The import name is fixed by the
mods that call it; nothing here is NanoFX's code."""
import App

_ACTIONS = "Custom.NanoFXv2.NanoFX_ScriptActions"

CONST_MAXFLICKERS = 2
g_FlickerControl = 0
g_LightsOff = []

# NanoFX's race colour table (0-255), as data.
_RACE_RGB = {
    "Federation": (55.0, 120.0, 255.0),
    "Klingon":    (255.0, 20.0, 0.0),
    "Romulan":    (0.0, 248.0, 130.0),
    "Cardassian": (255.0, 200.0, 0.0),
    "Ferengi":    (255.0, 180.0, 0.0),
    "Kessok":     (182.0, 0.0, 201.0),
    "Dominion":   (182.0, 0.0, 201.0),
    "Borg":       (0.0, 248.0, 150.0),
}
_DEFAULT_RGB = (155.0, 120.0, 255.0)

_COLOUR_HOOKS = {
    "ExpFX": "OverrideExpFXColor",
    "PlasmaFX": "OverridePlasmaFXColor",
    "WarpFX": "OverrideWarpFXColor",
}


def ControlFlickers(pAction, iNum):
    global g_FlickerControl
    g_FlickerControl = g_FlickerControl + iNum
    return 0


def _action(func, *args):
    return App.TGScriptAction_Create(_ACTIONS, func, *args)


def CreateRotationSeq(pShip, fRotation=None, fSpeed=None):
    seq = App.TGSequence_Create()
    if fRotation is not None:
        fRotation = (App.g_kSystemWrapper.GetRandomNumber(int(fRotation)) + fRotation) * 0.01
    seq.AddAction(_action("SetNanoRotation", pShip, fRotation, fSpeed))
    return seq


def CreateFlickerSeq(pShip, fTotalTime, fFlickerSpeed=0.2, sStatus="On"):
    """Toggle pShip's glow every fFlickerSpeed s (+0..0.1 s jitter), ending on
    or off per sStatus. At most CONST_MAXFLICKERS run at once; beyond that an
    empty sequence comes back, as NanoFX did."""
    seq = App.TGSequence_Create()
    if g_FlickerControl >= CONST_MAXFLICKERS:
        return seq
    rnd = App.g_kSystemWrapper.GetRandomNumber
    t = 0.0
    while t < fTotalTime - 0.1:
        off_at = t + rnd(100) * 0.001
        seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, 0), off_at)
        seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, 1),
                      off_at + fFlickerSpeed * 0.5)
        t = t + fFlickerSpeed
    final = 0 if sStatus == "Off" else 1
    seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, final),
                  float(fTotalTime))
    name = pShip.GetName() if pShip is not None else None
    # g_LightsOff = ships whose lights are currently left dark.
    if name is not None:
        if final == 0 and name not in g_LightsOff:
            g_LightsOff.append(name)
        if final == 1 and name in g_LightsOff:
            g_LightsOff.remove(name)
    ControlFlickers(None, 1)
    seq.AddAction(App.TGScriptAction_Create(__name__, "ControlFlickers", -1),
                  float(fTotalTime))
    return seq


def CreateSpecialFXSeq(pShip, pEvent, sFXType, bPlay=0):
    """None for every type: NanoFX's own plasma vent returned None on most
    calls, and its other types are effect modules we do not run."""
    return None


def _leaf(pShip):
    try:
        return str(pShip.GetScript()).split(".")[-1]
    except Exception:
        return ""


def _shipdef_for(leaf):
    if not leaf:
        return None
    from engine.foundation.shipdef import all_definitions
    from engine.foundation import shipdef_overrides
    wanted = leaf.lower()
    for d in list(all_definitions()) + list(shipdef_overrides.stock_definitions()):
        if str(getattr(d, "shipFile", "") or "").lower() == wanted:
            return d
    return None


def GetSpeciesName(pShip):
    leaf = _leaf(pShip)
    if not leaf:
        return "Default"
    from engine import ship_catalog
    entry = ship_catalog.entry(leaf)
    if entry is not None and getattr(entry, "species", None):
        return str(entry.species)
    d = _shipdef_for(leaf)
    race = getattr(d, "race", None) if d is not None else None
    if race:
        return getattr(race, "name", str(race))
    return "Default"


def GetOverrideColor(pShip, sEffectType):
    attr = _COLOUR_HOOKS.get(sEffectType)
    d = _shipdef_for(_leaf(pShip))
    if attr is None or d is None:
        return None
    hook = d.__dict__.get(attr)
    if hook is None:
        return None
    return hook(None)


def GetRaceTextureColor(sRace):
    return _RACE_RGB.get(sRace, _DEFAULT_RGB)


_warned_planets = set()


def CreateAtmosphereFX(pPlanet, sNifPath="data/models/environment/planet.nif",
                       sTexturePath="Class-M"):
    """Request an atmosphere for pPlanet from the planet-class preset named
    by sTexturePath ("Class-M", "Class-H", ...). Creates no objects: NanoFX's
    sun-shell layers are not built (spec 2026-10-16 §8.3)."""
    from engine.planets import atmosphere
    try:
        set_name = pPlanet.GetContainingSet().GetName()
        obj_name = pPlanet.GetName()
    except Exception:
        set_name = obj_name = None
    if not set_name or not obj_name:
        try:
            who = pPlanet.GetName()
        except Exception:
            who = repr(pPlanet)
        if who not in _warned_planets:
            _warned_planets.add(who)
            import sys
            sys.stderr.write("[NanoFX_Lib] CreateAtmosphereFX: planet %r has no "
                             "containing set or name; no atmosphere requested\n" % (who,))
        return
    preset = atmosphere.class_preset(sTexturePath)
    if preset is not None and set_name and obj_name:
        atmosphere.request(set_name, obj_name, preset)
