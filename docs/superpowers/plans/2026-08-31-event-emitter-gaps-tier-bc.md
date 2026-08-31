# Event Emitter Gaps — Tier B/C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six of the nine remaining event-emitter gaps in
`docs/engine/event-emitter-gaps.md`, so their SDK handlers become reachable.

**Architecture:** Three of the six need a small piece of engine state built
before there is an edge to post on (tractor firing transitions, target-list
membership); one needs a missing accessor before its handler can branch
correctly (`TorpedoSystem.GetNumReady`); one is closed in the *negative* (the
correct action is to not emit, plus a regression test that pins it); and one
is a shared dispatch fix that is a prerequisite for the tractor work and also
repairs a live bug on the cloak indicator. No fidelity guesses: every decision
below is read off SDK handler code cited inline.

**Tech Stack:** Python 3 engine shim (`engine/appc/`), pytest, the
`scripts/check_tests.sh` gate.

**Spec:** `docs/engine/event-emitter-gaps.md` (the gap register — it is the
authority for what each handler expects; this plan argues from it).

## Global Constraints

- **Never** run `git checkout -- <path>`, `git checkout .`, `git restore`,
  `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`.
  This checkout is shared with concurrent sessions and holds uncommitted work.
  Stage with an explicit pathspec. To mutate a file temporarily, `cp` it to
  `/tmp`, mutate, restore by `cp`, and `diff` to prove byte-identity.
- The gate is `scripts/check_tests.sh` (build + pytest + ctest), **not**
  `scripts/run_tests.sh`. Never call a failure "pre-existing" by eyeball — the
  gate diffs against `tests/known_failures.txt`, which currently holds exactly
  one pytest entry (`tests/unit/test_engineer_emitters.py::test_shield_level_change_announces`)
  and zero ctest entries.
- Run long commands in the **foreground**. Do not background the gate and poll.
- Events are posted through `App.g_kEventManager.AddEvent(evt)`. Destination
  dispatch is deliberately unguarded (see `engine/appc/events.py:AddEvent`);
  do **not** wrap `AddEvent` in try/except in engine emitters.
- Never assert that an SDK call is or is not a silent no-op from reasoning —
  read `docs/stub_heatmap.md` first. An undefined attribute returns a **truthy**
  `_Stub`, and an undefined `App.<NAME>` returns a truthy `_NamedStub`.
- Do not unstub a whole SDK module to reach one function. Reimplement the one
  behaviour at the equivalent engine hook.
- Tests spy on emissions via `monkeypatch.setattr(App.g_kEventManager,
  "AddEvent", events.append)`. `AddEvent` dispatches synchronously; there is no
  drain step.
- Each task ends with its own commit. Do not batch commits across tasks.

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `engine/appc/events.py` | Modify (`:710`, `:721`, `:751-756`, `:782-788`) | Broadcast func-handler registration honours BC's destination filter argument |
| `engine/appc/weapon_subsystems.py` | Modify (`TorpedoSystem`, `TractorBeamSystem`) | `GetNumReady()` on the system; `ET_CANT_FIRE` posts; tractor firing edge-detect + start/stop posts |
| `engine/appc/target_menu.py` | Modify (`STTargetMenu.set_contacts`) | Membership diff against the previous push; `ET_TARGET_LIST_OBJECT_ADDED`/`_REMOVED` posts |
| `docs/engine/event-emitter-gaps.md` | Modify | Register updated: 6 closed, 3 remaining with reasons |
| `tests/unit/test_broadcast_handler_filter.py` | Create | Pins the destination-filter contract, both directions |
| `tests/unit/test_tier_bc_event_emitters.py` | Create | Pins all four new emitters and the `ET_SET_TARGET` non-emission |

**Out of scope, deliberately.** Gaps #6/#7 (`ET_TORPEDO_ENTERED_SET` /
`ET_TORPEDO_EXITED_SET`) need torpedoes wired into `SetClass` membership,
which changes what every `GetClassObjectList(CT_TORPEDO)` caller and the
active-set render scoping see. That is a separate subsystem change and gets
its own plan. Gap #10 (`ET_RESTORE_PERSISTENT_TARGET`) stays open: BC's engine
owns both the persistent-target storage and the restore trigger, nothing in
the SDK ever *sets* one, and naming a call site would be inventing a mechanism.

---

### Task 1: Honour BC's destination filter on broadcast func handlers

`AddBroadcastPythonFuncHandler(eType, dest, name, *extra)` currently **discards
`extra`**. BC's fourth argument is a destination filter, and 10 SDK sites pass
one. Two of them are `Bridge/PowerDisplay.py:340-341` registering `HandleCloak`
filtered to `pPlayer` — and we *do* post `ET_CLOAK_BEGINNING` /
`ET_DECLOAK_COMPLETED` (`engine/appc/subsystems.py:2511`, `:2544`, `:2629`,
`:2687`), so today any NPC's cloak repaints the player's HUD cloak indicator
from that NPC's state. This is a live pre-existing bug, and it is also a
prerequisite for Task 4: `PowerDisplay.py:337-338` registers the tractor
handler with the same filter.

`AddBroadcastPythonMethodHandler` already implements exactly this
(`engine/appc/events.py:723-735`, dispatch at `:791-793`); this task brings the
func variant to parity.

**Files:**
- Modify: `engine/appc/events.py:710`, `:717-721`, `:751-756`, `:782-788`
- Test: `tests/unit/test_broadcast_handler_filter.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is first).
- Produces: `_broadcast_handlers[event_type]` entries become **3-tuples**
  `(dest, qualified_name, target)`. Any other reader of that dict must unpack
  three values. Task 4's tests rely on the filter actually filtering.

- [ ] **Step 1: Find every reader of the tuple shape**

Run and read the output before editing:

```bash
grep -rn "_broadcast_handlers" engine/ tests/ tools/
```

Expected today: four sites, all in `engine/appc/events.py` (`:710` annotation,
`:721` append, `:751` removal, `:782` dispatch). If the grep shows a reader
outside that file, update it in this task too and say so in the commit.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_broadcast_handler_filter.py`:

