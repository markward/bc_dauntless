"""Order pin (combat-effect-queue spec 4.2, inventory rule R2): the hit that
kills a ship posts ET_OBJECT_EXPLODING BEFORE its own ET_WEAPON_HIT, and the
explosion names the firer as the killer.

Dispatch is synchronous today, so MissionLib.ObjectStartedExploding (kill
attribution, friendly-fire game over) and every mission ObjectDestroyed handler
run while the victim's hull is already at zero but before the hit's WeaponHit
handlers (ConditionAttacked*, FriendlyFireHandler, per-ship hit handlers). A
boundary queue that delivers in a different order changes which handler sees
the other's effects. docs/reference/engine/native-combat/event-inventory.md
section 5 (R2).
"""
import App
import pytest

from engine.appc.combat import apply_hit
from engine.appc.math import TGPoint3
from tests.unit.test_rock_class import _make
from tests.unit.test_rock_death import _in_set, _fresh_sets  # noqa: F401


class _Recorder:
    """Spy on the event manager: the types in post order, plus each event."""

    def __init__(self, monkeypatch):
        self.seen = []
        real = App.g_kEventManager.AddEvent

        def spy(evt):
            self.seen.append((evt.GetEventType(), evt))
            return real(evt)

        monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)

    def types(self):
        return [t for t, _ in self.seen]

    def first(self, event_type):
        return next(e for t, e in self.seen if t == event_type)


@pytest.mark.parametrize("genus", [App.GENUS_SHIP, App.GENUS_ASTEROID],
                         ids=["ship", "rock"])
def test_killing_hit_posts_exploding_before_its_weapon_hit(monkeypatch, genus):
    killer = _make(App.GENUS_SHIP)
    _in_set(killer, "Killer")
    victim = _make(genus)
    _in_set(victim, "Victim")
    rec = _Recorder(monkeypatch)

    apply_hit(victim, 1e9, TGPoint3(0.0, 0.0, 0.0), source=killer)

    assert victim.IsDying()                        # the hit WAS lethal
    types = rec.types()
    assert App.ET_OBJECT_EXPLODING in types
    assert App.ET_WEAPON_HIT in types
    assert types.index(App.ET_OBJECT_EXPLODING) < types.index(App.ET_WEAPON_HIT)
    assert rec.first(App.ET_OBJECT_EXPLODING).GetFiringPlayerID() == killer.GetObjID()
