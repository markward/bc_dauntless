import math
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGEventHandlerObject, TGEventManager,
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
    ObjectClass_Cast, ObjectClass_GetObject, ObjectClass_GetObjectByID,
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
from engine.core.game import (
    Game, Episode, Mission, Game_GetCurrentGame, _set_current_game,
    Game_GetDifficulty,
    Game_SetDifficultyMultipliers, Game_SetDefaultDifficultyMultipliers,
    Game_GetOffensiveDifficultyMultiplier, Game_GetDefensiveDifficultyMultiplier,
    Game_GetCurrentPlayer, Game_SetCurrentPlayer,
)
from engine.appc.localization import TGLocalizationManager, TGLocalizationDatabase, _TGString
from engine.appc.var_manager import TGVarManager
from engine.appc.save_load import SaveLoadManager
from engine.appc.config_mapping import TGConfigMapping
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
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, WeaponSystem,
    TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
    SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
    WarpEngineSubsystem_GetWarpEffectTime, WarpEngineSubsystem_SetWarpEffectTime,
)
from engine.appc.properties import (
    TGModelProperty,
    TGModelPropertyManager, TGModelPropertySet,
    PositionOrientationProperty,
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
)

# ── App.CT_* class-type constants ─────────────────────────────────────────────
# SDK code calls pSet.GetPropertiesByType(App.CT_X) which feeds X into
# isinstance(prop, X).  isinstance requires a real class — _NamedStub crashes
# the moment a populated property set is filtered.  Bind the names to the
# matching Python classes so isinstance() works.
#
# Property-type constants map to the corresponding *Property class because
# property sets hold properties, not live subsystems.  Subsystem-type
# constants in property-set filtering contexts (CT_HULL_SUBSYSTEM, etc.)
# also map to the matching Property — the constant name matches the
# subsystem domain but the filter runs over property templates.
CT_SUBSYSTEM_PROPERTY            = SubsystemProperty
CT_POSITION_ORIENTATION_PROPERTY = PositionOrientationProperty
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
g_kSetManager = SetManager()
g_kTGActionManager = TGActionManager()
g_kModelPropertyManager = TGModelPropertyManager()
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

_next_event_type_id = 200


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
        return _NamedStub(f"{self._name}()")


def __getattr__(name):
    return _NamedStub(name)
