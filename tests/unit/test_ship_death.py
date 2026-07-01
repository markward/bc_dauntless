# tests/unit/test_ship_death.py
"""Unit tests for the ship death sequence (engine/appc/ship_death.py)."""
import pytest

from engine.appc import ship_death


class FakeSet:
    """Minimal SetClass stand-in recording removals by name."""
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)


class FakeShip:
    """Minimal ship: lifecycle flags + name + containing set + radius."""
    def __init__(self, name="Enemy1", containing_set=None, radius=1.0):
        self._name = name
        self._set = containing_set if containing_set is not None else FakeSet()
        self._radius = radius
        self._dying = False
        self._dead = False
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return self._radius
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


@pytest.fixture(autouse=True)
def _clean_registry():
    ship_death.reset()
    yield
    ship_death.reset()


def test_begin_marks_ship_dying():
    ship = FakeShip()
    ship_death.begin(ship)
    assert ship.IsDying() == 1
    assert ship.IsDead() == 0


def test_begin_is_idempotent():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.begin(ship)  # second call must not double-register
    # Advance just short of the throes window: still exactly one entry, alive.
    ship_death.advance(ship_death.THROES_DURATION - 0.01)
    assert ship.IsDead() == 0


def test_advance_marks_dead_at_throes_but_keeps_wreck_in_set():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)   # throes expire
    # Death-marker fired, but the wreck lingers — NOT removed yet.
    assert ship.IsDead() == 1
    assert s.removed == []
    assert ship_death.is_targetable_wreck(ship) is True


def test_advance_removes_wreck_after_throes_plus_linger():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)        # -> linger
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)  # linger expires
    assert s.removed == ["Doomed"]
    assert ship_death.is_targetable_wreck(ship) is False


def test_advance_does_not_kill_before_throes_elapse():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION / 2.0)
    assert ship.IsDead() == 0
    assert ship.IsDying() == 1


def test_wreck_entry_pruned_after_final_removal():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)  # removed once
    s.removed.clear()
    ship_death.advance(1.0)   # entry pruned -> no second removal
    assert s.removed == []


def test_is_targetable_wreck_false_for_untracked_ship():
    ship = FakeShip()
    assert ship_death.is_targetable_wreck(ship) is False


def test_locks_clear_only_at_final_removal(monkeypatch):
    cleared = []
    monkeypatch.setattr(ship_death, "_clear_target_locks",
                        lambda s: cleared.append(s))
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    assert cleared == []                 # not cleared at throes end
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)
    assert cleared == [ship]             # cleared only at linger end


def test_destroyed_event_fires_at_throes_not_linger():
    import App
    seen = []
    orig = App.g_kEventManager.AddEvent

    def capture(evt):
        seen.append(evt.GetEventType())
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    try:
        ship = FakeShip()
        ship_death.begin(ship)
        ship_death.advance(ship_death.THROES_DURATION)
        assert App.ET_OBJECT_DESTROYED in seen   # fired at the 5s mark
        assert ship.IsDead() == 1
        assert ship._set.removed == []           # still in set (lingering)
    finally:
        App.g_kEventManager.AddEvent = orig


def test_reset_clears_registry():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.reset()
    ship_death.advance(ship_death.THROES_DURATION)
    assert ship.IsDead() == 0  # nothing ticked


def test_out_of_action_predicate():
    ship = FakeShip()
    assert ship_death._out_of_action(ship) is False
    ship.SetDying(True)
    assert ship_death._out_of_action(ship) is True
    ship.SetDying(False)
    ship.SetDead(True)
    assert ship_death._out_of_action(ship) is True


def test_begin_ignores_none():
    ship_death.begin(None)  # must not raise
    ship_death.advance(ship_death.THROES_DURATION)  # registry stayed empty


def test_advance_prunes_ship_with_no_set():
    ship = FakeShip()
    ship._set = None  # GetContainingSet() -> None
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)  # must not raise
    assert ship.IsDead() == 1


