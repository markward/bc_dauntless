import math
from engine.core import stub_telemetry
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGBoolEvent, TGBoolEvent_Create,
    TGKeyboardEvent, ET_KEYBOARD_EVENT,
    WeaponHitEvent, ET_WEAPON_HIT, ET_WARP_BUTTON_PRESSED,
    ET_TORPEDO_RELOAD, ET_TORPEDO_FIRED,
    ET_WEAPON_FIRED, ET_WEAPON_FIRE_FAILED, ET_TORPEDO_AMMO_CONSUMED,
    ET_FRIENDLY_FIRE_DAMAGE, ET_FRIENDLY_FIRE_REPORT, ET_FRIENDLY_FIRE_GAME_OVER,
    ObjectExplodingEvent, ObjectExplodingEvent_Create,
    TGEventHandlerObject, TGEventManager,
    TGPythonInstanceWrapper,
    ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
)
from engine.appc import input as _input_consts   # keyboard WC_/KY_ table source
from engine.appc.input import (
    TGInputManager, KeyboardBinding,
    WC_LBUTTON, WC_RBUTTON, WC_MBUTTON,
    KY_LBUTTON, KY_RBUTTON, KY_MBUTTON,
    WC_F1, WC_F2, WC_F3, WC_F4, WC_F5,
    KY_F1, KY_F2, KY_F3, KY_F4, KY_F5,
    WC_F, WC_G, WC_X,
    KY_F, KY_G, KY_X,
    KS_KEYDOWN, KS_KEYUP, KS_KEYREPEAT, KS_NORMAL,
    init_input_pipeline, register_input_handlers,
)
from engine.appc.windows import (
    TacticalControlWindow,
    SubtitleWindow, SubtitleWindow_Cast,
    STStylizedWindow_CreateW,
)
from engine.appc.tg_ui.widgets import (
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
    TGFrame, TGFrame_Create, TGFrame_Cast,
    STTiledIcon, STTiledIcon_Create, STTiledIcon_Cast,
    WC_BACKSPACE, WC_TAB, WC_LINEFEED, WC_RETURN, WC_SPACE, WC_CURSOR,
)
from engine.appc.tg_ui import layout as _tg_ui_layout


class TGUIObject:
    """SDK-referenced anchor constants for AlignTo (widget.AlignTo(other,
    App.TGUIObject.ALIGN_BL, App.TGUIObject.ALIGN_UL)). Bound directly to
    engine.appc.tg_ui.layout's ALIGN_* sentinels — the single source of
    truth the layout resolver's ANCHOR_FRACTIONS/AlignTo is keyed on — so
    real SDK AlignTo calls resolve real anchors instead of both arguments
    collapsing to the int()==0 _NamedStub stub (App's module __getattr__
    would otherwise hand back a fresh stub for TGUIObject itself)."""
    ALIGN_UL = _tg_ui_layout.ALIGN_UL
    ALIGN_UC = _tg_ui_layout.ALIGN_UC
    ALIGN_UR = _tg_ui_layout.ALIGN_UR
    ALIGN_CL = _tg_ui_layout.ALIGN_CL
    ALIGN_CC = _tg_ui_layout.ALIGN_CC
    ALIGN_CR = _tg_ui_layout.ALIGN_CR
    ALIGN_BL = _tg_ui_layout.ALIGN_BL
    ALIGN_BC = _tg_ui_layout.ALIGN_BC
    ALIGN_BR = _tg_ui_layout.ALIGN_BR


from engine.appc.tg_ui.managers import (
    g_kFontManager, g_kIconManager, g_kImageManager,
    g_kFocusManager, g_kRootWindow,
)
from engine.appc.tg_ui.graphics_mode import (
    GraphicsModeInfo, GraphicsModeInfo_GetCurrentMode,
    TGUIModule_PixelAlignValue,
)
from engine.appc.tg_ui.st_widgets import (
    STCharacterMenu, STCharacterMenu_CreateW,
    STToggle, STToggle_CreateW, STToggle_Cast,
    STWarpButton, STWarpButton_CreateW, STWarpButton_Cast,
    SortedRegionMenu, SortedRegionMenu_CreateW, SortedRegionMenu_Cast,
    SortedRegionMenu_SetWarpButton, SortedRegionMenu_GetWarpButton,
    SortedRegionMenu_SetPauseSorting, SortedRegionMenu_ClearSetCourseMenu,
    SortedRegionMenu_IsSortingPaused,
    STRoundedButton, STRoundedButton_CreateW, STRoundedButton_Cast,
    STSubPane, STSubPane_Create, STSubPane_Cast,
    STButton_Cast, STStylizedWindow_Cast,
)
from engine.appc.tg_ui.eng_power import (
    EngPowerCtrl, EngPowerCtrl_Create, EngPowerCtrl_GetPowerCtrl, EngPowerCtrl_Cast,
    EngPowerDisplay, EngPowerDisplay_Create, EngPowerDisplay_GetPowerDisplay,
    EngPowerDisplay_Cast,
)
from engine.appc.radar import (
    RadarDisplay_Create, RadarDisplay_Cast,
    RadarScope_Create, RadarBlip_Create,
    _RadarDisplay as RadarDisplay,
    _RadarScope as RadarScope,
    _RadarBlip as RadarBlip,
)
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager
from engine.appc.math import (
    TGPoint3, TGMatrix3,
    TGPoint3_GetModelForward, TGPoint3_GetModelBackward,
    TGPoint3_GetModelUp, TGPoint3_GetModelDown,
    TGPoint3_GetModelRight, TGPoint3_GetModelLeft,
)
from engine.appc.objects import (
    ObjectClass, PhysicsObjectClass, DamageableObject,
    ObjectGroup, ObjectGroupWithInfo,
    ObjectGroup_ForceToGroup, ObjectGroup_FromModule, ObjectGroupWithInfo_Cast,
    ObjectClass_Cast, PhysicsObjectClass_Cast, DamageableObject_Cast,
    ObjectClass_GetObject, ObjectClass_GetObjectByID,
    PhysicsObjectClass_GetObject,
    IsNull,
)
from engine.appc.sets import (
    SetClass, SetManager, SetClass_Create, SetClass_GetNull,
    SetClass_MakeDisplayName,
)
from engine.appc.bridge_set import (
    BridgeSet,
    BridgeSet_Create,
    BridgeSet_Cast,
    BridgeObjectClass,
    BridgeObjectClass_Create,
    ViewScreenObject,
    ViewScreenObject_Create,
    ZoomCameraObjectClass,
    ZoomCameraObjectClass_Create,
    ZoomCameraObjectClass_GetObject,
    ModelManager,
    CameraObjectClass,
    CameraObjectClass_Create,
    CameraObjectClass_CreateFromNiCamera,
    CameraObjectClass_Cast,
    CameraObjectClass_GetObject,
)
from engine.appc.camera_modes import CameraMode_Create
from engine.appc.placement import (
    PlacementObject, Waypoint, Waypoint_Create,
    Waypoint_Cast, PlacementObject_Cast,
    PlacementObject_Create,
    PlacementObject_GetObjectBySetName, PlacementObject_GetObject,
)
from engine.appc.lights import (
    Light, LightPlacement, LightPlacement_Create,
)
from engine.appc.backdrops import (
    Backdrop, StarSphere, BackdropSphere,
    StarSphere_Create, BackdropSphere_Create,
)
from engine.appc.ships import (
    ShipClass, ShipClass_Create, ShipClass_GetObject,
    ShipClass_Cast, ShipClass_GetObjectByID,
)
from engine.appc.actions import (
    TGAction, TGNullAction, TGAction_CreateNull, TGAction_Cast,
    TGScriptAction, TGScriptAction_Create,
    TGSequence, TGSequence_Create, TGSequence_Cast,
    TGTimedAction, TGSoundAction, TGSoundAction_Create,
    TGAnimAction, TGAnimAction_Create,
    TGAnimPosition, TGAnimPosition_Create,
    SubtitleAction, SubtitleAction_Create,
    TGActionManager,
    TGActionManager_RegisterAction, TGActionManager_UnregisterAction,
    TGActionManager_FindAction, TGActionManager_SkipEvents,
    TGCreditAction, TGCreditAction_Create,
    TGCreditAction_SetDefaultColor, TGCreditAction_GetDefaultColor,
    TGConditionAction, TGConditionAction_Create,
    TGObjPtrEvent, TGObjPtrEvent_Create,
    TGObject_GetTGObjectPtr,
)
from engine.appc.warp import (
    WarpSequence_Create,
    ChangeRenderedSetAction_Create,
    ChangeRenderedSetAction_CreateFromSet,
)
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, g_kSoundManager, TGSound_Create,
    TGSoundRegion, TGSoundRegion_GetRegion, TGSoundRegion_Create,
)
from engine.core.game import (
    Game, Episode, Mission, Game_GetCurrentGame, _set_current_game,
    Game_GetDifficulty, Game_SetDifficulty,
    Game_SetDifficultyMultipliers, Game_SetDefaultDifficultyMultipliers,
    Game_GetOffensiveDifficultyMultiplier, Game_GetDefensiveDifficultyMultiplier,
    Game_GetCurrentPlayer, Game_SetCurrentPlayer,
)
from engine.appc.localization import TGLocalizationManager, TGLocalizationDatabase, TGString, _TGString
from engine.appc.var_manager import TGVarManager
from engine.appc.save_load import SaveLoadManager
from engine.appc.config_mapping import TGConfigMapping
from engine.appc.lod_models import LODModelManager
from engine.appc.animation_manager import AnimationManager
from engine.appc.debug import (
    CPyDebug, TGProfilingInfo,
    TGProfilingInfo_EnableProfiling, TGProfilingInfo_DisableProfiling,
    TGProfilingInfo_IsProfilingEnabled,
    TGProfilingInfo_StartTiming, TGProfilingInfo_StopTiming,
    TGProfilingInfo_GetTotalTime, TGProfilingInfo_ResetTimings,
)
# SDK callers use TGProfilingInfo_EndTiming; we already have _StopTiming.
TGProfilingInfo_EndTiming = TGProfilingInfo_StopTiming
from engine.appc.planet import (
    Planet, Sun,
    Planet_Create, Sun_Create, Planet_GetObject, Planet_Cast,
    ProximityManager,
)
from engine.appc.lens_flare import LensFlare, LensFlare_Create
from engine.appc.characters import (
    CharacterClass, CharacterClass_Create, CharacterClass_CreateNull,
    CharacterClass_Cast, CharacterClass_GetObject,
    CharacterClass_SetVolumeForLineType, CharacterClass_GetVolumeForLineType,
    STButton, STMenu, STTopLevelMenu,
    STButton_Create, STButton_CreateW, STMenu_Cast, STMenu_Create, STMenu_CreateW,
    STTopLevelMenu_CreateW, STTopLevelMenu_Cast, STTopLevelMenu_CreateNull,
    STTopLevelMenu_GetOpenMenu,
)
# STButton size-to-text flag — TacticalMenuHandlers uses App.STBSF_SIZE_TO_TEXT.
STBSF_SIZE_TO_TEXT = STButton.STBSF_SIZE_TO_TEXT
from engine.appc.target_menu import (
    STSubsystemMenu, STSubsystemMenu_Cast,
    STComponentMenu, STComponentMenu_Cast,
    STTargetMenu,
    STTargetMenu_CreateW, STTargetMenu_GetTargetMenu,
    _reset_target_menu_singleton,
    wire_to_bridge_set, unwire_from_bridge_set,
)
from engine.sdk_ui.widgets.ship_display import (
    ShipDisplay_Create, ShipDisplay_Cast,
    ShieldsDisplay_Create, DamageDisplay_Create, STFillGauge_Create,
)
from engine.appc.ai import (
    ArtificialIntelligence,
    TGCondition, TGConditionHandler,
    ConditionScript, ConditionScript_Create, ConditionScript_Cast,
    PlainAI, PlainAI_Create,
    PriorityListAI, PriorityListAI_Create,
    SequenceAI, SequenceAI_Create,
    RandomAI, RandomAI_Create,
    PreprocessingAI, PreprocessingAI_Create, PreprocessingAI_Cast,
    ConditionalAI, ConditionalAI_Create,
    ConditionEventCreator,
    BuilderAI, BuilderAI_Create,
    ProximityCheck, ProximityCheck_Create, ProximityCheck_CreateWithEvent,
    CharacterAction, CharacterAction_Create, CharacterAction_CreateByName,
    CharacterAction_Cast,
    CSP_LOW, CSP_NORMAL, CSP_HIGH,
    CSP_SPONTANEOUS, CSP_MISSION_CRITICAL,
    ArtificialIntelligence_GetAIByID,
)
from engine.appc.time_slice import (
    TimeSliceProcess, PythonMethodProcess, g_kAIManager,
)
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, WeaponSystem,
    TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
    TorpedoTube,
    SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
    WarpEngineSubsystem_GetWarpEffectTime, WarpEngineSubsystem_SetWarpEffectTime,
    ShieldSubsystem,
    CloakingSubsystem,
)
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.properties import (
    TGModelProperty,
    TGModelPropertyManager, TGModelPropertySet,
    PositionOrientationProperty,
    ObjectEmitterProperty,
    EngineGlowProperty,
    SubsystemProperty,
    HullProperty, PowerProperty,
    WeaponProperty, EnergyWeaponProperty,
    PhaserProperty, PulseWeaponProperty, TractorBeamProperty,
    TorpedoTubeProperty,
    PoweredSubsystemProperty,
    ShieldProperty, SensorProperty, RepairSubsystemProperty,
    WeaponSystemProperty, TorpedoSystemProperty,
    ShipProperty,
    EngineProperty, ImpulseEngineProperty, WarpEngineProperty,
    CloakingSubsystemProperty,
    PositionOrientationProperty_Create,
    HullProperty_Create, PowerProperty_Create,
    PhaserProperty_Create, PulseWeaponProperty_Create,
    TractorBeamProperty_Create, TorpedoTubeProperty_Create,
    ShieldProperty_Create, SensorProperty_Create,
    RepairSubsystemProperty_Create, TorpedoSystemProperty_Create,
    ShipProperty_Create,
    EngineProperty_Create, ImpulseEngineProperty_Create, WarpEngineProperty_Create,
    WeaponSystemProperty_Create,
    CloakingSubsystemProperty_Create,
    ObjectEmitterProperty_Create, ObjectEmitterProperty_Cast,
)
from engine.appc.particles import (
    AnimTSParticleController_Create,
    SparkParticleController_Create,
    EffectAction_Create,
    ExplosionPlumeController_Create,
    EffectController,
    EffectController_GetEffectLevel,
)