```python
"""BC's 4th argument to AddBroadcastPythonFuncHandler is a destination FILTER.

10 SDK sites pass one. Ours discarded it, so a filtered handler fired for
every event of its type regardless of destination. Live consequence:
Bridge/PowerDisplay.py:340-341 registers HandleCloak filtered to the player,
and HandleCloak repaints the HUD cloak indicator from
App.ShipClass_Cast(pEvent.GetDestination()) -- so any NPC cloaking repainted
the player's indicator from the NPC's state. AddBroadcastPythonMethodHandler
already filtered correctly (events.py:791-793); this brings the func variant
to parity.
"""
import App
import pytest

from engine.appc.objects import ObjectClass

_ET = App.ET_CLOAK_BEGINNING
_HANDLER = __name__ + ".record"

_seen = []


def record(pObject, pEvent):
    _seen.append(pEvent.GetDestination())


@pytest.fixture(autouse=True)
def clean():
    _seen.clear()
    yield
    for entry in list(App.g_kEventManager._broadcast_handlers.get(_ET, [])):
        App.g_kEventManager._broadcast_handlers[_ET].remove(entry)
    _seen.clear()


def _post_to(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(_ET)
    evt.SetDestination(dest)
    App.g_kEventManager.AddEvent(evt)


def test_a_filtered_handler_ignores_other_destinations():
    watched, other = ObjectClass(), ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, ObjectClass(), _HANDLER, watched)

    _post_to(other)
    assert _seen == [], "a handler filtered to one object fired for another"

    _post_to(watched)
    assert _seen == [watched]


def test_an_unfiltered_handler_still_sees_everything():
    """The 3-argument form is the common case (the other ~200 SDK sites) and
    must keep matching every destination."""
    a, b = ObjectClass(), ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, ObjectClass(), _HANDLER)

    _post_to(a)
    _post_to(b)
    assert _seen == [a, b]


def test_removal_still_works_for_a_filtered_handler():
    """RemoveBroadcastHandler unpacks the tuple; a shape change breaks it."""
    watched = ObjectClass()
    dest = ObjectClass()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        _ET, dest, _HANDLER, watched)
    App.g_kEventManager.RemoveBroadcastHandler(_ET, dest, _HANDLER)

    _post_to(watched)
    assert _seen == []
```

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_broadcast_handler_filter.py -q`
Expected: `test_a_filtered_handler_ignores_other_destinations` FAILS
(`_seen == [other]` — the filter is ignored). The other two pass already.

- [ ] **Step 4: Store the filter at registration**

In `engine/appc/events.py`, change the annotation at `:710`:

```python
        self._broadcast_handlers: dict[
            int, list[tuple["TGEventHandlerObject", str, object]]] = {}
```

and the registration at `:717-721`:

```python
    def AddBroadcastPythonFuncHandler(
        self, event_type: int, dest: "TGEventHandlerObject", qualified_name: str, *extra
    ) -> None:
        """Register a module-qualified broadcast handler.

        `extra[0]`, when present, is BC's destination FILTER: dispatch is
        restricted to events whose destination IS that object (identity, not
        equality -- `_Stub.__eq__` is type-based, so == would match unrelated
        stubs). 10 SDK sites pass one, including
        Bridge/PowerDisplay.py:337-341, whose tractor and cloak HUD handlers
        re-read state off `pEvent.GetDestination()` and therefore repaint the
        PLAYER's indicator from whatever ship the event names. Dropping the
        filter made every NPC's cloak/tractor repaint the player's HUD.
        Mirrors AddBroadcastPythonMethodHandler, which has always filtered.
        """
        _validate_event_type(event_type, "AddBroadcastPythonFuncHandler(%s)" % qualified_name)
        self._broadcast_handlers.setdefault(event_type, []).append(
            (dest, qualified_name, extra[0] if extra else None))
```

- [ ] **Step 5: Unpack three in removal**

At `:751-756`, change the loop header only:

```python
        for i, (d, q, _t) in enumerate(func_handlers):
```

Leave the identity-compare comment and body as they are — the target is
deliberately not part of the removal key, matching BC's
`RemoveBroadcastHandler(eType, dest, name)` three-argument call sites.

- [ ] **Step 6: Filter at dispatch**

At `:782-788`, change the loop header and add the guard as the first statement
in the body:

```python
        for bd, name, target in list(
            self._broadcast_handlers.get(event.GetEventType(), [])
        ):
            if target is not None and event.GetDestination() is not target:
                continue
            fn = _resolve_handler(name)
```

- [ ] **Step 7: Run the test and the neighbours**

Run: `uv run pytest tests/unit/test_broadcast_handler_filter.py tests/unit/test_events.py -q`
Expected: all pass. Running a neighbouring file in the SAME process is
required — this module holds process-global handler state and single-file
runs cannot see leakage.

- [ ] **Step 8: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures`. This step is load-bearing: the change
narrows dispatch for 10 registrations, and any test that relied on a filtered
handler firing broadly will surface here.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/events.py tests/unit/test_broadcast_handler_filter.py
git commit -m "fix(events): honour BC's destination filter on broadcast func handlers"
```

---

### Task 2: Close `ET_SET_TARGET` in the negative

Gap #2 was filed as "needs a fidelity decision". The SDK settles it: every
registration of `ET_SET_TARGET` is one of exactly two lines
(`Bridge/ScienceMenuHandlers.py:134`, `Bridge/HelmMenuHandlers.py:281`), and
each sits directly beneath a registration of `ET_TARGET_WAS_CHANGED` **on the
same object, to the same handler function**. Seven other sites listen to
`ET_TARGET_WAS_CHANGED` alone; nothing anywhere listens to `ET_SET_TARGET`
alone. Its reachable behaviour is therefore a strict subset of an event we
already post, so adding the emitter buys no behaviour and risks running
`TargetChanged` twice per change.

The deliverable is a **regression test that pins the non-emission**, so a
future reader who finds the gap register and "helpfully" adds the post gets a
red test explaining why not.

**Files:**
- Create: `tests/unit/test_tier_bc_event_emitters.py` (first section; later
  tasks append to this file)
- Test: the same file

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/unit/test_tier_bc_event_emitters.py` with the shared
  `posted` fixture and `_of_type` helper that Tasks 3, 4 and 5 reuse. Their
  signatures:
  `posted` → `list` of every event posted during the test, in order;
  `_of_type(posted, event_type)` → `list` filtered to that type.