# --- Task 2: critical-flag trigger via DamageSystem -------------------------
from engine.appc.objects import DamageableObject


class FakeSub:
    """Subsystem with condition + critical flag (mirrors ShipSubsystem)."""
    def __init__(self, max_condition=100.0, critical=0):
        self._cond = float(max_condition)
        self._max = float(max_condition)
        self._critical = int(critical)
        self._destroyed = False
    def GetCondition(self):      return self._cond
    def SetCondition(self, v):   self._cond = max(0.0, float(v))
    def GetMaxCondition(self):   return self._max
    def IsCritical(self):        return self._critical
    def SetDestroyed(self, v):   self._destroyed = bool(v)
    def IsDestroyed(self):       return 1 if self._destroyed else 0


class FakeDamageable(DamageableObject):
    """DamageableObject with a hull + lifecycle flags, for trigger tests."""
    def __init__(self):
        super().__init__()
        self._hull = FakeSub(critical=1)
        self._dying = False
        self._dead = False
        self._name = "Subject"
        self._set = FakeSet()
    def GetHull(self):           return self._hull
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return 1.0
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


def test_damaging_critical_subsystem_to_zero_triggers_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 100.0)  # hull is critical
    assert obj.IsDying() == 1


def test_damaging_noncritical_subsystem_to_zero_does_not_trigger_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DamageSystem(sensors, 100.0)
    assert sensors.GetCondition() == 0.0
    assert obj.IsDying() == 0


def test_warp_core_critical_triggers_death():
    obj = FakeDamageable()
    warp_core = FakeSub(critical=1)
    obj.DamageSystem(warp_core, 100.0)
    assert obj.IsDying() == 1


def test_partial_damage_does_not_trigger_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 40.0)  # hull still at 60
    assert obj.IsDying() == 0


def test_killing_blow_on_dying_ship_is_no_op():
    """A second killing blow through DamageSystem on an already-dying ship
    must not re-trigger begin (the IsDying guard prevents double-register)."""
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 100.0)  # first kill -> dying
    assert obj.IsDying() == 1
    obj.DamageSystem(obj.GetHull(), 100.0)  # second blow -> still just dying
    assert obj.IsDying() == 1
    assert len(ship_death._active) == 1


# --- Task 3: DestroySystem --------------------------------------------------
def test_destroy_system_on_critical_kills():
    obj = FakeDamageable()
    obj.DestroySystem(obj.GetHull())
    assert obj.GetHull().GetCondition() == 0.0
    assert obj.GetHull().IsDestroyed() == 1
    assert obj.IsDying() == 1


def test_destroy_system_on_noncritical_zeroes_but_no_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DestroySystem(sensors)
    assert sensors.GetCondition() == 0.0
    assert sensors.IsDestroyed() == 1
    assert obj.IsDying() == 0


def test_destroy_system_none_is_noop():
    obj = FakeDamageable()
    obj.DestroySystem(None)  # must not raise
    assert obj.IsDying() == 0


# --- Task 4: host-loop wiring ------------------------------------------------
def test_host_loop_advance_combat_ticks_death():
    """_advance_combat must call ship_death.advance so dying ships progress."""
    import engine.host_loop as host_loop
    ship = FakeShip(name="Tick")
    ship_death.begin(ship)
    # Drive the per-frame combat hub with no ships and a full-throes dt.
    host_loop._advance_combat([], ship_death.THROES_DURATION)
    assert ship.IsDead() == 1


def test_mission_teardown_calls_ship_death_reset():
    """The mission-swap teardown must clear the death registry (no dangling
    throes). The real teardown lives in _drain_pending_swap, alongside
    ship_lifecycle.reset()."""
    import engine.host_loop as host_loop
    import inspect
    src = inspect.getsource(host_loop.HostController._drain_pending_swap)
    assert "ship_death.reset()" in src