# ── App.CT_* class-type constants ─────────────────────────────────────────────
# In the original BC engine these are integer enum tags. In the SDK they reach
# three call sites:
#   1. pPropSet.GetPropertiesByType(CT_X)   — isinstance() over property templates
#   2. pSet.GetClassObjectList(CT_X)        — set queries by object class
#   3. pObject.IsTypeOf(CT_X)               — runtime type check
# isinstance() requires a real type, so every CT_X must be a class. The
# property-set call site is the one that crashes today; the others are
# currently stubbed but kept correct here so future implementations of
# GetClassObjectList / IsTypeOf get real classes for free.
#
# Property-type and subsystem-type CT_* map to the matching *Property class —
# property sets hold templates, not live subsystems. Object-type CT_* map to
# their ObjectClass subclass. For object types not yet implemented in the
# engine, a minimal placeholder class is defined inline; when a real
# implementation lands the binding here updates to point at it.

class Nebula(ObjectClass): pass
class Torpedo(ObjectClass): pass
class Debris(ObjectClass): pass
class AsteroidField(ObjectClass): pass
class AsteroidTile(ObjectClass): pass

class GridClass(ObjectClass):
    # SDK boilerplate calls Create → AddObjectToSet → SetHidden(1) on every
    # region; nothing ever sets line length, step, position, or un-hides.
    # See docs/superpowers/deferred/2026-05-18-gridclass-debug-overlay.md.
    def __init__(self):
        ObjectClass.__init__(self)
        self._hidden = True
        self._line_length = 0.0
        self._step = 0.0

    def SetLineLength(self, length): self._line_length = float(length)
    def GetLineLength(self): return self._line_length
    def SetStep(self, step): self._step = float(step)
    def GetStep(self): return self._step
    def UpdatePosition(self, *args, **kwargs): pass
    def Update(self, *args, **kwargs): pass

Grid = GridClass  # legacy alias for CT_GRID and any code reading the old name

def GridClass_Create(): return GridClass()

class Placement(ObjectClass): pass
class MultiplayerGame: pass

# Property / subsystem templates
CT_SUBSYSTEM_PROPERTY            = SubsystemProperty
CT_POSITION_ORIENTATION_PROPERTY = PositionOrientationProperty
CT_OBJECT_EMITTER_PROPERTY       = ObjectEmitterProperty
CT_HULL_SUBSYSTEM                = HullProperty
CT_POWER_SUBSYSTEM               = PowerProperty
CT_SHIELD_SUBSYSTEM              = ShieldProperty
CT_SENSOR_SUBSYSTEM              = SensorProperty
CT_REPAIR_SUBSYSTEM              = RepairSubsystemProperty
CT_IMPULSE_ENGINE_SUBSYSTEM      = ImpulseEngineProperty
CT_WARP_ENGINE_SUBSYSTEM         = WarpEngineProperty
CT_CLOAKING_SUBSYSTEM            = CloakingSubsystemProperty
CT_PHASER_SYSTEM                 = PhaserProperty
CT_PULSE_WEAPON_SYSTEM           = PulseWeaponProperty
CT_TORPEDO_SYSTEM                = TorpedoSystemProperty
CT_TRACTOR_BEAM_SYSTEM           = TractorBeamProperty
CT_WEAPON_SYSTEM                 = WeaponSystemProperty
CT_WEAPON                        = WeaponProperty
CT_ENERGY_WEAPON                 = EnergyWeaponProperty
CT_SHIP                          = ShipProperty
CT_SHIP_SUBSYSTEM                = ShipSubsystem

# Object classes (set / runtime type tags)
CT_OBJECT            = ObjectClass
CT_DAMAGEABLE_OBJECT = DamageableObject
CT_CHARACTER         = CharacterClass
CT_BACKDROP          = Backdrop
CT_PROXIMITY_CHECK   = ProximityCheck
CT_PLANET            = Planet
CT_SUN               = Sun
CT_NEBULA            = Nebula
CT_TORPEDO           = Torpedo
CT_DEBRIS            = Debris
CT_ASTEROID_FIELD    = AsteroidField
CT_ASTEROID_TILE     = AsteroidTile
CT_GRID              = Grid
CT_PLACEMENT         = Placement
CT_MULTIPLAYER_GAME  = MultiplayerGame
CT_ST_MENU           = STMenu
CT_SORTED_REGION_MENU = SortedRegionMenu

# MetaNebula factories — imported here (not at the top) so that the
# `Nebula` base class and `CT_NEBULA` tag above are already bound when
# engine.appc.nebula does `from App import Nebula`, avoiding a circular import.
from engine.appc.nebula import MetaNebula, MetaNebula_Create, Nebula_Cast, MetaNebula_Cast

# AsteroidField factories — imported here (after the bare `AsteroidField` base
# class and `CT_ASTEROID_FIELD` tag are bound) so engine.appc.asteroid_field can
# do `from App import AsteroidField` without a circular import. The richer
# subclass is an instance of the base, so CT_ASTEROID_FIELD isinstance checks
# (GetClassObjectList) and AsteroidField_Cast still match.
from engine.appc.asteroid_field import (
    AsteroidField, AsteroidFieldPlacement_Create, AsteroidField_Cast)

# ── Shield SDK surface ────────────────────────────────────────────────────────
# SDK calls App.ShieldClass.NUM_SHIELDS / .FRONT_SHIELDS etc.  Map the class
# name onto the engine's ShieldSubsystem.
ShieldClass = ShieldSubsystem


def ShieldClass_Cast(obj):
    """Lenient pass-through: returns obj if it's a ShieldSubsystem, else None.

    Rejects _NamedStub explicitly so undefined-attribute chains don't slip
    through and keep producing stub-tracker hits."""
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, ShieldSubsystem):
        return obj
    return None


def PositionOrientationProperty_Cast(obj):
    """Returns obj if it's a PositionOrientationProperty, else None.

    MissionLib.GetPositionOrientationFromProperty (MissionLib.py:1815) casts
    each property in a CT_POSITION_ORIENTATION_PROPERTY list through this; the
    DockWithStarbase / UndockFromStarbase AI then reads GetPosition/GetForward/
    GetUp off the result.  ObjectEmitterProperty subclasses
    PositionOrientationProperty, so it matches too (SDK hierarchy)."""
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, PositionOrientationProperty):
        return obj
    return None


def ShieldProperty_Cast(obj):
    """Lenient pass-through: returns obj if it's a ShieldProperty, else None."""
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, ShieldProperty):
        return obj
    return None


def SubsystemProperty_Cast(obj):
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, SubsystemProperty):
        return obj
    return None


def PoweredSubsystemProperty_Cast(obj):
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, PoweredSubsystemProperty):
        return obj
    return None


def CloakingSubsystemProperty_Cast(obj):
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, CloakingSubsystemProperty):
        return obj
    return None


def RepairSubsystemProperty_Cast(obj):
    if isinstance(obj, _NamedStub):
        return None
    if isinstance(obj, RepairSubsystemProperty):
        return obj
    return None


def PhaserSystem_Cast(obj):
    """SDK Preprocessors.py:493 — `pPhaserSystem = App.PhaserSystem_Cast(pWeaponSystem)`."""
    return obj if isinstance(obj, PhaserSystem) else None


def TorpedoSystem_Cast(obj):
    """SDK Preprocessors.py:506 — `pTorpSystem = App.TorpedoSystem_Cast(pWeaponSystem)`.
    Also Preprocessors.py:445 (dumb-fire guard)."""
    return obj if isinstance(obj, TorpedoSystem) else None


def TractorBeamSystem_Cast(obj):
    """SDK Preprocessors.py:479 — `pTractor = App.TractorBeamSystem_Cast(pWeaponSystem)`."""
    return obj if isinstance(obj, TractorBeamSystem) else None


def ShipSubsystem_Cast(obj):
    """SDK Preprocessors.py:326 — `pSubsystem = App.ShipSubsystem_Cast(App.TGObject_GetTGObjectPtr(id))`."""
    return obj if isinstance(obj, ShipSubsystem) else None


def TorpedoTube_Cast(obj):
    """SDK Preprocessors.py:455 — `pTube = App.TorpedoTube_Cast(pWeaponSystem.GetChildSubsystem(iChild))`."""
    return obj if isinstance(obj, TorpedoTube) else None


def PowerSubsystem_Cast(obj):
    """SDK Conditions/ConditionPowerBelow.py:91 —
    `pPower = App.PowerSubsystem_Cast( App.TGObject_GetTGObjectPtr(self.idPower) )`.
    Called from ConditionPowerBelow.__del__, so the lazy import must degrade
    to None once the interpreter tears down the import system
    (`ImportError: sys.meta_path is None`); the __del__ null-checks."""
    try:
        from engine.appc.subsystems import PowerSubsystem
    except ImportError:
        return None
    return obj if isinstance(obj, PowerSubsystem) else None


def SensorSubsystem_Cast(obj):
    """EngineerCharacterHandlers.AnnounceSystemDisabled:924 —
    `App.SensorSubsystem_Cast(pSource)` decides the "SensorsDisabled" line."""
    from engine.appc.subsystems import SensorSubsystem
    return obj if isinstance(obj, SensorSubsystem) else None


def ImpulseEngineSubsystem_Cast(obj):
    from engine.appc.subsystems import ImpulseEngineSubsystem
    return obj if isinstance(obj, ImpulseEngineSubsystem) else None


def WarpEngineSubsystem_Cast(obj):
    from engine.appc.subsystems import WarpEngineSubsystem
    return obj if isinstance(obj, WarpEngineSubsystem) else None


def RepairSubsystem_Cast(obj):
    from engine.appc.subsystems import RepairSubsystem
    return obj if isinstance(obj, RepairSubsystem) else None