- [ ] **Step 1: Write the test**

Create `tests/unit/test_tier_bc_event_emitters.py`:

```python
"""Engine emitters for the Tier B/C gaps in docs/engine/event-emitter-gaps.md.

Companion to test_tier_a_event_emitters.py. Tier A was "the post is the only
missing piece"; these needed a piece of state or an accessor built first, or
-- for ET_SET_TARGET -- needed the SDK read that says do not emit at all.

Events are captured by spying on App.g_kEventManager.AddEvent rather than by
registering SDK handlers: the contract is "the engine posts exactly this
event, exactly this often", and the negative cases (no post per tick while
held, no post on a no-op, no post at all for ET_SET_TARGET) are the whole
risk. AddEvent dispatches synchronously, so there is no drain step.
"""
import App
import pytest


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


# ── ET_SET_TARGET — deliberately NOT emitted ─────────────────────────────────
# Gap #2. Every SDK registration of ET_SET_TARGET (ScienceMenuHandlers.py:134,
# HelmMenuHandlers.py:281) is paired with an ET_TARGET_WAS_CHANGED
# registration on the same object to the same handler function. Nothing
# listens to ET_SET_TARGET alone; seven sites listen to ET_TARGET_WAS_CHANGED
# alone. So emitting it would add no reachable behaviour and would run
# TargetChanged twice per change on the Science and Helm menus.

def test_set_target_posts_only_target_was_changed(posted):
    """If you are here because you added an ET_SET_TARGET emitter: read the
    comment above. The SDK says the two events funnel to one handler, so a
    second post is a double-dispatch, not new behaviour."""
    from engine.appc.ships import ShipClass

    ship, target = ShipClass(), ShipClass()
    target.SetName("Target")
    ship.SetTarget(target)

    assert len(_of_type(posted, App.ET_TARGET_WAS_CHANGED)) == 1
    assert _of_type(posted, App.ET_SET_TARGET) == []


def test_the_two_target_events_are_distinct_constants():
    """The assertion above is only meaningful while the constants differ; if
    they ever collapsed to the same int it would pass vacuously."""
    assert App.ET_SET_TARGET != App.ET_TARGET_WAS_CHANGED
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py -q`
Expected: PASS (both) — this task pins existing correct behaviour rather than
changing it. If `test_set_target_posts_only_target_was_changed` fails, an
`ET_SET_TARGET` emitter already exists and must be removed, and the gap
register is wrong; report that rather than adapting the test.

- [ ] **Step 3: Prove the test would catch the regression**

```bash
cp engine/appc/ships.py /tmp/ships_bak.py
```

Add a second post beside the `ET_TARGET_WAS_CHANGED` block in
`ShipClass.SetTarget` (around `engine/appc/ships.py:1599-1604`):

```python
            evt2 = App.TGEvent_Create()
            evt2.SetEventType(App.ET_SET_TARGET)
            evt2.SetSource(self); evt2.SetDestination(self)
            App.g_kEventManager.AddEvent(evt2)
```

```bash
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
uv run pytest tests/unit/test_tier_bc_event_emitters.py -q   # expect 1 FAIL
cp /tmp/ships_bak.py engine/appc/ships.py
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
diff engine/appc/ships.py /tmp/ships_bak.py && echo "restore byte-identical"
```

Expected: the test fails while mutated, and the diff reports no differences
after restore. Clearing `__pycache__` is required — a stale `.pyc` silently
runs the unmutated module and the mutation appears not to matter.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_tier_bc_event_emitters.py
git commit -m "test(events): pin that SetTarget does not also post ET_SET_TARGET"
```

---

### Task 3: `ET_CANT_FIRE` — the missing accessor, then the emitter

Gap #1. Both SDK handlers — `Bridge/TacticalMenuHandlers.py:1990`
(`PlayerCantFire`, sound cue, 2 s global cooldown) and
`Bridge/TacticalCharacterHandlers.py:198` (`PlayerCantFire`, Tactical officer
line, 10 s since-last-talk cooldown) — read **only** `pEvent.GetSource()` and
re-derive the reason themselves. Both cast the source to torpedo, phaser and
tractor systems, and **only the torpedo branch does anything**: `pPhasers` and
`pTractors` are computed and never used in either handler. So the emitter's
scope is torpedo fire attempts, and the reason needs no payload.

Both handlers branch on `pTorps.GetNumReady()`, which **does not exist on our
`TorpedoSystem`** — `GetNumReady` is defined on `TorpedoTube`
(`engine/appc/weapon_subsystems.py:2378`). On a `TorpedoSystem` it resolves
through `TGObject.__getattr__` to a truthy `_Stub`, so `GetNumReady() > 0`
does not answer the question the handler is asking. The accessor is a
prerequisite, not an optional extra.

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`TorpedoSystem`, near
  `GetNumAvailableTorpsToType` at `:1352` and `StartFiring` at `:1289`)
- Test: `tests/unit/test_tier_bc_event_emitters.py` (append a section)

**Interfaces:**
- Consumes: the `posted` fixture and `_of_type` helper from Task 2.
- Produces: `TorpedoSystem.GetNumReady() -> int` (count of child tubes whose
  own `GetNumReady()` is non-zero), and an `ET_CANT_FIRE` post from
  `TorpedoSystem.StartFiring` with `Source = self` and
  `Destination = self.GetParentShip()`.

- [ ] **Step 1: Confirm the accessor is genuinely absent before adding it**

```bash
grep -n "def GetNumReady" engine/appc/weapon_subsystems.py
grep -rn "GetNumReady" docs/stub_heatmap.md
```

Expected: exactly one definition, on `TorpedoTube` (`:2378`). If the heatmap
shows `GetNumReady` with live hits against a system-level receiver, note the
count in the commit message — it quantifies the bug this closes.

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_tier_bc_event_emitters.py`:

