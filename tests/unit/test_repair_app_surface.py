"""Repair-feature App surface: constants + casts EngineerCharacterHandlers needs.

Guards the _Stub trap: App.__getattr__ vends a fresh _NamedStub for missing
names, so a missing export silently no-ops. Every name on the engineer
announce/report path must resolve to something real.
"""
import App


# Every App.* name Bridge/EngineerCharacterHandlers.py touches on the
# emitter paths (registration, announce handlers, Report/Communicate).
_ENGINEER_HANDLER_APP_NAMES = [
    # events
    "ET_REPORT", "ET_COMMUNICATE",
    "ET_TACTICAL_SHIELD_LEVEL_CHANGE", "ET_TACTICAL_HULL_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_0_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_1_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_2_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_3_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_4_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_5_LEVEL_CHANGE",
    "ET_SUBSYSTEM_DISABLED", "ET_SUBSYSTEM_DESTROYED",
    "ET_SUBSYSTEM_OPERATIONAL",
    "ET_REPAIR_COMPLETED", "ET_REPAIR_CANNOT_BE_COMPLETED",
    "ET_REPAIR_INCREASE_PRIORITY", "ET_ADD_TO_REPAIR_LIST",
    "ET_MAIN_BATTERY_LEVEL_CHANGE", "ET_BACKUP_BATTERY_LEVEL_CHANGE",
    # casts used by AnnounceSystemDisabled / AnnounceSystemDestroyed /
    # RepairCompleted (EngineerCharacterHandlers.py:918-932, 294-336)
    "PhaserSystem_Cast", "ShieldClass_Cast", "SensorSubsystem_Cast",
    "TorpedoSystem_Cast", "TractorBeamProjector_Cast",
    "ImpulseEngineSubsystem_Cast", "WarpEngineSubsystem_Cast",
    "PowerSubsystem_Cast", "ShipSubsystem_Cast", "RepairSubsystem_Cast",
    # machinery
    "TGObject_GetTGObjectPtr", "CharacterClass_GetObject",
    "TGSequence_Create", "CharacterAction_Create", "TGScriptAction_Create",
    "TGFloatEvent_Create", "CSP_SPONTANEOUS", "FloatRangeWatcher",
]


def test_engineer_handler_names_are_real_not_stubs():
    missing = []
    for name in _ENGINEER_HANDLER_APP_NAMES:
        val = getattr(App, name)
        if isinstance(val, App._NamedStub):
            missing.append(name)
    assert not missing, "App names still stubbed: %r" % missing


def test_new_event_constants_are_distinct_ints():
    values = {
        App.ET_SUBSYSTEM_OPERATIONAL,
        App.ET_REPAIR_INCREASE_PRIORITY,
        App.ET_ADD_TO_REPAIR_LIST,
        App.ET_SUBSYSTEM_DISABLED,
        App.ET_SUBSYSTEM_DESTROYED,
        App.ET_REPAIR_COMPLETED,
        App.ET_REPAIR_CANNOT_BE_COMPLETED,
    }
    assert len(values) == 7
    assert all(isinstance(v, int) for v in values)


def test_new_casts_pass_matching_reject_other():
    from engine.appc.subsystems import (
        SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
        RepairSubsystem,
    )
    from engine.appc.weapon_subsystems import TractorBeam
    pairs = [
        (App.SensorSubsystem_Cast, SensorSubsystem("s")),
        (App.ImpulseEngineSubsystem_Cast, ImpulseEngineSubsystem("i")),
        (App.WarpEngineSubsystem_Cast, WarpEngineSubsystem("w")),
        (App.RepairSubsystem_Cast, RepairSubsystem("r")),
        (App.TractorBeamProjector_Cast, TractorBeam("t")),
    ]
    for cast, obj in pairs:
        assert cast(obj) is obj
        assert cast(object()) is None
        assert cast(None) is None