def TractorBeamProjector_Cast(obj):
    """SDK class = the individual tractor projector. Our engine models the
    projector as TractorBeam (weapon_subsystems.py:1583) under a
    TractorBeamSystem; the disabled/destroyed event source may be either,
    so match both — the announce line is the same ("TractorDisabled")."""
    from engine.appc.weapon_subsystems import TractorBeam, TractorBeamSystem
    return obj if isinstance(obj, (TractorBeam, TractorBeamSystem)) else None


def ShieldSubsystem_Cast(obj):
    """Lenient pass-through used by shield-watcher conditions; returns obj if
    it's a ShieldSubsystem, else None (mirrors ShieldClass_Cast above)."""
    return obj if isinstance(obj, ShieldSubsystem) else None


def CloakingSubsystem_Create(name):
    """Construct a runtime cloaking device. Mirrors the Appc.new_* subsystem
    factory; the SDK reaches a ship's cloak via pShip.GetCloakingSubsystem(),
    but mission/setup code may build one directly."""
    return CloakingSubsystem(name)


def CloakingSubsystem_Cast(obj):
    """Lenient pass-through used by CloakShip / FedAttack cloak doctrines;
    returns obj if it's a CloakingSubsystem, else None."""
    return obj if isinstance(obj, CloakingSubsystem) else None


def PulseWeapon_Cast(obj):
    """SDK Conditions/ConditionPulseReady.py:133 —
    `pWeapon = App.PulseWeapon_Cast(pPulseSystem.GetChildSubsystem(iChild))`.
    Reachable from ConditionPulseReady.__del__ (via GetWeapons), so the lazy
    import degrades to None at interpreter shutdown like PowerSubsystem_Cast."""
    try:
        from engine.appc.subsystems import PulseWeapon
    except ImportError:
        return None
    return obj if isinstance(obj, PulseWeapon) else None


def PulseWeaponSystem_Cast(obj):
    """SDK AI/Preprocessors.py:771 (FireScript) —
    `pPulseSystem = App.PulseWeaponSystem_Cast(pWeaponSystem)`, then
    `range(pPulseSystem.GetNumChildSubsystems())`. Was undefined, so the
    truthy _NamedStub took the branch and int()-coerced GetNumChildSubsystems
    to 0 — the AI never enumerated pulse-weapon firing directions at all."""
    return obj if isinstance(obj, PulseWeaponSystem) else None


def Weapon_Cast(obj):
    """SDK AI/PlainAI/IntelligentCircleObject.py:62-64 —
    `pWeapon = App.Weapon_Cast(pSystem.GetChildSubsystem(i))`, `if pWeapon:`.
    Was undefined, so the truthy _NamedStub made the script build its entire
    weapon list out of stubs.

    Casts to the per-emitter LEAF subsystem (phaser bank / pulse weapon /
    tractor beam / torpedo tube), never the containing WeaponSystem — "a
    System is a container of weapons, not a weapon."  Our engine's
    PhaserBank/PulseWeapon/TractorBeam inherit WeaponSystem rather than
    Weapon (weapon_subsystems.py — they mix in _EnergyWeaponFireMixin for
    charge/fire behaviour instead of deriving from Weapon), so a plain
    `isinstance(obj, Weapon)` would reject them.  Reuse
    engine.appc.subsystem_types's CT_WEAPON class tuple — the single source
    of truth for exactly this leaf-emitter split — rather than inventing a
    second, divergent notion of "weapon" here."""
    try:
        from engine.appc.subsystem_types import subsystem_class_for_ct
    except ImportError:
        return None
    # subsystem_class_for_ct returns None for an unmapped CT -- `or ()`
    # keeps the isinstance() call total (isinstance(obj, None) raises
    # TypeError; isinstance(obj, ()) is a clean, always-false match).
    weapon_classes = subsystem_class_for_ct(CT_WEAPON) or ()
    return obj if isinstance(obj, weapon_classes) else None


# ── FuzzyLogic ───────────────────────────────────────────────────────────────
# Used by SDK PlainAI scripts (TorpedoRun, FollowObject, etc.) for
# behaviour smoothing. Two forms:
#   - FuzzyLogic_BreakIntoSets: pure function, triangular memberships
#     in N bands defined by N threshold peaks.
#   - FuzzyLogic class: weighted-edge rule engine (see class docstring below).

def FuzzyLogic_BreakIntoSets(value, thresholds):
    """Return tuple of N floats summing to 1.0, representing triangular
    memberships in N bands whose peaks are at the N thresholds.

    For 3 thresholds (lo, mid, hi):
      - value <= lo                       → (1.0, 0.0, 0.0)
      - lo < value < mid                  → linear interp: (1-t, t, 0.0)
      - value == mid                      → (0.0, 1.0, 0.0)
      - mid < value < hi                  → linear interp: (0.0, 1-t, t)
      - value >= hi                       → (0.0, 0.0, 1.0)

    Generalises to N thresholds: peak of band i is at threshold[i];
    the value's position between adjacent thresholds gives a 2-element
    ramp; all other bands are 0.0. SDK callers (TorpedoRun.py:156,159,233,
    FollowObject.py:110) consistently unpack N values from N thresholds.
    """
    t = list(thresholds)
    n_bands = len(t)
    result = [0.0] * n_bands
    if value <= t[0]:
        result[0] = 1.0
        return tuple(result)
    if value >= t[-1]:
        result[-1] = 1.0
        return tuple(result)
    for i in range(len(t) - 1):
        if t[i] <= value <= t[i + 1]:
            span = t[i + 1] - t[i]
            if span <= 0.0:
                result[i + 1] = 1.0
                return tuple(result)
            frac = (value - t[i]) / span
            result[i] = 1.0 - frac
            result[i + 1] = frac
            return tuple(result)
    result[-1] = 1.0
    return tuple(result)


class FuzzyLogic:
    """Weighted-edge fuzzy inference — a faithful port of Appc's FuzzyLogic.

    Ground truth: STBC-Reverse-Engineering-1/docs/gameplay/ai-architecture.md
    sec.12 (ctor 0x0047cd10, GetResultBySet 0x0047d0b0). A "rule" is literally a
    weighted edge `inputSet --confidence--> outputSet` carrying a runtime
    percentage-in-set scratch value. A script fuzzifies its inputs with
    FuzzyLogic_BreakIntoSets, pushes the memberships in with SetPercentageInSet,
    and reads back the UNNORMALIZED weighted sum of confidence x percentage over
    every edge targeting an output set. There is no defuzzification, no centroid,
    no normalization and no clamping — all blending is done in Python by the
    caller, which compares the raw sums against each other
    (AI/PlainAI/FollowObject.py:150-152).

    Every SDK caller uses the 2-arg AddRule(in, out) form, so confidence
    defaults to 1.0.
    """

    def __init__(self):
        self._max_rules: int = 0
        # Each rule: [input_set, output_set, confidence, percentage].
        self._rules: list = []

    def SetMaxRules(self, n) -> None:
        self._max_rules = int(n)

    def GetMaxRules(self) -> int:
        return self._max_rules

    def AddRule(self, input_set, output_set, confidence: float = 1.0) -> int:
        """Append a rule; return its index, or -1 at capacity."""
        if self._max_rules and len(self._rules) >= self._max_rules:
            return -1
        self._rules.append([int(input_set), int(output_set), float(confidence), 0.0])
        return len(self._rules) - 1

    def GetRule(self, index):
        i = int(index)
        if not (0 <= i < len(self._rules)):
            return None
        in_set, out_set, conf, _pct = self._rules[i]
        return (in_set, out_set, conf)

    def RemoveRule(self, index) -> None:
        """SWAP-REMOVE — the last rule is copied over `index`. Rule indices are
        NOT stable across removal (ai-architecture.md sec.12, 0x0047cdf0)."""
        i = int(index)
        if not (0 <= i < len(self._rules)):
            return
        last = self._rules.pop()
        if i < len(self._rules):
            self._rules[i] = last

    def SetRuleConfidence(self, index, confidence) -> None:
        i = int(index)
        if 0 <= i < len(self._rules):
            self._rules[i][2] = float(confidence)

    def SetPercentageInSet(self, set_id, value) -> None:
        """Write the percentage onto every rule whose INPUT set matches."""
        sid = int(set_id)
        v = float(value)
        for rule in self._rules:
            if rule[0] == sid:
                rule[3] = v

    def GetResultBySet(self, set_id) -> float:
        """Unnormalized sum of confidence x percentage over every rule whose
        OUTPUT set matches."""
        sid = int(set_id)
        return sum(rule[2] * rule[3] for rule in self._rules if rule[1] == sid)


# ── AIScriptAssist helpers ───────────────────────────────────────────────────
# C++-side helpers exposed to PlainAI scripts for torpedo-evasion logic.
# SDK App.py binds these directly to Appc symbols (see sdk/.../App.py:10162,
# 11200). The PlainAI EvadeTorps body calls
# ``AIScriptAssist_GetIncomingTorpIDsInSet`` every 0.15s to poll for incoming
# torpedo IDs in the current set.
#
# Phase 1 has no torpedo tracker, so this stub returns an empty tuple — the
# caller's ``if not lIncomingTorpIDs: return US_ACTIVE`` short-circuit then
# fires, which is the correct behaviour when nothing's incoming.
#
# Returning a real tuple (rather than the fallback _Stub) is required: the
# SDK script next does ``for idTorp in lIncomingTorpIDs`` — iterating a _Stub
# loops forever via __getitem__.

def AIScriptAssist_GetIncomingTorpIDsInSet(pShip, pSet, fDangerTimeThreshold,
                                            idToIgnore, iFlags):
    return ()


def AIScriptAssist_TorpIsIncoming(pShip, pTorp, fDangerTimeThreshold):
    return 0


# ── App.AT_* ammo-type constants ─────────────────────────────────────────────
# Plain int ammo-type indices, matching the real Appc.AT_* enum.  The SDK's
# only uses are as the first arg of TorpedoSystem.SetAmmoType — a 0-based
# slot selection in the same domain as GetAmmoTypeNumber() and
# range(GetNumAmmoTypes()) (AI/Preprocessors.py:548,640 pass raw indices to
# the same call; E2M0.py:720 selects the Sovereign's slot-1 Quantum via
# AT_TWO).
AT_ONE   = 0
AT_TWO   = 1
AT_THREE = 2
AT_FOUR  = 3
AT_FIVE  = 4

# ── Numeric constants ──────────────────────────────────────────────────────────
NULL_ID = 0
PI = math.pi
HALF_PI = math.pi / 2.0
TWO_PI = math.pi * 2.0

# ── Singletons ─────────────────────────────────────────────────────────────────
g_kEventManager = TGEventManager()
g_kTimerManager = TGTimerManager(g_kEventManager)
g_kRealtimeTimerManager = TGTimerManager(g_kEventManager)
g_kInputManager, g_kKeyboardBinding = init_input_pipeline(g_kEventManager)
register_input_handlers(g_kEventManager)

# ── TopWindow shim ─────────────────────────────────────────────────────────────
# See engine/appc/top_window.py and
# docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
# TopWindow_GetTopWindow() must precede any SDK import that might call it
# at module-load time — keep this block at the singleton initialisation site.
from engine.appc.top_window import (
    TopWindow_GetTopWindow,
    MWT_BRIDGE, MWT_TACTICAL, MWT_CONSOLE, MWT_EDITOR, MWT_OPTIONS,
    MWT_SUBTITLE, MWT_TACTICAL_MAP, MWT_CINEMATIC, MWT_MULTIPLAYER,
    MWT_CD_CHECK, MWT_MODAL_DIALOG,
)


def TacticalControlWindow_GetTacticalControlWindow():
    return TacticalControlWindow.GetInstance()


def TacticalControlWindow_Create():
    # SDK TacticalMenuHandlers.CreateMenus() calls this to create and get the
    # singleton TCW. In the real engine this creates a new window; in dauntless
    # we return the same singleton so AddMenuToList / AddChild calls land on one
    # place regardless of which call site the SDK uses to reach the window.
    return TacticalControlWindow.GetInstance()