```python
# ── ET_CANT_FIRE ─────────────────────────────────────────────────────────────
# Gap #1. TacticalMenuHandlers.py:1990 and TacticalCharacterHandlers.py:198
# both read ONLY GetSource() and re-derive the reason from the system's own
# state; both compute pPhasers/pTractors and then use neither. So the emitter
# is torpedo-scoped and carries no reason payload.

def _torpedo_system(available=0, unlimited=False):
    """A TorpedoSystem whose current ammo type has `available` rounds."""
    from engine.appc.weapon_subsystems import TorpedoSystem

    sys_ = TorpedoSystem("Torpedo System")
    sys_.LoadAmmoType(0, available)
    ammo = sys_.GetCurrentAmmoType()
    ammo._unlimited = unlimited
    return sys_


def test_firing_with_no_ammo_posts_cant_fire(posted):
    sys_ = _torpedo_system(available=0)
    sys_.StartFiring(target=None)

    evts = _of_type(posted, App.ET_CANT_FIRE)
    assert len(evts) == 1
    assert evts[0].GetSource() is sys_, (
        "both handlers cast GetSource() to TorpedoSystem to decide the line")


def test_firing_with_ammo_does_not_post(posted):
    sys_ = _torpedo_system(available=4)
    sys_.StartFiring(target=None)

    assert _of_type(posted, App.ET_CANT_FIRE) == []


def test_unlimited_ammo_never_posts(posted):
    """An undeclared/unlimited ammo type never gates, so it can never be the
    'out of torpedoes' case the handlers speak to."""
    sys_ = _torpedo_system(available=0, unlimited=True)
    sys_.StartFiring(target=None)

    assert _of_type(posted, App.ET_CANT_FIRE) == []


def test_the_system_reports_its_own_ready_count():
    """Both handlers branch on pTorps.GetNumReady() where pTorps is the
    SYSTEM. GetNumReady was defined only on TorpedoTube, so on a system it
    resolved through TGObject.__getattr__ to a truthy _Stub and the handlers
    could not distinguish 'out of ammo' from 'not reloaded yet'."""
    from engine.appc.weapon_subsystems import TorpedoSystem

    sys_ = TorpedoSystem("Torpedo System")
    assert isinstance(sys_.GetNumReady(), int)
    assert sys_.GetNumReady() == 0, "no tubes -> nothing ready"
```

- [ ] **Step 3: Run and watch them fail**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py -q`
Expected: `test_firing_with_no_ammo_posts_cant_fire` FAILS (no event) and
`test_the_system_reports_its_own_ready_count` FAILS (`_Stub` is not an `int`).
The two negative tests pass already — that is correct; they guard the
over-broad emitter, not the missing one.

- [ ] **Step 4: Add the system-level ready count**

In `engine/appc/weapon_subsystems.py`, inside `TorpedoSystem`, directly above
`GetNumAvailableTorpsToType` (`:1352`):

```python
    def GetNumReady(self) -> int:
        """Number of child tubes currently loaded and ready to launch.

        BC's own handlers call this on the SYSTEM
        (Bridge/TacticalMenuHandlers.py:2007,
        Bridge/TacticalCharacterHandlers.py:223) to separate "out of
        torpedoes" from "not reloaded yet". Ours defined GetNumReady only on
        TorpedoTube (:2378), so a system-level call resolved through
        TGObject.__getattr__ to a truthy _Stub and neither handler could take
        the branch it wanted.
        """
        ready = 0
        for i in range(self.GetNumWeapons()):
            tube = self.GetWeapon(i)
            if tube is not None and tube.GetNumReady():
                ready += 1
        return ready
```

- [ ] **Step 5: Post from the ammo gate**

Replace `TorpedoSystem.StartFiring`'s gate (`:1298-1302`) so the early return
announces itself. Keep the existing docstring; add the post and the note:

```python
        ammo = self.GetCurrentAmmoType()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        if finite and ammo.GetAvailable() <= 0:
            self._post_cant_fire()
            return
        super().StartFiring(target, offset)

    def _post_cant_fire(self) -> None:
        """Announce a torpedo fire attempt that cannot produce a launch.

        Gap #1 in docs/engine/event-emitter-gaps.md. The event carries no
        reason: both SDK handlers (Bridge/TacticalMenuHandlers.py:1990,
        Bridge/TacticalCharacterHandlers.py:198) re-derive it from this
        system's own state via GetNumReady() / GetNumAvailableTorpsToType(),
        and both self-guard -- they fall through silently when tubes are
        ready, and they carry their own cooldowns (2 s global; 10 s since
        Tactical last spoke). So an emitter here cannot spam a line even if
        the player holds the trigger.

        Scoped to torpedoes on purpose. Both handlers cast the source to
        phaser and tractor systems as well and then use neither, so posting
        from the phaser/tractor gates would be observationally inert today
        while committing us to a reading of "can't fire" that no SDK code
        exercises.
        """
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_CANT_FIRE)
        evt.SetSource(self)
        evt.SetDestination(self.GetParentShip())
        App.g_kEventManager.AddEvent(evt)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py tests/unit/test_weapon_subsystems.py -q`
Expected: all pass. Run the weapons neighbour in the same process — this file
carries module-level firing state.

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures`.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/weapon_subsystems.py tests/unit/test_tier_bc_event_emitters.py
git commit -m "feat(events): post ET_CANT_FIRE from the torpedo ammo gate"
```

---

### Task 4: Tractor beam start/stop edge-detect

Gaps #8 and #9. `TractorBeamSystem._engage_beam` runs every tick while the
beam is held (`update_weapons`, driven from `engine/host_loop.py:821,837`), so
posting from it directly would emit once per frame. BC's handlers are written
for a transition: `Bridge/PowerDisplay.py:1010` `HandleTractor` casts
`pEvent.GetDestination()` to `ShipClass` and repaints an On/Off indicator, and
`Conditions/ConditionFiringTractorBeam.py:26-27` sets a boolean condition
status. Both re-read the live state themselves — like `ET_SET_WARP_SEQUENCE`,
these are "something changed, go re-check" pings.

`IsFiring()` already computes the instantaneous state each call
(`engine/appc/weapon_subsystems.py:1815-1819`), but nothing caches last tick's
value to diff against. That cache is the whole of the new state.

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`TractorBeamSystem.__init__`,
  and one new method called from `StartFiring`, `update_weapons`, `StopFiring`)
- Test: `tests/unit/test_tier_bc_event_emitters.py` (append a section)

**Interfaces:**
- Consumes: Task 1's working destination filter (`PowerDisplay` registers
  `HandleTractor` filtered to the player); the `posted` fixture from Task 2.
- Produces: `TractorBeamSystem._sync_firing_event()` — call it after any
  operation that could change `IsFiring()`; it posts at most one event per
  call and only on a transition.

- [ ] **Step 1: Note the accessors the handlers need (already verified present)**

Both SDK handlers walk the system's children, and both walks resolve today —
this was checked while writing the plan, so it is context, not a task:

| SDK call | Ours |
|---|---|
| `pTractors.GetNumChildSubsystems()` | `subsystems.py:967` |
| `pTractors.GetWeapon(i)` (PowerDisplay) | `weapon_subsystems.py:1066`, aliases `GetChildSubsystem` |
| `pTractorSystem.GetChildSubsystem(i)` (the Condition) | `subsystems.py:970`, honours an int index |
| `App.TractorBeamProjector_Cast(...)` | `App.py:580` |

No work in this step. It exists so the implementer does not re-derive it, and
so that a later failure of `ConditionFiringTractorBeam` is not misdiagnosed as
a missing emitter when the emitter is the part that landed.

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_tier_bc_event_emitters.py`:

