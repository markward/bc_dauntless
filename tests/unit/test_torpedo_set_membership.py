"""Torpedoes become real set members — emitter gaps #6/#7.

Until now a torpedo lived ONLY in `projectiles._active`, never in a
`SetClass`. Three consequences, all of them dead SDK code:

  * `ET_TORPEDO_ENTERED_SET` / `_EXITED_SET` never fired, so
    `Conditions/ConditionIncomingTorps.py:180,182` and E8M2's two handlers
    were unreachable.
  * `pSet.GetClassObjectList(App.CT_TORPEDO)` always returned `[]`, so
    `AI/Preprocessors.py:705`'s incoming-damage estimate always read zero
    (an AI would happily double-fire at a target already taking lethal
    torpedoes) and `ConditionIncomingTorps.PeriodicCheck` saw nothing.
  * `App.ObjectClass_Cast(torpedo)` returned None, because `Torpedo`
    extended `TGObject` rather than `ObjectClass` — the hard stop at the top
    of `ConditionIncomingTorps.EnteredSet`.

Torpedo evasion itself already worked, via the 1 Hz polling path
(`AIScriptAssist_GetIncomingTorpIDsInSet`, re-armed each tick by the AI
driver). This does not replace that; it removes ~1 s of gate latency and
makes BC's own condition and mission beats reachable.
"""
import App
import pytest

from engine.appc import projectiles
from engine.appc.projectiles import Torpedo
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def clean_registry():
    """`_active` is module-global; a leaked torpedo pollutes later tests."""
    yield
    for t in list(projectiles._active):
        projectiles.expire(t)


@pytest.fixture
def scene():
    """A set holding one ship, the way a mission set does."""
    kset = SetClass()
    kset.SetName("TestSystem")
    App.g_kSetManager._sets["TestSystem"] = kset
    ship = ShipClass()
    kset.AddObjectToSet(ship, "Shooter")
    yield kset, ship
    App.g_kSetManager._sets.pop("TestSystem", None)


def _fired_from(ship) -> Torpedo:
    torp = Torpedo()
    torp._source_ship = ship
    projectiles.register(torp)
    return torp


@pytest.fixture
def posted(monkeypatch):
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


# ── identity ────────────────────────────────────────────────────────────────

def test_a_torpedo_is_an_object_class():
    """ConditionIncomingTorps.EnteredSet does ObjectClass_Cast FIRST and bails
    on None, so every other behaviour here is unreachable without this."""
    from engine.appc.objects import ObjectClass

    assert isinstance(Torpedo(), ObjectClass)
    assert App.ObjectClass_Cast(Torpedo()) is not None


def test_a_torpedo_still_casts_as_a_torpedo():
    """The promotion must not break the narrower cast -- EnteredSet calls
    Torpedo_Cast immediately after ObjectClass_Cast, and a ship must still
    fail it (a truthy stub here once made every ship look like a torpedo)."""
    assert App.Torpedo_Cast(Torpedo()) is not None
    assert App.Torpedo_Cast(ShipClass()) is None


# ── membership lifecycle ────────────────────────────────────────────────────

def test_registering_joins_the_source_ships_set(scene):
    kset, ship = scene
    torp = _fired_from(ship)

    assert torp.GetContainingSet() is kset
    assert torp in kset.GetClassObjectList(App.CT_TORPEDO)


def test_expiring_leaves_the_set(scene):
    kset, ship = scene
    torp = _fired_from(ship)
    projectiles.expire(torp)

    assert kset.GetClassObjectList(App.CT_TORPEDO) == []


def test_two_torpedoes_do_not_collide_in_the_set(scene):
    """`SetClass._objects` is keyed by NAME. Same name => the second silently
    replaces the first and the set undercounts."""
    kset, ship = scene
    a, b = _fired_from(ship), _fired_from(ship)

    assert a.GetName() != b.GetName()
    assert set(kset.GetClassObjectList(App.CT_TORPEDO)) == {a, b}


def test_a_torpedo_with_no_set_still_registers(scene):
    """Headless fixtures fire from ships in no set. The projectile must still
    fly -- `_active` is what drives motion -- it just joins no set."""
    _kset, _ship = scene
    orphan = ShipClass()
    torp = _fired_from(orphan)

    assert torp in projectiles._active
    assert torp.GetContainingSet() is None


# ── the events ──────────────────────────────────────────────────────────────

def test_registering_posts_entered_set(scene, posted):
    _kset, ship = scene
    torp = _fired_from(ship)

    evts = _of_type(posted, App.ET_TORPEDO_ENTERED_SET)
    assert len(evts) == 1
    assert evts[0].GetDestination() is torp, (
        "ConditionIncomingTorps.EnteredSet reads GetDestination()")