g_kSetManager = SetManager()
g_kModelManager = ModelManager()
g_kAnimationManager = AnimationManager()
g_kTGActionManager = TGActionManager()
g_kModelPropertyManager = TGModelPropertyManager()
g_kLODModelManager = LODModelManager()
g_kLocalizationManager = TGLocalizationManager()
g_kConfigMapping = TGConfigMapping()
# VarManager shares the event-type allocator with Game_GetNextEventType so
# IDs returned by MakeEpisodeEventType are unique across all event-type sources.
# Lambda indirection — Game_GetNextEventType is defined further down in this
# module, so we can't reference it directly at this point.
g_kVarManager = TGVarManager(event_type_allocator=lambda: Game_GetNextEventType())


# ── TGSystemWrapper ────────────────────────────────────────────────────────────
# SDK App.py:279 binds TGSystemWrapperClass.GetRandomNumber(n) which returns
# an int in [0, n-1].  Effects.py uses it heavily for particle-effect
# randomisation; mission scripts use it for AI variation.
#
# Headless engine uses Python's random; SetRandomSeed lets tests pin determinism.
import random as _random


class _SystemWrapper:
    def __init__(self):
        self._rng = _random.Random()

    def GetRandomNumber(self, upper_exclusive: int) -> int:
        if upper_exclusive <= 0:
            return 0
        return self._rng.randrange(int(upper_exclusive))

    def SetRandomSeed(self, seed) -> None:
        self._rng.seed(seed)

    def GetTimeSinceFrameStart(self) -> float:
        """Seconds since the current frame started. Phase 1 doesn't
        run a frame timer, so this returns 0.0 — SDK preprocessors
        (SelectTarget) compare this against a `dEndTime` budget; with a
        generous deadline the always-zero return keeps work in-budget."""
        return 0.0

    def __getattr__(self, name):
        return _NamedStub(name)


g_kSystemWrapper = _SystemWrapper()

# ── Event-type constants (integers; values are arbitrary but stable) ───────────
# Only the subset needed for Phase 1.  Add more as SDK scripts demand them.
ET_AI_TIMER = 100
ET_ACTION_COMPLETED = 101
# Posted to g_kTGActionManager (ObjPtr = action) to skip an action outright —
# MissionLib.py:4863/4871 uses it to drop queued dialogue when the player dies.
ET_ACTION_SKIP = 111
ET_MISSION_START = 102
ET_EPISODE_START = 103
ET_OBJECT_DELETED = 104
ET_ENTERED_SET = 105
# Fired when an object leaves a set (RemoveObjectFromSet/DeleteObjectFromSet, or
# a warp moving a ship between sets). Carries the LEFT set's name as a CString
# (TGStringEvent) because by dispatch time the object's containing-set may
# already point elsewhere — SDK ExitSet handlers read pEvent.GetCString() for the
# set name (E2M2.ExitSet, et al.). Not present in the original ET_* dump; value
# picked to stay contiguous with this block and not collide.
ET_EXITED_SET = 109
ET_OBJECT_EXPLODING = 106
ET_OBJECT_DESTROYED = 107
# Fired once the Game's pre-load (asset streaming) finishes. SDK Game.py binds
# Game_SetPreLoadDoneEvent to store an event the engine posts when loading is
# done; the QuickBattle boot chain (Game.LoadEpisode -> Episode.LoadMission)
# uses it to drive the synchronous mission-start cascade.
ET_PRELOAD_DONE = 108
# Fired by Game.SetPlayer (engine/core/game.py) when the current player ship is
# assigned. The SDK HelmMenuHandlers register broadcast handlers on it
# (OrbitMenuPlayerChanged, SetPlayer, the fleet-command PlayerChanged handlers)
# to (re)wire per-player state and repopulate the Orbit/Nav menus from the
# player's set. Not present in the original ET_* dump; value picked to stay
# contiguous with this block and not collide.
ET_SET_PLAYER = 110

# Fired by every SDK character-move builder's completed-event (PicardAnimations,
# MediumAnimations, ...) carrying a CS_* state as its int. BC's native engine
# consumes it and applies that state to the destination character — that is how an
# officer HIDES after walking into the turbolift (CS_HIDDEN) and how a walk-on ends
# STANDING / SEATED. Not present in the original ET_* dump; 100-111 are all taken
# in this block (checked), so 112 is the next free contiguous value.
ET_CHARACTER_ANIMATION_DONE = 112

# Used by Conditions/Condition*.py — broadcast events the SDK conditions
# subscribe to. Values arbitrary but stable; keep contiguous with the
# existing ET_* block so future grep finds them all in one place.
ET_DELETE_OBJECT_PUBLIC = 200
ET_OBJECT_GROUP_OBJECT_ENTERED_SET = 201
ET_OBJECT_GROUP_OBJECT_EXITED_SET = 202
ET_CONDITION_ATK_FORGIVE = 203
# Group membership changed (Add/Remove name on an ObjectGroup) — fires
# the GROUP_CHANGED event the SDK uses to invalidate cached views of
# the group's members. ConditionInRange subscribes to rebuild its
# proximity sphere when its target list churns.
ET_OBJECT_GROUP_CHANGED = 204
# AI-internal proximity transition. SDK Conditions/ConditionInRange
# fires a ProximityCheck with this event type so its ProximityEvent
# method runs when watched ships cross the radius boundary.
ET_AI_INTERNAL_PROX_EVENT = 205
# Decloak event used by SelectTarget to re-rate targets when a hostile
# uncloaks. Value picked outside the Slice A 200-203 range; 204/205 are
# taken by ET_OBJECT_GROUP_CHANGED / ET_AI_INTERNAL_PROX_EVENT.
ET_DECLOAK_BEGINNING = 206
# Cloak-beginning sibling of ET_DECLOAK_BEGINNING. BC fires this at the START
# of a cloak transition (the COMPLETED events fire at the end). Consumed by
# Bridge/PowerDisplay.py:340 (cloak power readout) and missions E2M0/E2M1.
ET_CLOAK_BEGINNING = 207
# Fired by AI/Player/OrbitPlanet.StartingOrbit (source=player ship,
# destination=planet) as soon as the orbit AI's sequence starts — NOT after a
# stable orbit is achieved. Consumed by mission listeners (E1M2.OrbitingHaven
# sets g_bPlayerInOrbit) and Conditions/ConditionPlayerOrbitting.
ET_AI_ORBITTING = 208
# Fired when a ship's installed AI ends: cleared (ClearAI), replaced
# (SetAI over an existing tree), or the root tree completes (US_DONE).
# TGIntEvent: GetInt() = the ended AI's GetID(), destination = the ship.
# Consumed by Conditions/ConditionPlayerOrbitting.OrbitDone ("player left
# orbit" → HelmMenuHandlers.Orbitting plays the KiskaLeaveOrbit line) and
# Bridge/HelmCharacterHandlers.AIDone.
ET_AI_DONE = 209

# ── Input event types — used by DefaultKeyboardBinding + TacticalInterfaceHandlers
# Values are stable arbitrary integers well above the Phase-1 event range.
# The SDK allocates these via Appc.ET_*; we pick our own stable IDs since the
# only requirement is consistency between BindKey registration and handler lookup.
ET_INPUT_FIRE_PRIMARY           = 1001
ET_INPUT_FIRE_SECONDARY         = 1002
ET_INPUT_FIRE_TERTIARY          = 1003
ET_INPUT_ZOOM                   = 1004
ET_INPUT_TOGGLE_MAP_MODE        = 1005
ET_INPUT_TOGGLE_CINEMATIC_MODE  = 1006
ET_INPUT_CYCLE_CAMERA           = 1007
ET_INPUT_CHASE_PLAYER           = 1008
ET_INPUT_REVERSE_CHASE          = 1009
ET_INPUT_ZOOM_TARGET            = 1010
ET_INPUT_CLEAR_TARGET           = 1011
ET_INPUT_TARGET_NEXT            = 1012
ET_INPUT_TARGET_PREV            = 1013
ET_INPUT_TARGET_NEAREST         = 1014
ET_INPUT_TARGET_NEXT_ENEMY      = 1015
ET_INPUT_TARGET_TARGETS_ATTACKER = 1016
ET_INPUT_TARGET_NEXT_NAVPOINT   = 1017
ET_INPUT_TARGET_NEXT_PLANET     = 1018
ET_INPUT_ALLOW_CAMERA_ROTATION  = 1019
ET_INPUT_SET_IMPULSE            = 1020
ET_INPUT_INCREASE_SPEED         = 1021
ET_INPUT_DECREASE_SPEED         = 1022
ET_INPUT_TURN_LEFT              = 1023
ET_INPUT_TURN_RIGHT             = 1024
ET_INPUT_TURN_UP                = 1025
ET_INPUT_TURN_DOWN              = 1026
ET_INPUT_ROLL_LEFT              = 1027
ET_INPUT_ROLL_RIGHT             = 1028
ET_INPUT_SKIP_EVENTS            = 1029
ET_INPUT_SELECT_X               = 1030
ET_INPUT_SELECT_OPTION          = 1031
ET_INPUT_PRE_SELECT_OPTION      = 1032
ET_INPUT_CLOSE_MENU             = 1033
ET_INPUT_INTERCEPT              = 1034
ET_INPUT_TOGGLE_CONSOLE         = 1035
ET_INPUT_TOGGLE_OPTIONS         = 1036
ET_INPUT_DEBUG_KILL_TARGET      = 1037
ET_INPUT_DEBUG_QUICK_REPAIR     = 1038
ET_INPUT_DEBUG_GOD_MODE         = 1039
ET_INPUT_DEBUG_LOAD_QUANTUMS    = 1040
ET_INPUT_TALK_TO_TACTICAL       = 1041
ET_INPUT_TALK_TO_HELM           = 1042
ET_INPUT_TALK_TO_XO             = 1043
ET_INPUT_TALK_TO_SCIENCE        = 1044
ET_INPUT_TALK_TO_ENGINEERING    = 1045
ET_INPUT_TALK_TO_GUEST          = 1046
ET_INPUT_TOGGLE_SCORE_WINDOW    = 1047
ET_INPUT_TOGGLE_CHAT_WINDOW     = 1048
ET_OTHER_BEAM_TOGGLE_CLICKED    = 1049
ET_OTHER_CLOAK_TOGGLE_CLICKED   = 1050
ET_SET_ALERT_LEVEL              = 1051
ET_QUICK_SAVE                   = 1052
ET_QUICK_LOAD                   = 1053
ET_INPUT_PRINT_SCREEN             = 1054
# 1055 is ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL (engine/appc/events.py) — do
# not reuse it here.
ET_INPUT_SELF_DESTRUCT          = 1056

# ── Bridge-interaction event types ─────────────────────────────────────────────
# Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md.
# Static ints in 1060-1099 — above the input block (1001-1056, plus slack
# 1057-1059 left for input-block growth), below the Game_GetNextEventType
# allocator floor (1200).
ET_ST_BUTTON_CLICKED        = 1060
ET_COMMUNICATE              = 1061
ET_HAIL                     = 1062
ET_SCAN                     = 1063
ET_SET_COURSE               = 1064
ET_ALL_STOP                 = 1065
ET_DOCK                     = 1066
ET_MANAGE_POWER             = 1067
ET_MANEUVER                 = 1068
ET_HAILABLE_CHANGE          = 1069
ET_SENSORS_SHIP_IDENTIFIED  = 1070
ET_CLOAK_COMPLETED          = 1071
ET_DECLOAK_COMPLETED        = 1072
ET_CHARACTER_MENU           = 1073
ET_CONTACT_STARFLEET        = 1074
# Fired when something rams a cloaked ship (a cloaked hull is still physically
# present). BC's HelmMenuHandlers.CloakedCollision plays a "collided with a
# cloaked ship" line off this event.
ET_CLOAKED_COLLISION        = 1075
# Helm "Orbit Planet" button event. SetupOrbitMenuFromSet builds one STButton
# per planet whose activation event is (type=ET_ORBIT_PLANET, source=planet,
# dest=orbit menu); HelmMenuHandlers.OrbitPlanet handles it on the menu.
ET_ORBIT_PLANET             = 1076
# Helm "Report" button event — HelmCharacterHandlers.AttachMenuToHelm registers
# Report/SetCourse/HelmDock/AllStop on the Helm top-level menu; Report is the
# only one of the four without a pre-existing static int here. 1077 is the first
# free value in this block (1075 is intentionally shared by ET_CLOAKED_COLLISION
# and ET_POWER_FRACTION_CHANGED; everything else through 1076 is taken).
ET_REPORT                   = 1077
# Dock lifecycle notifications. Fired when the player completes a dock with a
# starbase (ET_PLAYER_DOCKED_WITH_STARBASE) and when a tractored target finishes
# docking (ET_TRACTOR_TARGET_DOCKED). Real distinct ints so any future handler
# keyed on them dispatches; without this App.__getattr__ hands back a fresh
# unstable _NamedStub (int()==0) per access. 1078/1079 are the next free values
# in this block (1077 = ET_REPORT is the current high), below the 1200
# Game_GetNextEventType allocator floor.
ET_PLAYER_DOCKED_WITH_STARBASE = 1078
ET_TRACTOR_TARGET_DOCKED       = 1079
# Fired by ObjectClass.SetScannable on an actual change of the flag (mirrors
# ET_HAILABLE_CHANGE above). Bridge/ScienceMenuHandlers.CreateMenus registers
# a broadcast handler for it (PropertyChange) that refreshes the Scan Object
# menu's per-ship button when a ship's scannability toggles at runtime (e.g.
# Maelstrom/Episode6/E6M4's cloaked-Kessok reveal). 1080 is the next free
# value in this block.
ET_SCANNABLE_CHANGE            = 1080