```python
# ── ET_TRACTOR_BEAM_STARTED_FIRING / _STOPPED_FIRING ────────────────────────
# Gaps #8/#9. PowerDisplay.py:1010 casts GetDestination() to ShipClass and
# re-reads the system state; ConditionFiringTractorBeam.py:26-27 registers
# broadcast METHOD handlers filtered to the watched ship. Both need the SHIP
# as destination, and both need transitions, not per-tick pings.

class _FakeEmitter:
    """Minimal tractor projector: the system only asks IsFiring/CanFire/Fire."""

    def __init__(self):
        self._firing = False

    def IsFiring(self):
        return 1 if self._firing else 0

    def CanFire(self):
        return True

    def Fire(self, target=None, offset=None):
        self._firing = True

    def StopFiring(self, *a):
        self._firing = False


def _tractor_with(emitter):
    """A TractorBeamSystem on a ship, holding one emitter, arc/range checks
    stubbed out so the test exercises the EDGE-DETECT, not the geometry.

    AddChildSubsystem / SetParentShip, NOT AddWeapon / _parent_ship=:
    GetWeapon(i) and GetNumWeapons() are thin aliases over the child-subsystem
    walk (weapon_subsystems.py:1065-1066), and there is no AddWeapon at all --
    calling one would resolve through TGObject.__getattr__ to a truthy _Stub,
    attach nothing, and leave every assertion below passing against an empty
    system.
    """
    from engine.appc.ships import ShipClass
    from engine.appc.weapon_subsystems import TractorBeamSystem

    ship = ShipClass()
    ship.SetName("Player")
    sys_ = TractorBeamSystem("Tractor Beam System")
    sys_.SetParentShip(ship)
    sys_.AddChildSubsystem(emitter)
    assert sys_.GetNumWeapons() == 1, "the emitter must really be attached"
    return ship, sys_


def test_engaging_posts_started_once_with_the_ship_as_destination(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)

    started = _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)
    assert len(started) == 1
    assert started[0].GetDestination() is ship, (
        "PowerDisplay.HandleTractor casts GetDestination() to ShipClass")


def test_holding_the_beam_does_not_repost_every_tick(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    for _ in range(10):
        sys_.update_weapons(1.0 / 60.0)

    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1, (
        "the beam is re-dispatched every tick while held; the event is not")


def test_releasing_posts_stopped_once(posted, monkeypatch):
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: True)
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    posted.clear()
    sys_.StopFiring()

    stopped = _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)
    assert len(stopped) == 1
    assert stopped[0].GetDestination() is ship
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []


def test_stopping_a_beam_that_never_gripped_posts_nothing(posted, monkeypatch):
    """The HUD toggle can be released without the beam ever having gripped
    (out of range the whole time). No transition, no event."""
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    monkeypatch.setattr(TractorBeamSystem, "_can_engage", lambda *a: False)

    sys_.StartFiring(target=ship)
    sys_.StopFiring()

    assert _of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING) == []
    assert _of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING) == []


def test_losing_the_grip_mid_hold_posts_stopped_then_started_on_reacquire(
        posted, monkeypatch):
    """A tractor stays ENGAGED while the beam drops in and out (target out of
    range, shields up, emitter out of arc). Each crossing is a transition
    PowerDisplay must repaint for."""
    from engine.appc.weapon_subsystems import TractorBeamSystem

    em = _FakeEmitter()
    ship, sys_ = _tractor_with(em)
    engageable = {"v": True}
    monkeypatch.setattr(TractorBeamSystem, "_can_engage",
                        lambda *a: engageable["v"])
    monkeypatch.setattr(TractorBeamSystem, "_engage_beam",
                        lambda self, *a: (em.Fire(), True)[1])

    sys_.StartFiring(target=ship)
    posted.clear()

    engageable["v"] = False               # drifts out of range
    sys_.update_weapons(1.0 / 60.0)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STOPPED_FIRING)) == 1

    engageable["v"] = True                # back in range
    sys_.update_weapons(1.0 / 60.0)
    assert len(_of_type(posted, App.ET_TRACTOR_BEAM_STARTED_FIRING)) == 1
```

- [ ] **Step 3: Run and watch them fail**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py -q`
Expected: the three positive tests FAIL (no events posted); the two negative
tests (`..._never_gripped_posts_nothing`, and the per-tick assertion once
`started` is empty) may pass vacuously — that is expected at RED and is why
the positive assertions come first.

If `AddWeapon` or `_parent_ship` is not the right constructor surface for
`TractorBeamSystem`, fix the helper to match the real class rather than
adding surface to the production class for the test's benefit.

- [ ] **Step 4: Add the cached state**

In `TractorBeamSystem.__init__` (`:1753-1756`), after `self._engage_state = None`:

```python
        # Last observed IsFiring() value, for the ET_TRACTOR_BEAM_STARTED_/
        # STOPPED_FIRING edge-detect. Not derived from _fire_held: the beam
        # drops and re-acquires (range, shields, arc) while the ENGAGE intent
        # is continuously held, and each crossing is a transition BC's
        # PowerDisplay repaints for.
        self._was_firing = False