def test_expiring_posts_exited_set(scene, posted):
    _kset, ship = scene
    torp = _fired_from(ship)
    posted.clear()
    projectiles.expire(torp)

    evts = _of_type(posted, App.ET_TORPEDO_EXITED_SET)
    assert len(evts) == 1
    assert evts[0].GetDestination() is torp


def test_a_setless_torpedo_posts_nothing(scene, posted):
    """No set joined, so no set was entered. Posting anyway would make
    ConditionIncomingTorps track a torpedo its PeriodicCheck can never find."""
    _kset, _ship = scene
    _fired_from(ShipClass())

    assert _of_type(posted, App.ET_TORPEDO_ENTERED_SET) == []


def test_expiring_twice_posts_one_exit(scene, posted):
    """`expire` is called from several places and is deliberately tolerant of
    a torpedo already gone; the event must not double-fire."""
    _kset, ship = scene
    torp = _fired_from(ship)
    posted.clear()
    projectiles.expire(torp)
    projectiles.expire(torp)

    assert len(_of_type(posted, App.ET_TORPEDO_EXITED_SET)) == 1


def test_naming_does_not_post_name_change(scene, posted):
    """`ObjectClass.SetName` posts ET_NAME_CHANGE on a RENAME (old name
    non-empty). Naming a torpedo twice would post one per torpedo per spawn --
    a broadcast storm at combat fire rates. Name once, at register."""
    _kset, ship = scene
    _fired_from(ship)

    assert _of_type(posted, App.ET_NAME_CHANGE) == []


# ── regression guards ───────────────────────────────────────────────────────

def test_torpedoes_stay_out_of_the_ship_roster(scene):
    """iter_ships drives AI, motion, combat and subsystem updates. A torpedo
    appearing there would be simulated as a ship."""
    from engine.appc.ship_iter import iter_ships

    _kset, ship = scene
    torp = _fired_from(ship)
    roster = list(iter_ships())

    assert ship in roster
    assert torp not in roster


def test_torpedoes_do_not_broadcast_the_ship_set_events(scene, posted):
    """BC has separate constants for torpedoes. `_broadcast_set_transition`
    keeps its ShipClass filter, so a torpedo must not also raise the ship
    pair -- ConditionIncomingTorps registers for BOTH and would double-count."""
    _kset, ship = scene
    _fired_from(ship)

    assert _of_type(posted, App.ET_ENTERED_SET) == []


def test_a_torpedo_is_not_a_contact(scene):
    """contact_index buckets set members for perception. Torpedoes must not
    become sensor contacts or they would appear in the target list."""
    from engine.appc import contact_index

    kset, ship = scene
    torp = _fired_from(ship)

    assert torp not in contact_index.ships_in(kset)


# ── the accessors the newly-live SDK loop reads ─────────────────────────────
# AI/Preprocessors.py:705-709 walks GetClassObjectList(CT_TORPEDO) and reads
# GetTargetID()/GetDamage() off each torpedo. That loop was unreachable while
# the list was empty, so neither accessor existed -- and both would have read
# a truthy _Stub the moment set membership made the loop live.

def test_a_homing_torpedo_reports_its_targets_id(scene):
    _kset, ship = scene
    victim = ShipClass()
    torp = _fired_from(ship)
    torp._target_ship = victim

    assert torp.GetTargetID() == victim.GetObjID()


def test_a_dumbfire_torpedo_reports_null_id(scene):
    """It must not match a real target's id, or every unguided torpedo would
    be counted as inbound on whatever the AI is considering."""
    _kset, ship = scene
    torp = _fired_from(ship)

    assert torp.GetTargetID() == App.NULL_ID
    assert torp.GetTargetID() != ShipClass().GetObjID()


def test_damage_is_readable_as_a_number(scene):
    """Preprocessors does `fIncomingDamage + pTorp.GetDamage()`; a _Stub here
    would raise inside a preprocessor rather than return a wrong number."""
    _kset, ship = scene
    torp = _fired_from(ship)
    torp.SetDamage(250.0)

    assert torp.GetDamage() == 250.0
    assert 0.0 + torp.GetDamage() == 250.0


def test_the_preprocessor_estimate_now_totals_inbound_damage(scene):
    """End-to-end shape of AI/Preprocessors.py:705-709: sum the damage of
    every in-flight torpedo already homing on this target. Before set
    membership this loop had nothing to iterate and always produced 0.0."""
    kset, ship = scene
    victim = ShipClass()
    kset.AddObjectToSet(victim, "Victim")
    bystander = ShipClass()

    for dmg, tgt in ((100.0, victim), (150.0, victim), (999.0, bystander)):
        t = _fired_from(ship)
        t.SetDamage(dmg)
        t._target_ship = tgt

    inbound = sum(t.GetDamage() for t in kset.GetClassObjectList(App.CT_TORPEDO)
                  if t.GetTargetID() == victim.GetObjID())

    assert inbound == 250.0, "the bystander's torpedo must not be counted"