# ── FloatRangeWatcher condition event ─────────────────────────────────────────
# Crossing event broadcast by a power subsystem's battery watcher when the
# main/backup battery fraction crosses a registered threshold. The SDK
# allocates this via UtopiaModule_GetNextEventType (Conditions/
# ConditionPowerBelow.py:21); Dauntless assigns its own stable ET_* int in
# the 1060-1099 bridge/condition block, above the input range and below the
# Game_GetNextEventType allocator floor (1200).
ET_POWER_FRACTION_CHANGED   = 1075

# ── Nebula + environmental event types ────────────────────────────────────────────
# Private to the Phase-2 engine; values extend the engine/appc/events.py private
# range (0x1000..0x1200) and do not collide with SDK Appc-side ids.
ET_ENTERED_NEBULA = 0x1300
ET_EXITED_NEBULA = 0x1301
ET_ENVIRONMENT_DAMAGE = 0x1302

# ── Engineer status-report event types ────────────────────────────────────────
# Registered by Bridge/EngineerCharacterHandlers.AttachMenuToEngineer and
# stamped onto FloatRangeWatcher range-check events by Brex.ConfigureForShip
# (Bridge/Characters/Brex.py:107-142). These MUST be real distinct ints:
# App's module-level __getattr__ returns a fresh _NamedStub per access, so a
# handler registered under one access would never match an event fired under
# another. Values continue the private 0x13xx block above.
ET_TACTICAL_SHIELD_LEVEL_CHANGE   = 0x1310
ET_TACTICAL_HULL_LEVEL_CHANGE     = 0x1311
ET_TACTICAL_SHIELD_0_LEVEL_CHANGE = 0x1312
ET_TACTICAL_SHIELD_1_LEVEL_CHANGE = 0x1313
ET_TACTICAL_SHIELD_2_LEVEL_CHANGE = 0x1314
ET_TACTICAL_SHIELD_3_LEVEL_CHANGE = 0x1315
ET_TACTICAL_SHIELD_4_LEVEL_CHANGE = 0x1316
ET_TACTICAL_SHIELD_5_LEVEL_CHANGE = 0x1317
# Battery-fraction thresholds (stamped onto GetMain/BackupBatteryWatcher
# range-check events) plus the subsystem/repair report ids the same
# AttachMenuToEngineer call registers broadcast handlers under. The
# subsystem/repair four have no engine-side emitter yet — defining them as
# real ints gives those registrations a stable identity for when emission
# lands. Names verbatim from EngineerCharacterHandlers.py.
ET_MAIN_BATTERY_LEVEL_CHANGE      = 0x1318
ET_BACKUP_BATTERY_LEVEL_CHANGE    = 0x1319
ET_SUBSYSTEM_DISABLED             = 0x131A
ET_SUBSYSTEM_DESTROYED            = 0x131B
ET_REPAIR_COMPLETED               = 0x131C
ET_REPAIR_CANNOT_BE_COMPLETED     = 0x131D
# Posted by PoweredSubsystem.SetPowerPercentageWanted on every slider change.
# BC FUN_00562430 broadcasts this so the power-display HUD and the engineer's
# FloatRangeWatcher conditions can react to manual slider adjustments.
ET_SUBSYSTEM_POWER_CHANGED        = 0x131E
# Repaired back above the disabled threshold. Consumed by the AI Conditions
# classes (ConditionSystemDisabled/ConditionTorpsReady/ConditionPulseReady
# register broadcast handlers for it) as well as the engineer report path.
ET_SUBSYSTEM_OPERATIONAL          = 0x131F
# EngRepairPane click -> binary head/tail toggle on the repair queue.
ET_REPAIR_INCREASE_PRIORITY       = 0x1320
# A damaged subsystem entered the repair queue.
ET_ADD_TO_REPAIR_LIST             = 0x1321
# ── AI condition watcher event types ─────────────────────────────────────────
# Stamped by the SDK conditions onto the TGFloatEvent they hand to a
# FloatRangeWatcher, then fired back at them on a threshold crossing:
#   Conditions/ConditionSystemBelow.py:88-97   (subsystem condition fraction)
#   Conditions/ConditionSingleShieldBelow.py:36 (per-face shield fraction)
# These MUST be real distinct ints. App's module-level __getattr__ returns a
# fresh _NamedStub per access and _NamedStub hashes by id(), so a handler
# registered under one access can never match an event fired under another —
# which is exactly how the two most-used conditions in the AI (31 + 12 SDK
# uses) silently never updated their status.
ET_AI_SYSTEM_STATUS_WATCHER       = 0x1322
ET_AI_SHIELD_WATCHER              = 0x1323
# Broadcast by TGCondition.SetStatus on every status transition. Composite
# conditions listen for it on their children (Conditions/
# ConditionCriticalSystemBelow.py). Real int for the same reason as above.
ET_AI_CONDITION_CHANGED           = 0x1324
# Posted by ShipClass.SetTarget whenever the resolved target actually
# changes (Appc-side: ShipClass::SetTarget). Consumers register with
# AddPythonFuncHandlerForInstance ON THE SHIP (Camera.py:719 on the player,
# Bridge/HelmMenuHandlers.py:280, Bridge/ScienceMenuHandlers.py:133,
# Maelstrom/Episode1/E1M2/E1M2.py:1152) and AI/Preprocessors.py's
# UseShipTarget.CodeAISet registers a broadcast method handler filtered to
# the ship. Must be a real distinct int for the same reason as the AI
# condition watchers above: App's module __getattr__ returns a fresh
# id()-hashed _NamedStub per access, so a handler registered under one
# access could never match an event fired under another -- which is exactly
# how UseShipTarget stayed dead even after Task 9 made its CodeAISet hook
# finally run.
ET_TARGET_WAS_CHANGED             = 0x1325

_next_event_type_id = 1200


def Game_GetNextEventType() -> int:
    global _next_event_type_id
    result = _next_event_type_id
    _next_event_type_id += 1
    return result


Mission_GetNextEventType = Game_GetNextEventType
Episode_GetNextEventType = Game_GetNextEventType
# Module-level alias used by AI/Compound/, Conditions/, MainMenu/ scripts:
#   ET_X = App.UtopiaModule_GetNextEventType()
# SDK App.py:10687 binds this to Appc.UtopiaModule_GetNextEventType — same
# event-id allocator under the hood as the Game/Mission/Episode forms above.
UtopiaModule_GetNextEventType = Game_GetNextEventType

# ── Player hardpoint file (set by MissionLib.CreatePlayerShip) ─────────────────
_player_hardpoint_filename: "str | None" = None


def Game_GetPlayerHardpointFileName() -> "str | None":
    return _player_hardpoint_filename


def Game_SetPlayerHardpointFileName(filename: str) -> None:
    global _player_hardpoint_filename
    _player_hardpoint_filename = filename


# ── UtopiaModule ───────────────────────────────────────────────────────────────

class _UtopiaModule:
    def __init__(self):
        # Friendly-fire damage accumulator: tracks recent unintended-friendly
        # damage dealt by the player (MissionLib.py:3722-3724).  Crew comments
        # ("Friendly Fire") fire when this exceeds a threshold; SDK clears it
        # to 0 between missions.  Float (damage units), default 0.
        self._friendly_fire = 0.0
        # Maximum permitted friendly-fire accumulation before the full reaction
        # (MissionLib.py SetMaxFriendlyFire; read back as GetFriendlyFireTolerance).
        # 5000.0 is the ENGINE DEFAULT, decoded from a real BC save taken in E8M1
        # — a mission that sets neither this nor the warning points, so the saved
        # values ARE the defaults (docs/engine/
        # bcs-save-format.md, preamble scalars 1 and 3).
        #
        # This default is load-bearing, not cosmetic. MissionLib:3727 reads
        #     if total >= tolerance: GAME_OVER  elif <crossed a warning>: REPORT
        # so a 0 tolerance makes the first branch always win and the REPORT
        # unreachable — which silently killed the XO's friendly-fire warning in
        # QuickBattle (it sets warning points but never a tolerance).
        self._friendly_fire_max = 5000.0
        # Threshold below the max that triggers the warning ("watch your fire")
        # rather than the full violation (MissionLib.py SetFriendlyFireWarningPoints).
        # 300.0 is the engine default from the same save; QuickBattle.py:770
        # setting exactly 300 corroborates it.
        self._friendly_fire_warning_points = 300.0
        # Tractor-time accumulator: seconds the player has held a friendly
        # ship in tractor (MissionLib.py:3870-3873).  Triggers warnings when
        # held too long.  Float (seconds), default 0.
        self._friendly_tractor_time = 0.0
        # Captain name — saved in BCS save filenames (MissionLib.py:2801) and
        # shown in UI.  Default "Picard" matches the BC default profile.
        self._captain_name = "Picard"
        # Per-torpedo-type ammo economy. Keys are TorpedoSystem ammo-type
        # indices, values are int counts. -1 is the SDK sentinel for
        # "unset / unlimited"; getters return it for unseen types so
        # DockWithStarbase (Actions/ShipScriptActions.py:382-395) sees the
        # same default as the original engine.
        self._max_torpedo_load: dict = {}
        self._starbase_torpedo_load: dict = {}

    def GetGameTime(self) -> float:
        return g_kTimerManager.get_time()

    def SetCurrentFriendlyFire(self, value) -> None:
        self._friendly_fire = float(value)

    def GetCurrentFriendlyFire(self) -> float:
        return self._friendly_fire

    def SetMaxFriendlyFire(self, value) -> None:
        self._friendly_fire_max = float(value)

    def GetMaxFriendlyFire(self) -> float:
        return self._friendly_fire_max

    def GetFriendlyFireTolerance(self) -> float:
        """SWIG's asymmetric getter for the SetMaxFriendlyFire value
        (sdk/.../App.py:3259-3260). MissionLib.FriendlyFireHandler:3726 reads
        the game-over ceiling back through THIS name, not GetMaxFriendlyFire."""
        return self._friendly_fire_max

    def SetFriendlyFireWarningPoints(self, value) -> None:
        self._friendly_fire_warning_points = float(value)

    def GetFriendlyFireWarningPoints(self) -> float:
        return self._friendly_fire_warning_points

    def SetFriendlyTractorTime(self, value) -> None:
        self._friendly_tractor_time = float(value)

    def GetFriendlyTractorTime(self) -> float:
        return self._friendly_tractor_time

    def SetCaptainName(self, name) -> None:
        self._captain_name = str(name)

    def GetCaptainName(self):
        # SDK chains .GetCString() on the result — return _TGString so the
        # downstream call resolves on a real method, not a _NamedStub.
        return _TGString(self._captain_name)

    # ── Multiplayer state ────────────────────────────────────────────────────
    # The headless harness never enters network play; all three accessors
    # report the single-player offline state.  Real multiplayer requires the
    # network stack which is Phase 2.
    def IsHost(self) -> int: return 0
    def IsClient(self) -> int: return 0
    def IsMultiplayer(self) -> int: return 0
    def GetNetwork(self): return None  # SDK callers guard with `if pNetwork:`

    # ── Save/Load delegation ────────────────────────────────────────────────
    # The actual save/load machinery lives in engine.appc.save_load.SaveLoadManager;
    # UtopiaModule just delegates so the SDK call surface
    # (g_kUtopiaModule.SaveToFile etc.) stays unchanged.
    def SaveToFile(self, filename) -> int:
        return _save_load_manager.SaveToFile(filename)

    def LoadFromFile(self, filename) -> int:
        return _save_load_manager.LoadFromFile(filename)

    def SaveMissionState(self) -> int:
        return _save_load_manager.SaveMissionState()

    def LoadMissionState(self, module_name) -> int:
        return _save_load_manager.LoadMissionState(module_name)

    def SetLoadFromFileName(self, filename) -> None:
        _save_load_manager.SetLoadFromFileName(filename)

    def SetInternalLoadFileName(self, filename) -> None:
        _save_load_manager.SetInternalLoadFileName(filename)

    def GetSaveFilename(self):
        return _save_load_manager.GetSaveFilename()

    def GetLoadFilename(self):
        return _save_load_manager.GetLoadFilename()

    # ── Torpedo economy ─────────────────────────────────────────────────────
    # MissionLib.SetMaxTorpsForPlayer / SetTotalTorpsAtStarbase write here at
    # mission init; Actions.ShipScriptActions.DockWithStarbase reads on dock.
    def SetMaxTorpedoLoad(self, iType, iNumTorps) -> None:
        self._max_torpedo_load[int(iType)] = int(iNumTorps)

    def GetMaxTorpedoLoad(self, iType) -> int:
        return self._max_torpedo_load.get(int(iType), -1)

    def SetCurrentStarbaseTorpedoLoad(self, iType, iNumTorps) -> None:
        self._starbase_torpedo_load[int(iType)] = int(iNumTorps)

    def GetCurrentStarbaseTorpedoLoad(self, iType) -> int:
        return self._starbase_torpedo_load.get(int(iType), -1)

    # Event-type allocator on the UtopiaModule receiver as well, matching the
    # SDK pattern App.g_kUtopiaModule.GetNextEventType() (in addition to the
    # module-level App.UtopiaModule_GetNextEventType form).
    def GetNextEventType(self) -> int:
        return Game_GetNextEventType()

    def __getattr__(self, name):
        return _NamedStub(name)