```

- [ ] **Step 5: Add the transition post**

Add to `TractorBeamSystem`, directly after `IsFiring` (`:1819`):

```python
    def _sync_firing_event(self) -> None:
        """Post ET_TRACTOR_BEAM_STARTED_/STOPPED_FIRING on a beam transition.

        Gaps #8/#9 in docs/engine/event-emitter-gaps.md. Call after any
        operation that could change IsFiring(); it is a no-op unless the
        state actually crossed, so it is safe on the per-tick path.

        Destination is the parent SHIP, not the system:
        Bridge/PowerDisplay.py:1013 casts GetDestination() to ShipClass and
        then walks the ship's own tractor system, and
        Conditions/ConditionFiringTractorBeam.py:26-27 registers broadcast
        METHOD handlers filtered to the watched ship -- that filter compares
        against the event's destination. Neither event carries a payload:
        both handlers re-read the live state themselves.
        """
        now = bool(self.IsFiring())
        if now == self._was_firing:
            return
        self._was_firing = now
        ship = self.GetParentShip()
        if ship is None:
            return
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_TRACTOR_BEAM_STARTED_FIRING if now
                         else App.ET_TRACTOR_BEAM_STOPPED_FIRING)
        evt.SetSource(self)
        evt.SetDestination(ship)
        App.g_kEventManager.AddEvent(evt)
```

- [ ] **Step 6: Call it from the three paths that can cross**

In `StartFiring` (`:1796-1814`), replace the final two lines:

```python
        ship = self.GetParentShip()
        if self._can_engage(ship, target):
            self._engage_beam(target, offset, ship)
        self._sync_firing_event()
```

In `update_weapons` (`:1826-1869`), the method has four `return` points after
emitters may have been stopped or started. Call the sync immediately before
each of the returns that follow a possible state change — the `_is_offline`
and dead-target branches already call `self.StopFiring()` (covered by the next
edit), so the ones needing it are the `if not engageable: return False` exit
and both tail returns:

```python
        if not engageable:
            self._sync_firing_event()
            return False
        # Re-dispatch one eligible in-arc emitter if none is currently firing.
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is not None and em.IsFiring():
                self._sync_firing_event()
                return False
        fired = self._engage_beam(target, self._held_offset, ship)
        self._sync_firing_event()
        return fired
```

In `StopFiring` (`:1906-1908`):

```python
    def StopFiring(self, *args) -> None:
        self._engage_state = None
        super().StopFiring(*args)
        self._sync_firing_event()
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py tests/unit/test_tractor_beams.py -q`
Expected: all pass. If `tests/unit/test_tractor_beams.py` does not exist, run
`uv run pytest tests/unit -k tractor -q` instead and name what you ran.

- [ ] **Step 8: Prove the edge-detect is load-bearing**

```bash
cp engine/appc/weapon_subsystems.py /tmp/ws_bak.py
```

Delete the `if now == self._was_firing: return` guard, then:

```bash
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
uv run pytest tests/unit/test_tier_bc_event_emitters.py -q   # expect FAIL
cp /tmp/ws_bak.py engine/appc/weapon_subsystems.py
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
diff engine/appc/weapon_subsystems.py /tmp/ws_bak.py && echo "restore byte-identical"
```

Expected: `test_holding_the_beam_does_not_repost_every_tick` fails while
mutated, and the restore diff is empty.

- [ ] **Step 9: Run the gate and commit**

Run: `scripts/check_tests.sh` — expected `OK — no new failures`.

```bash
git add engine/appc/weapon_subsystems.py tests/unit/test_tier_bc_event_emitters.py
git commit -m "feat(events): post tractor beam start/stop on beam transitions"
```

---

### Task 5: Target-list membership diff

Gaps #4 and #5. `STTargetMenu.set_contacts`
(`engine/appc/target_menu.py:147-203`) is pushed every frame from
`host_loop._pump_contacts` (`:6231`) and today only ever *adds* rows: a contact
that fails detection is filtered out of `_rows()` rather than evicted from
`_row_cache`. There is no crossing that means "object entered the target list",
so the diff is the new state.

Membership is the **targetable** subset, because that is what the list shows
(`_rows()` filters on `Contact.targetable`). The diff must not change row
lifetime — evicting `_row_cache` entries is a separate behaviour change with
its own blast radius, and this task deliberately leaves it alone.

Destination is the object that joined or left: `ScienceMenuHandlers.ShipIdentified`
(`:244`) and `ExitedSet` (`:205`) both read `pEvent.GetDestination()`, and
`Maelstrom/Episode3/E3M2/E3M2.py:906` registers `ET_TARGET_LIST_OBJECT_ADDED`
with `AddPythonFuncHandlerForInstance` **on the Berkeley itself** — an instance
handler, which only fires if the ship is the destination.

**Files:**
- Modify: `engine/appc/target_menu.py` (`STTargetMenu.__init__`, `set_contacts`)
- Test: `tests/unit/test_tier_bc_event_emitters.py` (append a section)

**Interfaces:**
- Consumes: the `posted` fixture from Task 2.
- Produces: `STTargetMenu._listed` — the frozenset of ships that were
  targetable on the previous push. Nothing outside `set_contacts` should read it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_tier_bc_event_emitters.py`:

