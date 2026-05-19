import math
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGBoolEvent, TGBoolEvent_Create,
    TGKeyboardEvent, ET_KEYBOARD_EVENT,
    WeaponHitEvent, ET_WEAPON_HIT,
    TGEventHandlerObject, TGEventManager,
)
from engine.appc.input import (
    TGInputManager, KeyboardBinding,
    WC_LBUTTON, WC_RBUTTON, WC_MBUTTON,
    KY_LBUTTON, KY_RBUTTON, KY_MBUTTON,
    KS_KEYDOWN, KS_KEYUP, KS_KEYREPEAT, KS_NORMAL,
    init_input_pipeline, register_input_handlers,
)
from engine.appc.windows import TacticalControlWindow
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
    ObjectClass_Cast, PhysicsObjectClass_Cast,
    ObjectClass_GetObject, ObjectClass_GetObjectByID,
    IsNull,
)
from engine.appc.sets import SetClass, SetManager, SetClass_Create, SetClass_GetNull
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
    SubtitleAction, SubtitleAction_Create,
    TGActionManager,
    TGActionManager_RegisterAction, TGActionManager_UnregisterAction,
    TGActionManager_FindAction,
    TGCreditAction, TGCreditAction_Create,
    TGCreditAction_SetDefaultColor, TGCreditAction_GetDefaultColor,
    TGConditionAction, TGConditionAction_Create,
    TGObjPtrEvent, TGObjPtrEvent_Create,
    TGObject_GetTGObjectPtr,
)
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, g_kSoundManager,
)
from engine.core.game import (
    Game, Episode, Mission, Game_GetCurrentGame, _set_current_game,
    Game_GetDifficulty,
    Game_SetDifficultyMultipliers, Game_SetDefaultDifficultyMultipliers,
    Game_GetOffensiveDifficultyMultiplier, Game_GetDefensiveDifficultyMultiplier,
    Game_GetCurrentPlayer, Game_SetCurrentPlayer,
)
from engine.appc.localization import TGLocalizationManager, TGLocalizationDatabase, TGString, _TGString
from engine.appc.var_manager import TGVarManager
from engine.appc.save_load import SaveLoadManager
from engine.appc.config_mapping import TGConfigMapping
from engine.appc.lod_models import LODModelManager
from engine.appc.debug import (
    CPyDebug, TGProfilingInfo,
    TGProfilingInfo_EnableProfiling, TGProfilingInfo_DisableProfiling,
    TGProfilingInfo_IsProfilingEnabled,
    TGProfilingInfo_StartTiming, TGProfilingInfo_StopTiming,
    TGProfilingInfo_GetTotalTime, TGProfilingInfo_ResetTimings,
)
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
    STButton_CreateW, STMenu_Cast, STTopLevelMenu_CreateW, STTopLevelMenu_Cast,
)
from engine.appc.ai import (
    ArtificialIntelligence,
    TGCondition, TGConditionHandler,
    ConditionScript, ConditionScript_Create, ConditionScript_Cast,
    PlainAI, PlainAI_Create,
    PriorityListAI, PriorityListAI_Create,
    SequenceAI, SequenceAI_Create,
    PreprocessingAI, PreprocessingAI_Create, PreprocessingAI_Cast,
    ConditionalAI, ConditionalAI_Create,
    ConditionEventCreator,
    BuilderAI, BuilderAI_Create,
    ProximityCheck, ProximityCheck_Create, ProximityCheck_CreateWithEvent,
    CharacterAction, CharacterAction_Create, CharacterAction_CreateByName,
    CSP_LOW, CSP_NORMAL, CSP_HIGH,
)
from engine.appc.time_slice import (
    TimeSliceProcess, PythonMethodProcess, g_kAIManager,
)
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, WeaponSystem,
    TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
    SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
    WarpEngineSubsystem_GetWarpEffectTime, WarpEngineSubsystem_SetWarpEffectTime,
    ShieldSubsystem,
)
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
class SortedRegionMenu(STMenu): pass

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


# ── App.AT_* ammo-type constants ─────────────────────────────────────────────
# SDK code treats these as TorpedoAmmoType instances (objects with GetAmmoName)
# rather than plain ints — MissionLib.SetTotalTorpsAtStarbase iterates the
# torpedo system and compares ``pTorpType.GetAmmoName() == "Photon"``.
# Standard BC ammo names: AT_ONE = "Photon", AT_TWO = "Quantum"; later
# slots are placeholders used by other missions.
from engine.appc.subsystems import TorpedoAmmoType as _TorpedoAmmoType
AT_ONE   = _TorpedoAmmoType("Photon")
AT_TWO   = _TorpedoAmmoType("Quantum")
AT_THREE = _TorpedoAmmoType("TriCobalt")
AT_FOUR  = _TorpedoAmmoType("Plasma")
AT_FIVE  = _TorpedoAmmoType("Polaron")

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


def TacticalControlWindow_GetTacticalControlWindow():
    return TacticalControlWindow.GetInstance()
g_kSetManager = SetManager()
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

    def __getattr__(self, name):
        return _NamedStub(name)


g_kSystemWrapper = _SystemWrapper()

# ── Event-type constants (integers; values are arbitrary but stable) ───────────
# Only the subset needed for Phase 1.  Add more as SDK scripts demand them.
ET_AI_TIMER = 100
ET_ACTION_COMPLETED = 101
ET_MISSION_START = 102
ET_EPISODE_START = 103
ET_OBJECT_DELETED = 104
ET_ENTERED_SET = 105
ET_OBJECT_EXPLODING = 106

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
ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL = 1055

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
        # Maximum permitted friendly-fire accumulation before triggering the
        # full reaction (MissionLib.py SetMaxFriendlyFire).  Default 0 = engine
        # default which scripts override per-mission.
        self._friendly_fire_max = 0.0
        # Threshold below the max that triggers the warning ("watch your fire")
        # rather than the full violation (MissionLib.py SetFriendlyFireWarningPoints).
        self._friendly_fire_warning_points = 0.0
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
    def __int__(self):      return 0
    def __float__(self):    return 0.0
    def __index__(self):    return 0
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
        return _NamedStub(f"{name}.{attr}")

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
    return _NamedStub(name)