_save_load_manager = SaveLoadManager()
g_kUtopiaModule = _UtopiaModule()


# ── Typed event objects ────────────────────────────────────────────────────────
# SDK scripts create these, store a typed value via Set*, then pass the event
# to a handler which reads it back via Get*.  The stub's __getattr__ would lose
# the stored value, so we need real storage.

class _TGTypedEvent:
    """Base for Int/String/Float event objects."""
    def __init__(self):
        self._event_type = 0
        self._destination = None
    def SetEventType(self, t): self._event_type = t
    def GetEventType(self): return self._event_type
    def SetDestination(self, d): self._destination = d
    def GetDestination(self): return self._destination
    def __getattr__(self, name): return _Stub()

class _TGIntEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = 0
    def SetInt(self, v): self._val = int(v) if not isinstance(v, _Stub) else 0
    def GetInt(self): return self._val

class _TGStringEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = ""
    def SetString(self, v): self._val = str(v) if not isinstance(v, _Stub) else ""
    def GetString(self): return _TGString(self._val)
    def GetCString(self): return self._val

class _TGFloatEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = 0.0
    def SetFloat(self, v): self._val = float(v) if not isinstance(v, _Stub) else 0.0
    def GetFloat(self): return self._val

def TGIntEvent_Create(): return _TGIntEvent()
def TGStringEvent_Create(): return _TGStringEvent()
def TGFloatEvent_Create(): return _TGFloatEvent()


# ── NiPoint2 — 2-float (x, y) value used by layout helpers ───────────────────
# SDK TacticalMenuHandlers.CreateOrdersStatusDisplay:
#   kSize = App.NiPoint2(0.0, 0.0)
#   pPopupMenu.GetDesiredSize(kSize)
#   pPane.Resize(kSize.x, ...)
class NiPoint2:
    def __init__(self, x: float = 0.0, y: float = 0.0):
        self.x = float(x)
        self.y = float(y)


# ── TGColorA — 4-float RGBA value (NetImmerse NiColorA) ───────────────────────
# Hardpoint scripts and Tactical/Projectiles/* allocate these to hold shield-
# glow / weapon / torpedo / UI panel tints, then hand them to engine setters
# such as ShieldProperty.SetShieldGlowColor and pTorp.CreateTorpedoModel.
# Both method (SetRGBA/GetR/...) and attribute (kColor.r = 0.0) forms are used
# in the SDK; UITree.py:292 reads via attribute, StylizedWindow.py writes via
# attribute, hardpoints write via SetRGBA.
class TGColorA:
    def __init__(self, r=0.0, g=0.0, b=0.0, a=0.0):
        self.r = float(r)
        self.g = float(g)
        self.b = float(b)
        self.a = float(a)

    def SetRGBA(self, r, g, b, a):
        self.r = float(r); self.g = float(g)
        self.b = float(b); self.a = float(a)

    def SetR(self, v): self.r = float(v)
    def SetG(self, v): self.g = float(v)
    def SetB(self, v): self.b = float(v)
    def SetA(self, v): self.a = float(v)

    def GetR(self): return self.r
    def GetG(self): return self.g
    def GetB(self): return self.b
    def GetA(self): return self.a

    def ScaleRGB(self, k):
        k = float(k)
        self.r *= k; self.g *= k; self.b *= k

    def Copy(self, other):
        self.r = other.r; self.g = other.g
        self.b = other.b; self.a = other.a


# ── NiColorA — NetImmerse RGBA colour; alias and named constants ───────────────
# TGColorA (above) and NiColorA are the same layout in BC.  EngineerMenuHandlers
# and several art scripts write colour attributes using the NiColorA name.
NiColorA = TGColorA   # same implementation; different BC module name
NiColorA_BLACK = NiColorA(0.0, 0.0, 0.0, 1.0)
NiColorA_WHITE = NiColorA(1.0, 1.0, 1.0, 1.0)

# ── STButton colours referenced in TacticalMenuHandlers ──────────────────────
# TacticalMenuHandlers.OverrideButtonColors uses these module-level colour
# constants.  Headless: real NiColorA objects with reasonable defaults; the
# exact RGBA values are irrelevant because dauntless never renders them.
g_kSTMenu2NormalBase    = NiColorA(0.5, 0.5, 0.5, 1.0)
g_kSTMenu2HighlightedBase = NiColorA(0.8, 0.8, 0.8, 1.0)
g_kSTMenu2Disabled      = NiColorA(0.3, 0.3, 0.3, 0.5)

# ── App.globals — Appc.globals namespace (SDK App.py:13178). PowerDisplay and
# the engineering UI read indents + colours through it; colour values are
# LCARS approximations from the original UI (cosmetic — CEF restyles).
# NOTE: assigning globals = _AppcGlobals() shadows the builtin inside this
# module.  Capture _py_globals first so __getattr__'s memoize path still works.
_py_globals = globals  # preserve builtin before shadowing


class _AppcGlobals:
    DEFAULT_ST_INDENT_HORIZ = 5.0
    DEFAULT_ST_INDENT_VERT = 5.0
    g_kEngineeringWarpCoreColor      = NiColorA(0.25, 0.47, 1.00, 1.0)  # blue
    g_kEngineeringMainPowerColor     = NiColorA(1.00, 0.80, 0.20, 1.0)  # yellow
    g_kEngineeringBackupPowerColor   = NiColorA(1.00, 0.30, 0.15, 1.0)  # red
    g_kEngineeringEnginesColor       = NiColorA(0.85, 0.45, 0.95, 1.0)
    g_kEngineeringShieldsColor       = NiColorA(0.65, 0.55, 0.95, 1.0)
    g_kEngineeringWeaponsColor       = NiColorA(0.95, 0.60, 0.25, 1.0)
    g_kEngineeringSensorsColor       = NiColorA(0.95, 0.90, 0.30, 1.0)
    g_kEngineeringCloakColor         = NiColorA(0.95, 0.55, 0.20, 1.0)
    g_kEngineeringTractorColor       = NiColorA(0.95, 0.40, 0.55, 1.0)
    g_kEngineeringCtrlBkgndLineColor = NiColorA(0.30, 0.30, 0.30, 1.0)
    # LCARS interface-chrome border (QuickBattle ship-menu bar, StylizedWindow
    # frames). SDK App.py exports it at globals scope; exact Appc RGBA is not
    # recoverable, so a neutral LCARS-blue placeholder — headless never renders it.
    g_kInterfaceBorderColor          = NiColorA(0.60, 0.70, 1.00, 1.0)


globals = _AppcGlobals()
# SDK App.py re-exports the colours at module level (lines 13994-14003).
g_kEngineeringWarpCoreColor      = globals.g_kEngineeringWarpCoreColor
g_kEngineeringMainPowerColor     = globals.g_kEngineeringMainPowerColor
g_kEngineeringBackupPowerColor   = globals.g_kEngineeringBackupPowerColor
g_kEngineeringEnginesColor       = globals.g_kEngineeringEnginesColor
g_kEngineeringShieldsColor       = globals.g_kEngineeringShieldsColor
g_kEngineeringWeaponsColor       = globals.g_kEngineeringWeaponsColor
g_kEngineeringSensorsColor       = globals.g_kEngineeringSensorsColor
g_kEngineeringCloakColor         = globals.g_kEngineeringCloakColor
g_kEngineeringTractorColor       = globals.g_kEngineeringTractorColor
g_kEngineeringCtrlBkgndLineColor = globals.g_kEngineeringCtrlBkgndLineColor
g_kInterfaceBorderColor          = globals.g_kInterfaceBorderColor

# ── Ship species constants ────────────────────────────────────────────────────
# Used by WeaponsDisplay.SetShipIcon and other art routines.  Exact Appc values
# are not available; we use unique sentinel integers — they are only ever passed
# to TGIcon_Create("ShipIcons", SPECIES_*) where headless rendering ignores them.
SPECIES_GALAXY          = 0
SPECIES_DEFIANT         = 1
SPECIES_SOVEREIGN       = 2
SPECIES_KLINGON_BOK_RAT = 3
SPECIES_KLINGON_KVORT   = 4
SPECIES_KLINGON_NEGH_VAR= 5
SPECIES_ROMULAN_WARBIRD = 6
SPECIES_BORG_CUBE       = 7
SPECIES_BORG_SPHERE     = 8
SPECIES_CARDASSIAN      = 9
SPECIES_FERENGI         = 10
SPECIES_GENERIC         = 11

# ── Tactical / Engineering display widget factories ────────────────────────────
# TacticalMenuHandlers and EngineerMenuHandlers create several purely-visual
# display widgets (weapons display, ship display sub-panels, power display,
# repair pane, etc.) whose only effect on the headless menu tree is being
# registered on the TCW via Set*/Add*.  They must survive a handful of layout
# calls (GetNthChild, Resize, SetFixedSize, GetBorderWidth, …) without crashing.
#
# Implementation: each factory returns a _DisplayWidget — a minimal subclass of
# the STStylizedWindow layout sink that overrides GetNthChild to always return
# a fresh TGPane so downstream TGPane_Cast(…GetNthChild(X)) succeeds.