```python
# ── ET_TARGET_LIST_OBJECT_ADDED / _REMOVED ──────────────────────────────────
# Gaps #4/#5. ScienceMenuHandlers.ShipIdentified (:244) and ExitedSet (:205)
# both read pEvent.GetDestination(); E3M2.py:906 registers ADDED as an
# INSTANCE handler on the ship itself, so the ship must be the destination or
# that mission beat never fires. Membership is the targetable subset -- that
# is what _rows() lists.

def _contact(ship, targetable=True):
    from engine.appc.perception import Contact

    return Contact(ship=ship, surface_gu=1.0, perceivable=True,
                   targetable=targetable, subsystems_targetable=True)


def _menu_and_ships(n=2):
    from engine.appc.ships import ShipClass
    from engine.appc.target_menu import STTargetMenu

    menu = STTargetMenu("Targets")
    ships = []
    for i in range(n):
        s = ShipClass()
        s.SetName("Ship%d" % i)
        ships.append(s)
    return menu, ships


def test_a_new_contact_posts_added_with_the_ship_as_destination(posted):
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])

    added = _of_type(posted, App.ET_TARGET_LIST_OBJECT_ADDED)
    assert len(added) == 1
    assert added[0].GetDestination() is a, (
        "E3M2 registers ADDED as an instance handler ON the ship")


def test_a_contact_that_persists_does_not_repost(posted):
    """set_contacts runs every frame. Only crossings are events."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    posted.clear()

    for _ in range(5):
        menu.set_contacts([_contact(a)])

    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_ADDED) == []
    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED) == []


def test_a_contact_that_drops_posts_removed(posted):
    menu, (a, b) = _menu_and_ships()
    menu.set_contacts([_contact(a), _contact(b)])
    posted.clear()

    menu.set_contacts([_contact(a)])

    removed = _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)
    assert len(removed) == 1
    assert removed[0].GetDestination() is b


def test_losing_targetability_counts_as_removal(posted):
    """A contact that is still perceivable but no longer targetable is not on
    the list -- _rows() filters on targetable -- so it left it."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    posted.clear()

    menu.set_contacts([_contact(a, targetable=False)])

    removed = _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)
    assert len(removed) == 1
    assert removed[0].GetDestination() is a


def test_an_empty_push_removes_everything(posted):
    """Mid-warp the player sits alone in _WarpTransit and perceived_by returns
    (); every contact left the list."""
    menu, (a, b) = _menu_and_ships()
    menu.set_contacts([_contact(a), _contact(b)])
    posted.clear()

    menu.set_contacts([])

    assert len(_of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED)) == 2


def test_the_row_cache_is_not_evicted_on_removal(posted):
    """Deliberate scope limit: this task posts events, it does not change row
    lifetime. Rows are reused for the life of the menu (see set_contacts'
    docstring on state normalisation); evicting them is a separate change."""
    menu, (a, _b) = _menu_and_ships()
    menu.set_contacts([_contact(a)])
    menu.set_contacts([])

    assert a in menu._row_cache
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py -q`
Expected: the four positive tests FAIL (no events). `test_a_contact_that_persists_does_not_repost`
and `test_the_row_cache_is_not_evicted_on_removal` pass already.

- [ ] **Step 3: Add the previous-membership field**

In `STTargetMenu.__init__` (`engine/appc/target_menu.py:129-132`), beside
`self._contacts`:

```python
        # Ships that were TARGETABLE on the previous push -- the membership
        # this list actually shows (_rows() filters on Contact.targetable).
        # The diff against it is what makes ET_TARGET_LIST_OBJECT_ADDED /
        # _REMOVED possible: set_contacts is pushed every frame, so without a
        # previous set there is no crossing to post on.
        self._listed: frozenset = frozenset()
```

- [ ] **Step 4: Diff and post in `set_contacts`**

Replace the body of `set_contacts` after the `self._contacts = ...` assignment
(`engine/appc/target_menu.py:194-203`). Keep the existing docstring untouched:

```python
        for c in self._contacts:
            if c.ship not in self._row_cache:
                self.RebuildShipMenu(c.ship)
            row = self._row_cache.get(c.ship)
            if row is None:
                continue
            row.SetVisible()
        self._post_membership_changes()

    def _post_membership_changes(self) -> None:
        """Post ET_TARGET_LIST_OBJECT_ADDED / _REMOVED for this push's
        crossings, then remember the new membership.

        Gaps #4/#5 in docs/engine/event-emitter-gaps.md. Membership is the
        TARGETABLE subset because that is what this list shows -- a contact
        that is perceivable but not targetable has no row (`_rows`), so it is
        not "on the target list" in the sense the SDK handlers mean.

        Destination is the object itself:
        Bridge/ScienceMenuHandlers.py:244 (ShipIdentified) and :205
        (ExitedSet) both read pEvent.GetDestination(), and
        Maelstrom/Episode3/E3M2/E3M2.py:906 registers ADDED as an INSTANCE
        handler on the Berkeley -- instance dispatch only reaches the
        destination, so a broadcast with some other destination would leave
        that mission beat dead.

        Row LIFETIME is deliberately unchanged: `_row_cache` still keeps one
        row per ship for the life of the menu. This method reports membership;
        it does not manage rows.
        """
        listed = frozenset(c.ship for c in self._contacts if c.targetable)
        if listed == self._listed:
            return
        import App
        for ship in listed - self._listed:
            self._post_membership(App.ET_TARGET_LIST_OBJECT_ADDED, ship)
        for ship in self._listed - listed:
            self._post_membership(App.ET_TARGET_LIST_OBJECT_REMOVED, ship)
        self._listed = listed

    def _post_membership(self, event_type, ship) -> None:
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(event_type)
        evt.SetSource(self)
        evt.SetDestination(ship)
        App.g_kEventManager.AddEvent(evt)
```

- [ ] **Step 5: Pin that a mission swap starts from empty membership**

`_listed` must not survive a mission swap, or the first push in the new system
posts REMOVED for every ship of the old one.

**No reset hook is needed — the existing lifecycle already covers it**, and
this step is to pin that rather than to add code. `host_loop.py:3586` calls
`App._reset_target_menu_singleton()` on swap (`target_menu.py:611-614`, sets
the singleton to `None`), and the ensure-helper at `host_loop.py:6198-6199`
then constructs a **fresh** `STTargetMenu` via `STTargetMenu_CreateW`. A new
instance starts with `_listed = frozenset()` from `__init__`.

That is a lifecycle other work could quietly change, so pin it. Append to the
target-list section of `tests/unit/test_tier_bc_event_emitters.py`:

```python
def test_a_swap_starts_from_empty_membership(posted):
    """No explicit reset exists because none is needed: host_loop.py:3586
    drops the singleton on swap and host_loop.py:6198 builds a fresh menu, so
    _listed starts empty by construction. If the menu ever becomes reused
    across swaps, this test goes red and _listed needs clearing wherever
    _row_cache is."""
    import App
    from engine.appc.ships import ShipClass

    old = ShipClass()
    old.SetName("OldSystemShip")
    menu = App.STTargetMenu_CreateW("Targets")
    menu.set_contacts([_contact(old)])
    posted.clear()

    App._reset_target_menu_singleton()
    fresh = App.STTargetMenu_CreateW("Targets")
    fresh.set_contacts([])

    assert _of_type(posted, App.ET_TARGET_LIST_OBJECT_REMOVED) == [], (
        "the new system's first push must not report the old system's ships "
        "as having left")
```