# --- Task 5: AI gate --------------------------------------------------------
def test_dying_ship_ai_tick_returns_done_without_running():
    from engine.appc import ai_driver
    from engine.appc.ai import PlainAI, ArtificialIntelligence

    class SpyAI(PlainAI):
        def __init__(self, ship):
            super().__init__()
            self._ship = ship

    ship = FakeShip(name="AIShip")
    ship.SetDying(True)
    ai = SpyAI(ship)

    status = ai_driver.tick_ai(ai, 0.0)
    assert status == ArtificialIntelligence.US_DONE


def test_alive_ship_ai_tick_not_gated():
    from engine.appc import ai_driver
    from engine.appc.ai import PlainAI
    ship = FakeShip(name="LiveShip")  # not dying
    ai = PlainAI()
    ai._ship = ship
    # Should not raise and should not be force-returned by the death gate.
    ai_driver.tick_ai(ai, 0.0)


# --- Task 6: weapon gate ----------------------------------------------------
def test_weapon_offline_when_parent_ship_dying():
    from engine.appc.subsystems import _is_offline

    class FakeWeapon:
        def __init__(self, ship):
            self._ship = ship
        def IsDisabled(self):   return 0
        def IsDestroyed(self):  return 0
        def GetParentShip(self): return self._ship

    ship = FakeShip(name="Gunner")
    weapon = FakeWeapon(ship)
    assert _is_offline(weapon) is False  # alive: weapon online
    ship.SetDying(True)
    assert _is_offline(weapon) is True   # dying: weapon gated offline


def test_weapon_offline_unaffected_when_no_parent_ship():
    from engine.appc.subsystems import _is_offline

    class FakeWeaponNoShip:
        def IsDisabled(self):   return 0
        def IsDestroyed(self):  return 0
        def GetParentShip(self): return None

    assert _is_offline(FakeWeaponNoShip()) is False


# --- Task 7: explosion VFX --------------------------------------------------
def test_begin_spawns_explosion_controller():
    """begin must register at least one particle controller targeting an
    Explosion sprite."""
    from engine.appc import particles
    particles.reset()
    ship = FakeShip(name="Boom", radius=3.0)
    ship_death.begin(ship)
    descriptors = particles.snapshot_descriptors()
    assert len(descriptors) >= 1
    paths = [d.get("texture_path", "") for d in descriptors]
    assert any("Explosion" in p for p in paths)
    particles.reset()


def test_spawn_explosion_raise_safe(monkeypatch):
    """If the SDK Effects call raises, begin must still mark the ship dying."""
    import Effects
    def boom(*a, **k):
        raise RuntimeError("no backend")
    monkeypatch.setattr(Effects, "CreateExplosionPuffHigh", boom)
    ship = FakeShip(name="Safe")
    ship_death.begin(ship)  # must not raise
    assert ship.IsDying() == 1


# --- Task 8: ET_OBJECT_DESTROYED broadcast ----------------------------------
def test_app_defines_object_destroyed_constant():
    import App
    assert isinstance(App.ET_OBJECT_DESTROYED, int)


def test_death_broadcasts_object_destroyed_once():
    import App
    from engine.appc.events import TGPythonInstanceWrapper

    fired = {"count": 0, "source_name": None}

    class Listener:
        def Destroyed(self, pEvent):
            fired["count"] += 1
            src = pEvent.GetSource()
            fired["source_name"] = src.GetName() if src is not None else None

    listener = Listener()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(listener)

    ship = FakeShip(name="Marked")
    # Register a per-source method handler keyed on this ship (the SDK
    # ConditionDestroyed pattern: target == the watched object).
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_OBJECT_DESTROYED, wrapper, "Destroyed", ship)

    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)

    assert fired["count"] == 1
    assert fired["source_name"] == "Marked"

    App.g_kEventManager.RemoveAllInstanceHandlers()


# --- ET_OBJECT_EXPLODING broadcast (BC "started exploding") ------------------
def test_app_defines_object_exploding_constant():
    import App
    assert isinstance(App.ET_OBJECT_EXPLODING, int)
    assert App.ET_OBJECT_EXPLODING != App.ET_OBJECT_DESTROYED