class _DisplayWidget:
    """Minimal layout-sink widget for tactical/engineering display areas.

    All geometry and layout calls are no-ops.  GetNthChild always returns a
    fresh TGPane so SDK patterns like TGPane_Cast(w.GetNthChild(SLOT)).Resize(…)
    never encounter None.

    GetShipID() returns None so that SDK code that does:
        pShip = ShipClass_GetObjectByID(SetClass_GetNull(), pDisplay.GetShipID())
        if pShip == None: return
    exits early without crashing.
    """
    def __init__(self, name: str = ""):
        self._name = name
        self._children: list = []

    def SetUseScrolling(self, *_a) -> None:      pass
    def SetName(self, *_a) -> None:              pass
    def GetName(self) -> str:                    return self._name
    def GetNameParagraph(self):
        from engine.appc.tg_ui.widgets import TGParagraph
        return TGParagraph(self._name)
    def SetFixedSize(self, *_a) -> None:         pass
    def SetMaximumSize(self, *_a) -> None:       pass
    def InteriorChangedSize(self, *_a) -> None:  pass
    def Layout(self, *_a) -> None:               pass
    def Resize(self, *_a) -> None:               pass
    def GetWidth(self) -> float:                 return 0.0
    def GetHeight(self) -> float:                return 0.0
    def GetBorderWidth(self) -> float:           return 0.0
    def GetBorderHeight(self) -> float:          return 0.0
    def GetMaximumWidth(self) -> float:          return 0.0
    def GetMaximumHeight(self) -> float:         return 0.0
    def GetLeft(self) -> float:                  return 0.0
    def GetTop(self) -> float:                   return 0.0
    def AlignTo(self, *_a) -> None:              pass
    def SetPosition(self, *_a) -> None:          pass
    def Move(self, *_a) -> None:                 pass
    def SetNotVisible(self, *_a) -> None:        pass
    def SetVisible(self, *_a) -> None:           pass
    def SetMinimizable(self, *_a) -> None:       pass
    def SetEnabled(self, *_a) -> None:           pass
    def ResizeUI(self, *_a) -> None:             pass
    # SDK calls GetShipID() then passes it to ShipClass_GetObjectByID to check
    # whether a real ship exists.  Return None so the pShip == None guard fires.
    def GetShipID(self):                         return None
    # GetConceptualParent: some SDK functions (EngRepairPane, WeaponsDisplay)
    # walk up the widget tree via GetParent().GetConceptualParent().  Make the
    # top-level display widget terminate that chain gracefully.
    def GetConceptualParent(self):               return self
    # GetParent: PowerDisplay.py line 275 calls pPowerDisplay.GetParent().Resize(…).
    # Return self so that Resize() no-ops cleanly.
    def GetParent(self):                         return self
    def IsMinimized(self):                       return 0

    def AddChild(self, child, *_a) -> None:
        self._children.append(child)

    def GetNthChild(self, n):
        n = int(n)
        if 0 <= n < len(self._children):
            return self._children[n]
        # Return a fresh TGPane so TGPane_Cast(…GetNthChild(SLOT)).Resize(…) works.
        from engine.appc.tg_ui.widgets import TGPane
        return TGPane()

    def GetFirstChild(self):
        return self._children[0] if self._children else None

    def __getattr__(self, name):
        # Absorb any remaining SDK calls — these widgets have dozens of
        # display-only methods we'll never enumerate exhaustively.
        return lambda *_a, **_kw: None


class WeaponsDisplay:
    """Constants for child-pane slot indices (SDK App.WeaponsDisplay.*).

    The exact Appc values are not available without running the DLL.  We use
    unique sequential integers so that getattr accesses succeed and dict-keyed
    lookups in GetNthChild don't alias.  The actual values don't matter because
    our _BackRefPane.GetNthChild returns a fresh _SelfParentedPane for every
    slot, and no SDK code treats the index as a magic number outside of
    App.WeaponsDisplay.<NAME>.
    """
    DISPLAY_PANE                    = 0
    TORPEDO_PANE                    = 1
    ICON_PANE                       = 2
    TOP_RIGHT_BORDER                = 3
    TOP_BORDER                      = 4
    LEFT_TOP_BORDER                 = 5
    LEFT_BORDER                     = 6
    LEFT_BOTTOM_BORDER              = 7
    RIGHT_TOP_BORDER                = 8
    RIGHT_BORDER                    = 9
    RIGHT_BOTTOM_BORDER             = 10
    GLASS                           = 11
    UPPER_PHASER_PANE               = 12
    UPPER_PHASER_INDICATOR_PANE     = 13
    UPPER_DISRUPTOR_PANE            = 14
    UPPER_DISRUPTOR_INDICATOR_PANE  = 15
    LOWER_PHASER_PANE               = 16
    LOWER_PHASER_INDICATOR_PANE     = 17
    LOWER_DISRUPTOR_PANE            = 18
    LOWER_DISRUPTOR_INDICATOR_PANE  = 19
    SHIP_ICON                       = 20


class EngRepairPane:
    """Constants for EngRepairPane child slots (SDK App.EngRepairPane.*)."""
    DIVIDER = 0


def WeaponsDisplay_Cast(obj) -> "_DisplayWidget | None":
    """Return obj if it is a _DisplayWidget (headless WeaponsDisplay), else None.

    SDK code does:
        pDisplay = App.WeaponsDisplay_Cast(pParent.GetConceptualParent())
        pShip = App.ShipClass_GetObjectByID(App.SetClass_GetNull(), pDisplay.GetShipID())
        if pShip == None: return

    We need WeaponsDisplay_Cast to return the _DisplayWidget so that
    GetShipID() → None → ShipClass_GetObjectByID returns None → early exit.
    """
    return obj if isinstance(obj, _DisplayWidget) else None


def WeaponsDisplay_Create(width=0.0, height=0.0) -> "_DisplayWidget":
    w = _DisplayWidget("WeaponsDisplay")
    # Pre-seed DISPLAY_PANE (slot 0) with a _BackRefPane whose GetParent()
    # returns w and GetConceptualParent() returns w.  The torpedo pane lives
    # inside that pane.  This lets ResizeTorpedoPane walk:
    #   torp_pane.GetParent()          → display_pane (_BackRefPane, is TGPane)
    #   TGPane_Cast(display_pane)      → display_pane (passes isinstance check)
    #   display_pane.GetConceptualParent() → w (_DisplayWidget)
    #   WeaponsDisplay_Cast(w)         → w
    #   w.GetShipID()                  → None
    #   ShipClass_GetObjectByID(…, None) → None
    #   if pShip == None: return       ← exits cleanly
    from engine.appc.tg_ui.widgets import TGPane

    class _SelfParentedPane(TGPane):
        """TGPane whose GetParent() returns itself and GetConceptualParent() returns the owner.

        Used for all child panes of the WeaponsDisplay display_pane so that SDK
        patterns like:
            pParent = pUpperPane.GetParent()          # → self (a TGPane)
            pParent.GetWidth()                        # → 0.0 (safe)
            pParent.GetConceptualParent()             # → owner (_DisplayWidget)
        always terminate cleanly even when TGPane_Cast is applied.
        """
        def __init__(self, owner: "_DisplayWidget"):
            super().__init__()
            self._owner = owner

        def GetParent(self):
            return self  # TGPane_Cast(self) succeeds; GetWidth()/GetHeight() → 0.0

        def GetConceptualParent(self):
            return self._owner  # WeaponsDisplay_Cast(owner) → owner; owner.GetShipID() → None

        def GetNthChild(self, n):
            # Child panes of display_pane also need to be self-parented so the
            # same GetParent chain works one level deeper.
            n = int(n)
            if 0 <= n < len(self._children):
                return self._children[n][0]
            return _SelfParentedPane(self._owner)

    class _BackRefPane(_SelfParentedPane):
        """The DISPLAY_PANE itself — GetConceptualParent returns the top-level display widget."""
        pass

    display_pane = _BackRefPane(w)
    torp_pane = _SelfParentedPane(w)
    display_pane.AddChild(torp_pane)
    w.AddChild(display_pane)
    return w


def TacWeaponsCtrl_Create(width=0.0, height=0.0) -> "_DisplayWidget":
    return _DisplayWidget("TacWeaponsCtrl")


class _BeamToggle:
    """Tractor-beam on/off toggle button state.

    BridgeHandlers.ToggleTractorBeam flips this between 0 and 1 on each click;
    the TacWeaponsCtrl reads it to decide whether to engage or disengage the
    beam.  Stands in for BC's C++ toggle widget.
    """
    def __init__(self):
        self._state = 0

    def GetState(self) -> int:
        return self._state

    def SetState(self, s) -> None:
        self._state = int(s)


class _TacWeaponsCtrl(TGEventHandlerObject):
    """Headless stand-in for BC's C++ TacWeaponsCtrl tactical-weapons widget.

    In stock BC this compiled widget owns the tractor beam-toggle button and,
    when ET_OTHER_BEAM_TOGGLE_CLICKED reaches it (re-fired by
    BridgeHandlers.ToggleTractorBeam after flipping the toggle state), engages
    or disengages the player's tractor beam.  Our renderer has no such C++
    widget, so we reproduce exactly that behaviour here — the missing link that
    makes the toggle → StartFiring path reach the tractor system.
    """
    def __init__(self):
        super().__init__()
        self._beam_toggle = _BeamToggle()
        self._cloak_toggle = _BeamToggle()
        self.AddPythonFuncHandlerForInstance(
            ET_OTHER_BEAM_TOGGLE_CLICKED, "App._tac_weapons_beam_toggled")
        self.AddPythonFuncHandlerForInstance(
            ET_OTHER_CLOAK_TOGGLE_CLICKED, "App._tac_weapons_cloak_toggled")

    def GetBeamToggle(self) -> "_BeamToggle":
        return self._beam_toggle

    def GetCloakToggle(self):
        """The cloak toggle button — or None when the player ship has no
        cloaking device.  BC's BridgeHandlers.ToggleCloak calls
        pWeapons.GetCloakToggle() and returns early on None ("Not all ships can
        cloak…"), so a non-cloak ship sees no cloak control at all."""
        import MissionLib
        player = MissionLib.GetPlayer()
        if player is None or player.GetCloakingSubsystem() is None:
            return None
        return self._cloak_toggle

    def RefreshCloakToggle(self) -> None:
        """Resync the cloak toggle button to the device's actual intent so a
        forced decloak (damaged cloak) or a scripted cloak is reflected in the
        button / power-display state — mirrors BC TacWeaponsCtrl.RefreshCloakToggle."""
        import MissionLib
        player = MissionLib.GetPlayer()
        cloak = player.GetCloakingSubsystem() if player is not None else None
        engaged = cloak is not None and bool(cloak.IsTryingToCloak())
        self._cloak_toggle.SetState(1 if engaged else 0)


_g_tac_weapons_ctrl = None


def TacWeaponsCtrl_GetTacWeaponsCtrl() -> "_TacWeaponsCtrl":
    global _g_tac_weapons_ctrl
    if _g_tac_weapons_ctrl is None:
        _g_tac_weapons_ctrl = _TacWeaponsCtrl()
    return _g_tac_weapons_ctrl


def _tac_weapons_beam_toggled(pObject, pEvent):
    """Engage/disengage the player's tractor beam to match the toggle state.

    Mirrors TacticalInterfaceHandlers.FireWeapons (StartFiring with the current
    target / StopFiring), but driven by the beam toggle rather than a held fire
    key.  Tractor lives in its own WG_TRACTOR group, untouched by the
    WG_PRIMARY→pulse fallback.
    """
    toggle = pObject.GetBeamToggle()
    import MissionLib
    player = MissionLib.GetPlayer()
    if player is None:
        return
    tractor = player.GetWeaponSystemGroup(ShipClass.WG_TRACTOR)
    if tractor is None:
        return
    if toggle.GetState():
        target = player.GetTarget()
        if target is None:
            # Nothing to grab — snap the toggle back off so the button state
            # matches the (non-)firing reality.
            toggle.SetState(0)
            return
        # The tractor is a manual-control system (the alert-level power policy
        # leaves it OFF by design — ships.py _apply_alert_power); the beam
        # toggle IS its power switch.  Power it on before firing, else
        # StartFiring bails on `not self.IsOn()`.
        if hasattr(tractor, "TurnOn"):
            tractor.TurnOn()
        tractor.StartFiring(target, None)
    else:
        tractor.StopFiring()
        if hasattr(tractor, "TurnOff"):
            tractor.TurnOff()


