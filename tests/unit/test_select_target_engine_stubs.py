"""Unit tests for the small engine surfaces SelectTarget needs."""
import App
from engine.appc.events import WeaponHitEvent
from engine.appc.ships import ShipClass


def test_et_decloak_beginning_constant_is_unique():
    """Event-type constant exists and doesn't collide with the existing
    range or with the Slice A condition constants."""
    assert isinstance(App.ET_DECLOAK_BEGINNING, int)
    existing = {App.ET_AI_TIMER, App.ET_ACTION_COMPLETED, App.ET_MISSION_START,
                App.ET_WEAPON_HIT, App.ET_DELETE_OBJECT_PUBLIC,
                App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET,
                App.ET_OBJECT_GROUP_OBJECT_EXITED_SET,
                App.ET_CONDITION_ATK_FORGIVE}
    assert App.ET_DECLOAK_BEGINNING not in existing


def test_tg_profiling_info_endtiming_alias():
    """SDK calls TGProfilingInfo_EndTiming; we already have _StopTiming.
    The alias must be present and accept a token without raising."""
    token = App.TGProfilingInfo_StartTiming("test")
    App.TGProfilingInfo_EndTiming(token)  # must not raise


def test_system_wrapper_time_since_frame_start_returns_zero():
    """SelectTarget compares against `dEndTime`; with deadline = game_time + 1.0
    and time-since-frame-start = 0, the always-zero return keeps us
    inside the budget."""
    assert App.g_kSystemWrapper.GetTimeSinceFrameStart() == 0.0


def test_ship_class_get_cloaking_subsystem_returns_none():
    """FedAttack/NonFedAttack gate cloak usage on this being truthy;
    None keeps the non-cloak path live."""
    ship = ShipClass()
    assert ship.GetCloakingSubsystem() is None


def test_weapon_hit_event_get_firing_object_aliases_get_source():
    """SDK SelectTarget reads pEvent.GetFiringObject(); we expose
    GetSource(). Add an alias that does the same thing."""
    evt = WeaponHitEvent()
    source = ShipClass()
    evt.SetSource(source)
    assert evt.GetFiringObject() is source