def test_begin_broadcasts_object_exploding_immediately():
    """BC fires ET_OBJECT_EXPLODING the instant the throes start — this is the
    event E1M2 (and 23 other SDK missions) subscribe to for kill-detection.
    It must fire at begin(), before any advance()."""
    import App
    seen = []
    orig = App.g_kEventManager.AddEvent

    def capture(evt):
        seen.append(evt.GetEventType())
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    try:
        ship = FakeShip(name="Debris1")
        ship_death.begin(ship)
        # EXPLODING fires at throes-start, before ET_OBJECT_DESTROYED (removal).
        assert App.ET_OBJECT_EXPLODING in seen
        assert App.ET_OBJECT_DESTROYED not in seen
    finally:
        App.g_kEventManager.AddEvent = orig


def test_exploding_reaches_broadcast_func_handler_with_destination():
    """The E1M2 ObjectDestroyed pattern: a func-broadcast handler on
    ET_OBJECT_EXPLODING that reads pEvent.GetDestination() to identify the
    dying ship. Verifies the event carries destination == the ship."""
    import App
    import sys

    fired = {"count": 0, "dest_name": None}

    mod = sys.modules[__name__]

    def _on_exploding(pMission, pEvent):
        fired["count"] += 1
        dest = pEvent.GetDestination()
        fired["dest_name"] = dest.GetName() if dest is not None else None

    mod._on_exploding = _on_exploding
    try:
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_OBJECT_EXPLODING, object(), __name__ + "._on_exploding")
        ship = FakeShip(name="Debris3")
        ship_death.begin(ship)
        assert fired["count"] == 1
        assert fired["dest_name"] == "Debris3"
    finally:
        App.g_kEventManager.RemoveAllInstanceHandlers()
        App.g_kEventManager._broadcast_handlers.clear()
        del mod._on_exploding


# --- Death script (SDK SetDeathScript) --------------------------------------
# Module-level probe target for RunDeathScript resolution (SDK death-script
# signature: def Func(TGObject) — a single arg, the dying object).
_death_probe_calls = []


def _death_probe(obj):
    _death_probe_calls.append(obj)


def _death_probe_raises(obj):
    raise RuntimeError("boom in death script")


def test_ship_class_run_death_script_calls_target_with_ship():
    from engine.appc.ships import ShipClass
    _death_probe_calls.clear()
    ship = ShipClass()
    ship.SetDeathScript(__name__ + "._death_probe")
    assert ship.GetDeathScript() == __name__ + "._death_probe"
    ship.RunDeathScript()
    assert _death_probe_calls == [ship]     # called once, sole arg = the ship


def test_ship_class_run_death_script_none_is_noop():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    assert ship.GetDeathScript() is None
    ship.RunDeathScript()                   # must not raise


def test_ship_class_run_death_script_swallows_raise():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.SetDeathScript(__name__ + "._death_probe_raises")
    ship.RunDeathScript()                   # exception swallowed, no propagation


def test_begin_invokes_run_death_script_once():
    """ship_death.begin() runs the object's authored death script at throes
    start (the SDK moment BC calls RunDeathScript)."""
    class DeathScriptShip(FakeShip):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.ran = 0
        def RunDeathScript(self):
            self.ran += 1

    ship = DeathScriptShip(name="Debris1")
    ship_death.begin(ship)
    assert ship.ran == 1


def test_begin_skips_run_death_script_when_absent():
    """A ship without RunDeathScript (e.g. non-ship object) is handled
    gracefully — begin() must not raise."""
    ship = FakeShip(name="Rock")          # plain FakeShip has no RunDeathScript
    ship_death.begin(ship)                # must not raise
    assert ship.IsDying() == 1