Confirm `_reset_target_menu_singleton` and `STTargetMenu_CreateW` are both
exported from `App` before relying on them here; if either is module-private,
import it from `engine.appc.target_menu` instead and say so in the commit.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_tier_bc_event_emitters.py tests/unit/test_target_menu_visibility_derived.py tests/unit/test_readers_share_one_distance.py -q`
Expected: all pass. Those two neighbours exercise `set_contacts` directly and
are the ones most likely to notice an unintended change.

- [ ] **Step 7: Prove the diff is load-bearing**

```bash
cp engine/appc/target_menu.py /tmp/tm_bak.py
```

Delete the `if listed == self._listed: return` guard **and** change
`self._listed = listed` to `self._listed = frozenset()`, then:

```bash
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
uv run pytest tests/unit/test_tier_bc_event_emitters.py -q   # expect FAIL
cp /tmp/tm_bak.py engine/appc/target_menu.py
find . -name __pycache__ -path "./engine/*" -exec rm -rf {} + 2>/dev/null
diff engine/appc/target_menu.py /tmp/tm_bak.py && echo "restore byte-identical"
```

Expected: `test_a_contact_that_persists_does_not_repost` fails while mutated.

- [ ] **Step 8: Run the gate and commit**

Run: `scripts/check_tests.sh` — expected `OK — no new failures`.

```bash
git add engine/appc/target_menu.py tests/unit/test_tier_bc_event_emitters.py
git commit -m "feat(events): post target-list added/removed from a membership diff"
```

---

### Task 6: Update the gap register and the project context

**Files:**
- Modify: `docs/engine/event-emitter-gaps.md`
- Modify: `CLAUDE.md` (the "Measured constant surface" row's closing warning)

- [ ] **Step 1: Rewrite the status header**

Replace the `> **Status 2026-08-31 — Tier A closed (3 of 12).**` block with a
block recording **9 of 12 closed**, listing the six added by this plan
(`ET_CANT_FIRE`, `ET_SET_TARGET` as a documented non-emission,
`ET_TARGET_LIST_OBJECT_ADDED`, `ET_TARGET_LIST_OBJECT_REMOVED`,
`ET_TRACTOR_BEAM_STARTED_FIRING`, `ET_TRACTOR_BEAM_STOPPED_FIRING`) and
naming the three that remain with their reasons: #6/#7 blocked on wiring
torpedoes into `SetClass` (its own plan), #10 open because BC's engine owns
both the persistent-target storage and the restore trigger.

Update the title line — it currently reads "9 of the original 12 still have no
engine poster".

- [ ] **Step 2: Mark each closed entry**

For sections 1, 2, 4, 5, 8 and 9, append a `**✅ Landed**` (or, for #2,
`**✅ Closed — deliberately NOT emitted**`) paragraph in the style the Tier A
entries already use: what landed, where, and what the non-obvious decision
was. For #2 the decision is the registration-pairing evidence. For #4/#5 it is
that membership is the targetable subset and row lifetime is unchanged. For
#8/#9 it is that the destination is the ship and the edge-detect is on
`IsFiring()`, not `_fire_held`. For #1 it is that the missing
`TorpedoSystem.GetNumReady` was a prerequisite and that phaser/tractor gates
are deliberately not posted.

- [ ] **Step 3: Update the summary table**

Change the six rows' "Engine emitter" cells to `✅ **DONE** — <where>`,
matching the existing Tier A row style.

- [ ] **Step 4: Correct the CLAUDE.md warning**

`CLAUDE.md`'s "Measured constant surface" row ends with:

> ⚠️ **Fixing a constant's VALUE does not add its emitter or its call site** —
> twelve event types (`ET_SET_TARGET`, `ET_SET_WARP_SEQUENCE`, etc.) now have
> real ints but nothing in the engine posts them yet; their SDK handlers are
> still dead.

Update the count to three, drop `ET_SET_TARGET` from the example list (it is
now a documented non-emission, not a pending gap), and keep the pointer to
`docs/engine/event-emitter-gaps.md`.

- [ ] **Step 5: Run the docs consistency test**

Run: `uv run pytest tests/docs/ -q`
Expected: pass. `tests/docs/test_doc_consistency.py` machine-checks counts
against summary lines; if it fails, the number in a prose summary disagrees
with the table and must be corrected rather than the test relaxed.

- [ ] **Step 6: Run the gate and commit**

Run: `scripts/check_tests.sh` — expected `OK — no new failures`.

```bash
git add docs/engine/event-emitter-gaps.md CLAUDE.md
git commit -m "docs: record six emitter gaps closed, three remaining"
```

---

## Live verification (user-actionable — an agent must not drive the game)

None of these six are fully visible to a unit test; four of them change
on-screen or in-mission behaviour. Run under `--developer` after the branch is
green:

1. **Tractor HUD indicator.** Tractor a target and watch the Engineering power
   display's Tractor readout switch On, then Off when you release or the
   target drifts out of range. Before this branch it never changed.
2. **Cloak indicator no longer cross-talks** (the Task 1 side effect). With an
   NPC cloaking nearby, the player's cloak readout must not change. This is
   the pre-existing bug the filter fix repairs, and it is the one regression
   risk in Task 1 worth confirming directly.
3. **Science → Scan Object list.** Fly toward and away from a ship and watch
   rows appear and disappear as it enters and leaves sensor range. Before this
   branch the scan menu was populated only by other paths.
4. **E3M2 `DetectBerkeley`.** Load E3M2 and confirm the Berkeley beat fires
   when it first appears on the target list. This is the instance-handler path
   that proves the destination is right.
5. **Out of torpedoes.** Empty a torpedo type and pull the trigger: expect the
   `UITorpsNoAmmo` cue and Tactical's "out of photons/quantums" line, subject
   to their 2 s / 10 s cooldowns.

Watch for a **mission-load burst** in (3): the first push after a load posts
ADDED for every ship already in sensor range. That is the correct reading of
the transition — they did just enter the list — but it is the behaviour most
likely to look wrong, so check that no handler misbehaves on a burst.
