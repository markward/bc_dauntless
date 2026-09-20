"""TGTimerManager.AddTimer must return the timer id.

Conditions/ConditionAttacked.py:198-205 and ConditionAttackedBy.py (mirror):
    if App.g_kTimerManager.AddTimer( pTimer ):
        self.idForgivenessTimer[sSource] = pTimer.GetObjID()
Returning None meant the id was never recorded, so StopForgivenessTimer
never deleted anything and the forgiveness timer fired regardless of later
hits -- the conditions reached TRUE less often than BC.
"""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.events import WeaponHitEvent
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def test_add_timer_returns_the_objid():
    t = App.TGTimer_Create()
    t.SetTimerStart(App.g_kTimerManager.get_time() + 5.0)
    got = App.g_kTimerManager.AddTimer(t)
    assert got == t.GetObjID()
    App.g_kTimerManager.DeleteTimer(got)
    assert got not in App.g_kTimerManager._timers


def test_condition_attacked_records_its_forgiveness_timer():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    victim = ShipClass()
    victim._hull = HullSubsystem("H")
    victim._hull.SetMaxCondition(1000.0)
    shields = ShieldSubsystem("Shields")
    shields.SetMaxShields(ShieldSubsystem.FRONT_SHIELDS, 100.0)
    victim.SetShieldSubsystem(shields)
    pSet.AddObjectToSet(victim, "Victim")

    shooter = ShipClass()
    shooter._hull = HullSubsystem("H")
    shooter._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(shooter, "Shooter")

    # Thresholds high so a 10-damage hit against a 100-max shield (10%)
    # stays UNDER threshold -- that's the branch that starts the
    # forgiveness timer (AddShieldDamage -> StartForgivenessTimer).
    cond = ConditionScript_Create(
        "Conditions.ConditionAttacked", "ConditionAttacked",
        "Victim", 100.0, 100.0, 5.0,
    )
    cond.SetActive()
    assert cond._instance is not None, cond._init_error

    evt = WeaponHitEvent(is_hull_hit=False)
    evt.SetEventType(App.ET_WEAPON_HIT)
    evt.SetSource(shooter)
    evt.SetDestination(victim)
    evt.SetDamage(10.0)
    App.g_kEventManager.AddEvent(evt)

    timers = cond._instance.idForgivenessTimer
    assert "Shooter" in timers and isinstance(timers["Shooter"], int), (
        "forgiveness timer id was not recorded -- AddTimer returned None")