# --- Firing-player-id on the explosion event --------------------------------
class FakeAttacker:
    """Minimal killer: only needs GetObjID (BC's firing-player-id is the
    firing ship's object id)."""
    def __init__(self, obj_id):
        self._id = obj_id
    def GetObjID(self):
        return self._id


def _capture_exploding_event(run):
    """Run `run()` while capturing the ObjectExplodingEvent that ship_death
    broadcasts. Returns the captured event (or None)."""
    import App
    captured = {"evt": None}
    orig = App.g_kEventManager.AddEvent

    def capture(evt):
        if evt.GetEventType() == App.ET_OBJECT_EXPLODING:
            captured["evt"] = evt
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    try:
        run()
    finally:
        App.g_kEventManager.AddEvent = orig
    return captured["evt"]


def test_exploding_event_carries_killer_firing_player_id():
    import App
    attacker = FakeAttacker(4242)
    ship = FakeShip(name="Victim")
    evt = _capture_exploding_event(lambda: ship_death.begin(ship, killer=attacker))
    assert evt is not None
    assert evt.GetFiringPlayerID() == 4242


def test_exploding_event_null_id_when_unattributed():
    import App
    ship = FakeShip(name="Victim")
    evt = _capture_exploding_event(lambda: ship_death.begin(ship))
    assert evt is not None
    assert evt.GetFiringPlayerID() == App.NULL_ID


def test_damage_system_threads_killer_into_exploding_event():
    """End-to-end: a fatal DamageSystem hit attributes the kill on the
    exploding event via the source (firing ship)."""
    target = FakeDamageable()             # critical hull + real lifecycle flags
    attacker = FakeAttacker(7777)
    evt = _capture_exploding_event(
        lambda: target.DamageSystem(target.GetHull(), 100.0, attacker))
    assert evt is not None
    assert target.IsDying() == 1
    assert evt.GetFiringPlayerID() == 7777


# --- Sprite-sheet explosion animation ---------------------------------------
def test_anim_controller_texture_cells_default_and_set():
    """AnimTSParticleController defaults to a 1x1 grid (whole texture); the
    descriptor carries atlas_cols/atlas_rows; SetTextureCells overrides them."""
    from engine.appc import particles
    c = particles.AnimTSParticleController_Create()
    c.CreateTarget("x.tga")
    d = particles._descriptor_for(c, None)
    assert d["atlas_cols"] == 1 and d["atlas_rows"] == 1   # default whole-texture
    c.SetTextureCells(8, 8)
    d = particles._descriptor_for(c, None)
    assert d["atlas_cols"] == 8 and d["atlas_rows"] == 8


def test_death_explosion_is_explosionA_8x8_sheet():
    """The death explosion forces the colour ExplosionA sheet and declares its
    8x8 sprite-sheet grid so the renderer animates frames + varies the row."""
    from engine.appc import particles
    particles.reset()
    ship = FakeShip(name="Boom", radius=3.0)
    ship_death.begin(ship)
    descriptors = particles.snapshot_descriptors()
    sheets = [d for d in descriptors
              if "ExplosionA" in d.get("texture_path", "")
              and d.get("atlas_cols") == 8 and d.get("atlas_rows") == 8]
    assert len(sheets) >= 1
    particles.reset()


def test_death_explosion_tuning():
    """Per-puff life drives the 8-frame animation duration; the emit radius
    spreads puffs across a hull-sized sphere; the size is the 0.75 factor."""
    from engine.appc import particles
    particles.reset()
    radius = 4.0
    ship = FakeShip(name="Tuned", radius=radius)
    ship_death.begin(ship)
    sheets = [d for d in particles.snapshot_descriptors()
              if "ExplosionA" in d.get("texture_path", "")]
    assert sheets
    d = sheets[0]
    assert d["emit_life"] == ship_death.EXPLOSION_PUFF_LIFE          # slower animation
    assert d["emit_radius"] == radius * ship_death.EXPLOSION_SPREAD_FACTOR  # hull spread
    assert ship_death.EXPLOSION_SIZE_FACTOR == 0.75                  # smaller puffs
    # Exactly EXPLOSION_COUNT births: spacing covers the throes evenly and
    # the emission window admits births 0..COUNT-1 only.
    spacing = ship_death.THROES_DURATION / ship_death.EXPLOSION_COUNT
    assert d["emit_frequency"] == spacing
    births = [i * spacing for i in range(ship_death.EXPLOSION_COUNT + 2)
              if i * spacing <= d["stop_age"]]
    assert len(births) == ship_death.EXPLOSION_COUNT
    particles.reset()


