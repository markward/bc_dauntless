"""Order pin (combat-effect-queue spec 4.2, inventory rule R2, revised by
native-damage ruling M5): the hit that kills a ship posts its own
ET_WEAPON_HIT first; the death check runs at the tick boundary
(engine/appc/death_check.py), so ET_OBJECT_EXPLODING follows it there, and
the explosion still names the firer as the killer.

Before M5 the death began inside the hit, so ET_OBJECT_EXPLODING came first
and MissionLib.ObjectStartedExploding ran before the hit's WeaponHit handlers.
M5 moves every death to the boundary -- E3M5's KillGonDev zeroes a hull and
only then makes the ship invincible, which an in-hit death check would kill
-- so a WeaponHit handler now sees the victim at hull 0 but not yet dying.
docs/superpowers/specs/2026-11-02-native-damage-design.md (M5) and
docs/reference/engine/native-combat/event-inventory.md section 5 (R2).
"""
import App
import pytest

from engine.appc import death_check
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
def test_killing_hit_posts_its_weapon_hit_then_exploding_at_the_boundary(
        monkeypatch, genus):
    killer = _make(App.GENUS_SHIP)
    _in_set(killer, "Killer")
    victim = _make(genus)
    _in_set(victim, "Victim")
    rec = _Recorder(monkeypatch)

    apply_hit(victim, 1e9, TGPoint3(0.0, 0.0, 0.0), source=killer)

    assert not victim.IsDying()                    # not inside the hit (M5)
    assert App.ET_OBJECT_EXPLODING not in rec.types()
    death_check.drain()                            # the tick boundary

    assert victim.IsDying()                        # the hit WAS lethal
    types = rec.types()
    assert App.ET_OBJECT_EXPLODING in types
    assert App.ET_WEAPON_HIT in types
    assert types.index(App.ET_WEAPON_HIT) < types.index(App.ET_OBJECT_EXPLODING)
    assert rec.first(App.ET_OBJECT_EXPLODING).GetFiringPlayerID() == killer.GetObjID()