def ToggleTractorFromInput():
    """Flip the tractor beam toggle and engage/disengage directly.

    The keyboard path uses this instead of re-posting ET_OTHER_BEAM_TOGGLE_CLICKED
    through the tactical window: in the live engine the SDK
    BridgeHandlers.ToggleTractorBeam chain (window handler resolution +
    CallNextHandler + event re-fire) does not reliably reach the
    TacWeaponsCtrl, so we drive the same TacWeaponsCtrl logic here with no
    indirection.
    """
    ctrl = TacWeaponsCtrl_GetTacWeaponsCtrl()
    toggle = ctrl.GetBeamToggle()
    new_state = 0 if toggle.GetState() else 1
    toggle.SetState(new_state)
    # The player has no UI to pick a tractor mode, so a manual grab uses PULL:
    # draw the target in to its standoff and hold it there (the intuitive
    # tractor-beam behaviour).  Mission/AI scripts still drive HOLD/TOW/DOCK on
    # NPC ships via SetMode directly.
    if new_state:
        import MissionLib
        player = MissionLib.GetPlayer()
        if player is not None:
            tr = player.GetWeaponSystemGroup(ShipClass.WG_TRACTOR)
            if tr is not None and hasattr(tr, "SetMode"):
                tr.SetMode(TractorBeamSystem.TBS_PULL)
    _tac_weapons_beam_toggled(ctrl, None)


def _tac_weapons_cloak_toggled(pObject, pEvent):
    """Engage/disengage the player's cloak to match the toggle state — the
    engine-side stand-in for BC's C++ TacWeaponsCtrl cloak handling.

    BC's BridgeHandlers.ToggleCloak flips the toggle button then re-fires
    ET_OTHER_CLOAK_TOGGLE_CLICKED to this control; the control acts on the
    toggle state (StartCloaking when on, StopCloaking when off).  The state
    machine no-ops a redundant call, so an already-cloaked ship is unaffected
    by a spurious "on".
    """
    toggle = pObject._cloak_toggle
    import MissionLib
    player = MissionLib.GetPlayer()
    if player is None:
        return
    cloak = player.GetCloakingSubsystem()
    if cloak is None:
        toggle.SetState(0)
        return
    if toggle.GetState():
        cloak.StartCloaking()
    else:
        cloak.StopCloaking()


def ToggleCloakFromInput():
    """Flip the cloak toggle and engage/disengage directly (keyboard path).

    Mirrors ToggleTractorFromInput: the SDK BridgeHandlers.ToggleCloak window
    chain (handler resolution + CallNextHandler + event re-fire) does not
    reliably reach the TacWeaponsCtrl in our host, so the Alt+C poller drives
    the same logic here with no indirection.  No-op when the player ship has no
    cloaking device.  Resyncs the toggle to the device's real state before
    flipping, so a forced decloak (damaged cloak) doesn't leave the button stuck
    "on" and swallow the next press.
    """
    import MissionLib
    player = MissionLib.GetPlayer()
    if player is None or player.GetCloakingSubsystem() is None:
        return
    ctrl = TacWeaponsCtrl_GetTacWeaponsCtrl()
    ctrl.RefreshCloakToggle()
    toggle = ctrl._cloak_toggle
    toggle.SetState(0 if toggle.GetState() else 1)
    _tac_weapons_cloak_toggled(ctrl, None)


class EngRepairPaneWidget(_DisplayWidget):
    """The live repair-queue pane. Created by the unmodified SDK
    (EngineerMenuHandlers.py:84) and added as a child of the Engineering
    menu; CrewMenuPanel detects this class and projects the queue via
    engine.ui.eng_repair_pane.repair_pane_snapshot."""
    def __init__(self, width=0.0, height=0.0, rows=0):
        super().__init__("EngRepairPane")
        self._pane_width, self._pane_height, self._pane_rows = width, height, rows

    def IsVisible(self) -> int:
        # _DisplayWidget defines no IsVisible; its __getattr__ catch-all
        # (line ~1380) would return a lambda giving None -> bool(None) ->
        # False, which crew_menus.js treats as "skip this node entirely"
        # (visible === false check runs before the node.type check) -- the
        # pane would never render. The pane genuinely IS visible whenever it
        # exists as a child of the open Engineering menu, so this always
        # returns the SDK integer-bool true (1), matching the convention
        # used by sibling widgets (e.g. engine/appc/characters.py:69).
        return 1


def EngRepairPane_Create(width=0.0, height=0.0, n=0) -> "EngRepairPaneWidget":
    pane = EngRepairPaneWidget(width, height, n)
    # Pre-seed one child (index 0 = DIVIDER) so GetNthChild(DIVIDER).Layout()
    # keeps working (SDK layout path).
    from engine.appc.tg_ui.widgets import TGPane
    pane.AddChild(TGPane())
    return pane


# EngPowerDisplay_Create, EngPowerCtrl_GetPowerCtrl and related names are
# imported from engine.appc.tg_ui.eng_power at the top of this module.


# ── Stub call tracker ─────────────────────────────────────────────────────────
class _StubTracker:
    def __init__(self):
        self._data = {}      # {name: {mission: call_count}}
        self._mission = None

    def set_mission(self, name):
        self._mission = name

    def reset_mission(self):
        self._mission = None

    def record(self, name):
        if self._mission is None:
            return
        self._data.setdefault(name, {}).setdefault(self._mission, 0)
        self._data[name][self._mission] += 1

    def report(self):
        rows = []
        for name, missions in self._data.items():
            rows.append((name, len(missions), sum(missions.values())))
        rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
        return rows

    def clear(self):
        self._data.clear()
        self._mission = None

_stub_tracker = _StubTracker()


# ── Color consumer tracker ────────────────────────────────────────────────────
# Records (setter_name, mission, caller_file:line, rgba) for every stub call
# whose arg list contains a TGColorA.  Off by default — enable only when
# running the gameloop harness with --color-consumers so frame inspection
# overhead stays out of the normal path.
class _ColorConsumerTracker:
    def __init__(self):
        self._enabled = False
        # key = (name, mission, caller, rgba) → count
        self._data: dict = {}

    def enable(self): self._enabled = True
    def disable(self): self._enabled = False
    def is_enabled(self): return self._enabled

    def record(self, name, color, caller_file, caller_line):
        if not self._enabled:
            return
        mission = _stub_tracker._mission
        if mission is None:
            return
        rgba = (color.r, color.g, color.b, color.a)
        key = (name, mission, "%s:%d" % (caller_file, caller_line), rgba)
        self._data[key] = self._data.get(key, 0) + 1

    def report(self):
        # rows sorted: most-called first, then by name
        rows = [(n, m, c, rgba, count) for (n, m, c, rgba), count in self._data.items()]
        rows.sort(key=lambda r: (-r[4], r[0], r[1], r[2]))
        return rows

    def clear(self):
        self._data.clear()


_color_consumer_tracker = _ColorConsumerTracker()


# ── Emission recorder ─────────────────────────────────────────────────────────
# Captures shuttle / probe / decoy launch events when the
# Actions.ShipScriptActions.LaunchObject hook (engine/appc/emission.py) is
# installed. Off by default; tests and the harness opt in.
class _EmissionRecorder:
    def __init__(self):
        self._enabled = False
        self._mission = None
        self._events = []

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def is_enabled(self):
        return self._enabled

    def set_mission(self, name):
        self._mission = name

    def reset_mission(self):
        self._mission = None

    def record(self, ship_id, emitter_name, emitter_type,
               world_position, world_forward, world_up):
        if not self._enabled:
            return
        self._events.append({
            "mission": self._mission,
            "ship_id": ship_id,
            "emitter_name": emitter_name,
            "emitter_type": emitter_type,
            "world_position": (world_position.x, world_position.y, world_position.z),
            "world_forward":  (world_forward.x,  world_forward.y,  world_forward.z),
            "world_up":       (world_up.x,       world_up.y,       world_up.z),
        })

    def events(self):
        return list(self._events)

    def clear(self):
        self._events = []


_emission_recorder = _EmissionRecorder()


# ── Fallback stub ──────────────────────────────────────────────────────────────
class _Stub:
    """Returned for any App attribute not yet implemented.

    Falsy so that `if pShip:` guards behave correctly when the object
    hasn't been set up — surfaces missing implementations rather than
    silently proceeding with stub data.
    """
    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __bool__(self):
        # Truthiness trap: an undefined name sails through `if (x):` guards.
        if stub_telemetry.ENABLED:
            name = getattr(self, "_name", None)
            stub_telemetry.record_bool(name.partition(".")[0] if name else "App")
        return True

    def __hash__(self):
        return id(self)

    def __getitem__(self, key):
        return _Stub()

    def __setitem__(self, key, value):
        pass

    def __delitem__(self, key):
        pass

    def __repr__(self):
        return "<App._Stub>"

    # Numeric operators: return 0/0.0 so arithmetic in SDK scripts doesn't crash.
    # GetRadius() / 2, position comparisons, etc. all need to produce a numeric.
    # int()==0 is the collapse trap that has caused real bugs (WC_*/KY_*
    # keyboard constants, TGUIObject.ALIGN_* before it was bound to real
    # constants) — record_coercion is the signal that surfaces it.
    def __int__(self):
        if stub_telemetry.ENABLED:
            stub_telemetry.record_coercion("int")
        return 0

    def __float__(self):
        if stub_telemetry.ENABLED:
            stub_telemetry.record_coercion("float")
        return 0.0

    def __index__(self):
        if stub_telemetry.ENABLED:
            stub_telemetry.record_coercion("index")
        return 0
    def __add__(self, o):   return o if isinstance(o, str) else 0
    def __radd__(self, o):  return o if isinstance(o, str) else 0
    def __sub__(self, o):   return 0
    def __rsub__(self, o):  return 0
    def __mul__(self, o):   return 0
    def __rmul__(self, o):  return 0
    def __truediv__(self, o):  return 0.0
    def __rtruediv__(self, o): return 0.0
    def __floordiv__(self, o):  return 0
    def __rfloordiv__(self, o): return 0
    def __mod__(self, o):   return "" if isinstance(o, (str, tuple)) else 0
    def __rmod__(self, o):  return "" if isinstance(o, (str, tuple)) else 0
    def __neg__(self):      return 0
    def __pos__(self):      return 0
    def __abs__(self):      return 0
    def __or__(self, o):    return 0
    def __ror__(self, o):   return 0
    def __and__(self, o):   return 0
    def __rand__(self, o):  return 0
    def __xor__(self, o):   return 0
    def __rxor__(self, o):  return 0
    def __lshift__(self, o): return 0
    def __rshift__(self, o): return 0
    def __invert__(self):   return 0
    # Comparison operators: always False so guards like `fRadius >= 6000` skip
    def __lt__(self, o):    return False
    def __le__(self, o):    return False
    def __gt__(self, o):    return False
    def __ge__(self, o):    return False
    def __eq__(self, o):    return isinstance(o, type(self))
    def __ne__(self, o):    return not isinstance(o, type(self))


class _NamedStub(_Stub):
    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        name = self.__dict__.get("_name", "<unknown>")
        full = f"{name}.{attr}"
        if stub_telemetry.ENABLED:
            # Split at the FIRST dot so a chained access matches the
            # heatmap's owner|attr table shape (e.g. TGUIObject.ALIGN_BL ->
            # owner=TGUIObject, attr=ALIGN_BL; deeper chains keep the rest
            # of the dotted path as a breadcrumb in attr, same as the
            # instance stub path in engine/core/ids.py).
            owner, _dot, rest = full.partition(".")
            stub_telemetry.record_attr(owner, rest)
        return _NamedStub(full)

    def __repr__(self):
        return f"<App._NamedStub {self._name!r}>"

    def __call__(self, *args, **kwargs):
        _stub_tracker.record(self._name)
        if _color_consumer_tracker.is_enabled():
            for a in args:
                if isinstance(a, TGColorA):
                    import sys as _sys
                    frame = _sys._getframe(1)
                    _color_consumer_tracker.record(
                        self._name, a, frame.f_code.co_filename, frame.f_lineno
                    )
                    break
        return _NamedStub(f"{self._name}()")


def __getattr__(name):
    # Keyboard constants live in engine.appc.input (the generated WC_/KY_ table).
    # Surface any name it defines as App.WC_*/App.KY_* so the explicit import
    # list can never drift a key into a _NamedStub (int()==0) dead slot.  Every
    # other absent symbol — and any WC_/KY_ name the table omits (the unwired
    # CTRL_/ALT_/CAPS_ modifier variants) — still falls through to _NamedStub.
    if name[:3] in ("WC_", "KY_"):
        val = getattr(_input_consts, name, None)
        if isinstance(val, int):
            _py_globals()[name] = val   # memoize: future lookups skip __getattr__
            return val
    if stub_telemetry.ENABLED:
        stub_telemetry.record_attr("App", name)
    return _NamedStub(name)