def test_emitter_seed_is_stable_and_distinct():
    """Per-particle randomness must derive from a per-emitter seed that is
    constant across snapshots (a moving emitter must not re-roll particles
    every frame) and differs between emitters (no twin explosions)."""
    from engine.appc import particles
    c1 = particles.AnimTSParticleController_Create()
    c2 = particles.AnimTSParticleController_Create()
    s1a = particles._descriptor_for(c1, None)["seed"]
    s1b = particles._descriptor_for(c1, None)["seed"]
    s2 = particles._descriptor_for(c2, None)["seed"]
    assert s1a == s1b                 # stable across snapshots
    assert s1a != s2                  # distinct between emitters
    assert 0.0 <= s1a < 1.0


def test_descriptor_anchors_at_last_world_location_when_unresolved():
    """When the emit-from ship has no render instance (removed at death),
    the descriptor anchors at the ship's last world location so the
    explosion finishes at the wreck site."""
    from engine.appc import particles

    class _Loc:
        x, y, z = 10.0, -5.0, 3.0

    class _Wreck:
        def GetWorldLocation(self):
            return _Loc()

    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(_Wreck())
    d = particles._descriptor_for(c, resolve_attach=lambda obj: None)
    assert d["instance_id"] is None
    assert d["emit_pos"] == (10.0, -5.0, 3.0)


# --- Target-lock release at end of death sequence ----------------------------
def test_locks_held_through_throes_and_released_at_finish():
    """Locks on the dying ship persist through the throes window AND the linger
    window (the player keeps watching the selectable wreck) and release only at
    the END of the full sequence (throes + linger) — both the target and the
    targeted-subsystem lock (which BC stores on the FIRING ship). Unrelated
    locks survive throughout."""
    import App
    from engine.appc.ships import ShipClass

    pSet = App.SetClass()
    attacker = ShipClass(); attacker.SetName("Attacker")
    bystander = ShipClass(); bystander.SetName("Bystander")
    victim = ShipClass(); victim.SetName("Victim")
    other = ShipClass(); other.SetName("Other")
    for s in (attacker, bystander, victim, other):
        pSet.AddObjectToSet(s, s.GetName())
    # iter_ships walks g_kSetManager — register the set as the game does.
    App.g_kSetManager.AddSet(pSet, "lock_test")
    try:
        attacker.SetTarget(victim)
        attacker.SetTargetSubsystem(object())  # subsystem lock rides on attacker
        bystander.SetTarget(other)             # unrelated lock must survive

        ship_death.begin(victim)
        ship_death.advance(ship_death.THROES_DURATION / 2.0)
        # Mid-throes: still locked on the dying ship.
        assert attacker.GetTarget() is victim
        assert attacker.GetTargetSubsystem() is not None

        ship_death.advance(ship_death.THROES_DURATION / 2.0)
        # Throes elapsed: ship is dead and marked, but still lingering as a
        # selectable wreck — locks persist, wreck not removed yet.
        assert victim.IsDead() == 1
        assert attacker.GetTarget() is victim
        assert attacker.GetTargetSubsystem() is not None

        ship_death.advance(ship_death.WRECK_LINGER_DURATION)
        # Full sequence complete: locks on the wreck released; unrelated kept.
        assert attacker.GetTarget() is None
        assert attacker.GetTargetSubsystem() is None
        assert bystander.GetTarget() is other
    finally:
        App.g_kSetManager._sets.pop("lock_test", None)
