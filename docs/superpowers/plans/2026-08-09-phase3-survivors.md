# Phase 3 — Build the Surviving Gaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three genuine gaps the 2026-08-09 audit left standing — `PhaserBank.CanHit`, set-to-set warp exit velocity, and the DynamicMusic engine surface.

**Architecture:** Three independent groups, each reverting cleanly on its own. A and B add small pieces of missing engine surface that currently collapse to a truthy `_Stub` or to nothing. C supplies `g_kMusicManager` plus two event types so the SDK's own music state machine — which already exists in `DynamicMusic.py` — can drive our audio backend.

**Tech Stack:** Python 3 / pytest, `engine/appc/`, `engine/audio/`, `scripts/check_tests.sh` gate.

## Global Constraints

- **Source:** `docs/superpowers/plans/2026-08-09-triage-report.md`. Read it before Task 1.
- **Branch:** `fix/open-question-reconciliation` (continues; 11 commits in).
- **Shared checkout:** stage with explicit pathspecs only. NEVER `git add -A`, `git add .`, `git stash`, `git clean`, `git reset --hard`, `git checkout -- <path>`, `git restore`. `.claude/` belongs to another session — never stage it.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest AND ctest against `tests/known_failures.txt`). NOT `run_tests.sh`. Read the ledger; never trust a remembered failure count.
- **SDK booleans must be real `int`s, never `bool`, never a `_Stub`.** `TGObject.__getattr__` vends a truthy `_Stub` for any undefined method, so a missing method silently reads as "yes". Return `1`/`0`.
- **Rotation convention:** column-vector, right-handed. World-forward is `GetWorldRotation().GetCol(1)` — never `GetRow(1)`. Prefer the helper `ObjectClass.GetWorldForwardTG()`.
- **Test doubles must mirror the real surface.** Do not give a fake a method the real class lacks — phantom-method fakes have hidden two real bugs here (see `GetSceneNodeId`, `docs/stub_heatmap.md` rank 10).
- **Do not unstub a whole SDK module** to reach one function. Reimplement the behaviour at the equivalent engine hook.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `engine/appc/weapon_subsystems.py` | `PhaserBank.CanHit` | 1 |
| `tests/unit/test_phaser_can_hit.py` | arc + range coverage for `CanHit` | 1 |
| `engine/appc/warp.py:331-346` | warp arrival velocity | 2 |
| `tests/unit/test_warp_exit_velocity.py` | arrival velocity coverage | 2 |
| `engine/appc/music_manager.py` | `MusicManager` — `LoadMusic`/`StartMusic`/`StopMusic`/`UnloadMusic`/`PlayFanfare` | 3 |
| `App.py` | `g_kMusicManager`, `ET_MUSIC_DONE`, `ET_MUSIC_CONDITION_CHANGED` | 3 |
| `tests/unit/test_music_manager.py` | manager surface + queue-advance event | 3, 5 |
| `engine/audio/music.py` | music playback + volume ramp | 4 |
| `tests/audio/test_music_playback.py` | playback/ramp coverage | 4 |

---

## Group A — `PhaserBank.CanHit`

### Task 1: Implement `PhaserBank.CanHit`

`ConditionInPhaserFiringArc.py:175` calls `pBank.CanHit(vTargetLocation)` in live AI
(`AI/Compound/FedAttack.py`, `AI/Setup.py`). We do not define it, so it resolves to a
truthy `_Stub` and the arc test passes unconditionally.

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (add method to `class PhaserBank`, line ~1887)
- Test: `tests/unit/test_phaser_can_hit.py` (create)

**Interfaces:**
- Consumes: `_emitter_in_arc(emitter, ship, aim_world)` (`weapon_subsystems.py:164`) — takes a **unit direction**, not a point; `subsystem_world_position(sub, ship=None)` (`subsystems.py:25`); `ShipSubsystem.GetParentShip()` (`subsystems.py:525`); `EnergyWeaponProperty.GetMaxDamageDistance()` (`properties.py:506`).
- Produces: `PhaserBank.CanHit(target_world_point) -> int` (1 or 0).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_phaser_can_hit.py`:

```python
"""PhaserBank.CanHit — the arc+range test ConditionInPhaserFiringArc relies on.

Without this method the SDK call resolves to a truthy _Stub and every target
reads as 'in arc', so FedAttack fires with no arc discipline at all.
"""
import math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.weapon_subsystems import PhaserBank


class _StubShip:
    """Mirrors the real ShipClass surface CanHit touches — nothing more."""
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self._loc = TGPoint3(x, y, z)
        self._rot = TGMatrix3()  # identity
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self


def _forward_bank(max_range=100.0):
    """Forward-facing bank, +-50 deg width, -3..+60 deg height, at ship origin."""
    bank = PhaserBank("ForwardPhaser1")
    prop = PhaserProperty("ForwardPhaser1")
    prop.SetPosition(0.0, 0.0, 0.0)
    # model-forward +Y, up +Z
    prop.SetOrientation(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetArcWidthAngles(-0.872665, 0.872665)
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    prop.SetMaxDamageDistance(max_range)
    bank.SetProperty(prop)
    bank._parent_ship = _StubShip()
    return bank


def test_target_dead_ahead_and_in_range_can_be_hit():
    bank = _forward_bank()
    assert bank.CanHit(TGPoint3(0.0, 50.0, 0.0)) == 1


def test_target_behind_cannot_be_hit():
    bank = _forward_bank()
    assert bank.CanHit(TGPoint3(0.0, -50.0, 0.0)) == 0


def test_target_beyond_max_range_cannot_be_hit():
    bank = _forward_bank(max_range=10.0)
    # Dead ahead, so in arc — rejected on range alone.
    assert bank.CanHit(TGPoint3(0.0, 50.0, 0.0)) == 0


def test_target_outside_width_arc_cannot_be_hit():
    bank = _forward_bank()
    # 80 deg off the nose in yaw: outside the +-50 deg width arc.
    ang = math.radians(80.0)
    assert bank.CanHit(TGPoint3(50.0 * math.sin(ang), 50.0 * math.cos(ang), 0.0)) == 0


def test_returns_a_real_int_not_a_truthy_stub():
    """A _Stub is truthy AND int()s to 0 — both silently wrong. Demand a real int."""
    bank = _forward_bank()
    result = bank.CanHit(TGPoint3(0.0, 50.0, 0.0))
    assert type(result) is int


def test_zero_max_range_means_unbounded_not_unreachable():
    """MaxDamageDistance defaults to 0.0 on a bank with no authored range.
    Treat 0 as 'no limit' — treating it as 'range 0' would disable every bank
    whose hardpoint omits the field."""
    bank = _forward_bank(max_range=0.0)
    assert bank.CanHit(TGPoint3(0.0, 5000.0, 0.0)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_phaser_can_hit.py -v`

Expected: FAIL. Note the *shape* of the failure — `CanHit` is undefined, so `__getattr__`
hands back a truthy `_Stub` and the assertions compare a `_Stub` against `1`. If instead
you see `AttributeError`, the class raises for `_private`-style names; either way it is red.

- [ ] **Step 3: Implement `CanHit` on `PhaserBank`**

Add to `class PhaserBank` in `engine/appc/weapon_subsystems.py`:

```python
    def CanHit(self, target_world_point) -> int:
        """1 if `target_world_point` lies inside this bank's firing arc and
        within its maximum range, else 0. SDK ShipClass surface — the sole
        Python caller is Conditions/ConditionInPhaserFiringArc.py:175, reached
        from AI/Compound/FedAttack.py and AI/Setup.py.

        Must return a real int: an undefined method here resolves to a truthy
        _Stub, which makes the condition report every target as in-arc.

        Range semantics: MaxDamageDistance == 0 means UNBOUNDED, not
        unreachable — most hardpoints omit the field, and treating 0 as a
        zero-radius limit would silently disable every such bank.
        """
        if not isinstance(target_world_point, TGPoint3):
            return 0
        ship = self.GetParentShip()
        origin = subsystem_world_position(self, ship)
        if origin is None:
            return 0

        dx = target_world_point.x - origin.x
        dy = target_world_point.y - origin.y
        dz = target_world_point.z - origin.z
        dist = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist <= 0.0:
            return 0

        max_range = 0.0
        prop = self.GetProperty() if hasattr(self, "GetProperty") else None
        if prop is not None and hasattr(prop, "GetMaxDamageDistance"):
            try:
                max_range = float(prop.GetMaxDamageDistance())
            except Exception:
                max_range = 0.0
        if max_range > 0.0 and dist > max_range:
            return 0

        aim = TGPoint3(dx / dist, dy / dist, dz / dist)
        return 1 if _emitter_in_arc(self, ship, aim) else 0
```

If `_math` is not already imported in this module, add `import math as _math` at the top
alongside the existing imports. Confirm `subsystem_world_position` and `TGPoint3` are
imported in this module; if not, import them from `engine.appc.subsystems` and
`engine.appc.math` respectively.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_phaser_can_hit.py -v`
Expected: 6 passed.

- [ ] **Step 5: Remove the now-false "unspecifiable" note**

`engine/appc/weapon_subsystems.py:684` lists `CanHit` among methods that are
"DELIBERATELY ABSENT ... IsInArc/CanHit are additionally unspecifiable — their BC
signatures cannot be recovered from the SDK." That docstring belongs to the *leaf weapon*
base and its "zero SDK call sites" claim was verified **on a tube**. Edit it to say:
`CanHit` is implemented on `PhaserBank` (one SDK call site,
`ConditionInPhaserFiringArc.py:175`); `IsInArc` remains absent with zero call sites.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. Investigate any failure not in `tests/known_failures.txt` before committing.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/weapon_subsystems.py tests/unit/test_phaser_can_hit.py
git commit -m "feat(weapons): implement PhaserBank.CanHit arc+range test

ConditionInPhaserFiringArc.py:175 calls this in live AI (FedAttack, AI/Setup).
Undefined, it resolved to a truthy _Stub and every target read as in-arc.
Reuses _emitter_in_arc; MaxDamageDistance == 0 means unbounded."
```

---

## Group B — Set-to-set warp exit velocity

### Task 2: Give warp arrival a chosen velocity

Nothing in the set-change path sets velocity, so arrival velocity is currently whatever
the ship happened to carry — accidental, not designed. **Decision (Mark, 2026-08-09):**
the ship keeps its commanded throttle, and the velocity vector is re-derived along the
placement's new world-forward.

**Files:**
- Modify: `engine/appc/warp.py:331-346` (`_PlacePlayerAction._do_play`)
- Test: `tests/unit/test_warp_exit_velocity.py` (create)

**Interfaces:**
- Consumes: `ShipClass._current_speed` (`ships.py:114`), `ObjectClass.GetWorldForwardTG()`, `ShipClass.SetVelocity(TGPoint3)`.
- Produces: no new public API — `_PlacePlayerAction._do_play` gains a final velocity step.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_warp_exit_velocity.py`:

```python
"""Warp arrival velocity.

Set-to-set warp is a teleport: the ship is removed from one set, added to
another, and placed at a named placement that supplies a NEW orientation.
Chosen behaviour (Mark, 2026-08-09): keep the commanded throttle, re-aim the
velocity along the new facing. Previously nothing set velocity at all, so
arrival velocity was accidental.
"""
from engine.appc.math import TGPoint3
from engine.appc.warp import _PlacePlayerAction


class _Placed:
    """Ship double: PlaceObjectByName installs a new heading, as the real
    placement does. Only the surface _do_play touches."""
    def __init__(self, speed, heading):
        self._current_speed = speed
        self._heading = heading
        self._velocity = TGPoint3(0.0, 0.0, 0.0)
        self.placed_as = None
    def GetName(self): return "player"
    def PlaceObjectByName(self, name): self.placed_as = name
    def GetWorldForwardTG(self): return self._heading
    def SetVelocity(self, v): self._velocity = v
    def GetVelocity(self): return self._velocity


class _Set:
    def __init__(self): self.added = []
    def GetObject(self, name): return None
    def RemoveObjectFromSet(self, name): pass
    def AddObjectToSet(self, obj, name): self.added.append(name)


def _run(monkeypatch, ship, dest_name="dest"):
    import App
    dest = _Set()
    class _SetMgr:
        _sets = {}
        def GetSet(self, name): return dest if name == dest_name else None
    monkeypatch.setattr(App, "g_kSetManager", _SetMgr(), raising=False)
    _PlacePlayerAction(ship, dest_name, "placement_a")._do_play()
    return dest


def test_arrival_velocity_follows_the_new_heading(monkeypatch):
    ship = _Placed(speed=4.0, heading=TGPoint3(0.0, 1.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (round(v.x, 6), round(v.y, 6), round(v.z, 6)) == (0.0, 4.0, 0.0)


def test_arrival_velocity_uses_placement_heading_not_pre_warp_heading(monkeypatch):
    """The whole point: the placement re-aims the ship, so a ship that warps
    while pointing +Y must leave along its NEW facing, here +X."""
    ship = _Placed(speed=3.0, heading=TGPoint3(1.0, 0.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (round(v.x, 6), round(v.y, 6), round(v.z, 6)) == (3.0, 0.0, 0.0)


def test_a_stopped_ship_arrives_stopped(monkeypatch):
    ship = _Placed(speed=0.0, heading=TGPoint3(0.0, 1.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_no_destination_set_leaves_velocity_untouched(monkeypatch):
    """Existing no-op path must stay a no-op — do not stamp velocity on a ship
    that never moved."""
    ship = _Placed(speed=5.0, heading=TGPoint3(0.0, 1.0, 0.0))
    ship.SetVelocity(TGPoint3(9.0, 9.0, 9.0))
    _PlacePlayerAction(ship, "", "placement_a")._do_play()
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (9.0, 9.0, 9.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_warp_exit_velocity.py -v`
Expected: the three positive tests FAIL (velocity stays `(0,0,0)` — nothing sets it);
`test_no_destination_set_leaves_velocity_untouched` PASSES already.

- [ ] **Step 3: Implement the arrival velocity**

In `engine/appc/warp.py`, at the end of `_PlacePlayerAction._do_play`, after
`ship.PlaceObjectByName(self._placement)`:

```python
        # Warp arrival velocity. The placement supplies a NEW orientation, so
        # re-derive the velocity vector along the new facing while preserving
        # the commanded throttle (Mark, 2026-08-09). Before this, nothing set
        # velocity on a set-to-set warp at all and arrival velocity was
        # whatever the ship happened to carry in — accidental, not designed.
        speed = float(getattr(ship, "_current_speed", 0.0) or 0.0)
        fwd = ship.GetWorldForwardTG() if hasattr(ship, "GetWorldForwardTG") else None
        if fwd is not None and hasattr(ship, "SetVelocity"):
            ship.SetVelocity(TGPoint3(fwd.x * speed, fwd.y * speed, fwd.z * speed))
```

Confirm `TGPoint3` is imported in `warp.py`; if not, add
`from engine.appc.math import TGPoint3`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_exit_velocity.py -v`
Expected: 4 passed.

- [ ] **Step 5: Confirm the existing warp spine still passes**

Run: `uv run pytest tests/unit/test_warp_spine.py -v`
Expected: all pass. If `test_warp_sequence_moves_player_and_terminates_source` or
`test_depart_tears_down_source_and_parks_player_in_transit` breaks, its ship double
lacks `GetWorldForwardTG`/`SetVelocity` — the `hasattr` guards above should prevent
that, so a failure means the guard is wrong, not the test.

- [ ] **Step 6: Update the OQ record**

In `docs/gap_analysis.md`, OQ-2.2: mark the set-to-set half resolved, citing
`engine/appc/warp.py` and `tests/unit/test_warp_exit_velocity.py`, and note it is a
**chosen default awaiting live confirmation**, not a recovered BC behaviour — the
reference could not reach it (best relevance 0.32 against a 0.35 floor). If that
leaves no unmarked OQ but the summary line still lists one, `tests/docs/
test_doc_consistency.py` will fail; update the `Still open:` line to match.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/warp.py tests/unit/test_warp_exit_velocity.py docs/gap_analysis.md
git commit -m "feat(warp): give set-to-set warp arrival a chosen velocity

Nothing set velocity on a set change, so arrival velocity was accidental. The
ship now keeps its commanded throttle, re-aimed along the placement's new
world-forward. A chosen default awaiting live confirmation, not recovered BC
behaviour."
```

---

## Group C — DynamicMusic engine surface

`DynamicMusic.py` owns the queue and state machine already. We supply the manager and
the two event types it waits on. Three tasks: manager surface, audio playback, wiring.

### Task 3: `MusicManager` and the two event types

**Files:**
- Create: `engine/appc/music_manager.py`
- Modify: `App.py` (expose `g_kMusicManager`, `ET_MUSIC_DONE`, `ET_MUSIC_CONDITION_CHANGED`)
- Test: `tests/unit/test_music_manager.py` (create)

**Interfaces:**
- Produces: `MusicManager` with **signatures taken from real SDK call sites, not inferred** — `LoadMusic(path, name, beat=0.0) -> None` (FILE first, `DynamicMusic.py:60`), `UnloadMusic(name) -> None` (one track by name, `:78`), `StartMusic(name, looping=1) -> int` (**returns 1/0**, branched on at `:178`), `StopMusic() -> None`, `PlayFanfare(name) -> None`, `IsEnabled() -> int` / `SetEnabled(value) -> None` (`E8M2.py:6558-6568`), `set_backend(backend)`, `current() -> str | None`; module-level `App.g_kMusicManager`; int constants `App.ET_MUSIC_DONE`, `App.ET_MUSIC_CONDITION_CHANGED`.

> ⚠️ **CORRECTED 2026-08-09 mid-execution.** The first draft of this task guessed
> the signatures and was wrong four ways: argument order (name/path reversed),
> `UnloadMusic`'s arity (it takes a name), `StartMusic`'s return (load-bearing),
> and it omitted `IsEnabled`/`SetEnabled` entirely. Implementing the guess broke
> 14 QuickBattle/host-loop tests, because supplying a real `g_kMusicManager`
> makes the previously-silent SDK path actually execute. **Read the call sites:**
> `grep -rn "g_kMusicManager\." sdk/Build/scripts/`. Note also that DynamicMusic
> is driven by QuickBattle (`QuickBattleGame.py:66`) as well as Maelstrom.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_music_manager.py`:

```python
"""g_kMusicManager — the surface DynamicMusic.py drives.

DynamicMusic is live: Maelstrom.py:111 Initialize, :265 Terminate, and
ChangeMusic from Episodes 1,4,6,7,8. Every symbol below was absent, so
App.<name> resolved to a _NamedStub and the whole music system was a silent
no-op (stub heatmap ranks 163/164, last seen 2026-08-06).
"""
import App
from engine.appc.music_manager import MusicManager


def test_app_exposes_the_music_manager_and_event_types():
    assert isinstance(App.g_kMusicManager, MusicManager)
    # Undefined App constants collapse to int()==0 and silently match each
    # other; these must be distinct real ints.
    assert type(App.ET_MUSIC_DONE) is int
    assert type(App.ET_MUSIC_CONDITION_CHANGED) is int
    assert App.ET_MUSIC_DONE != App.ET_MUSIC_CONDITION_CHANGED


def test_start_music_requires_a_loaded_name():
    m = MusicManager()
    m.StartMusic("combat")
    assert m.current() is None, "unloaded name must not become current"


def test_load_then_start_makes_it_current():
    m = MusicManager()
    m.LoadMusic("combat", "data/music/combat.mp3")
    m.StartMusic("combat")
    assert m.current() == "combat"


def test_stop_music_clears_current():
    m = MusicManager()
    m.LoadMusic("combat", "data/music/combat.mp3")
    m.StartMusic("combat")
    m.StopMusic()
    assert m.current() is None


def test_unload_music_drops_the_registry_and_stops_playback():
    m = MusicManager()
    m.LoadMusic("combat", "data/music/combat.mp3")
    m.StartMusic("combat")
    m.UnloadMusic()
    assert m.current() is None
    m.StartMusic("combat")
    assert m.current() is None, "UnloadMusic must drop the name registry too"


def test_starting_a_second_track_replaces_the_first():
    m = MusicManager()
    m.LoadMusic("a", "data/music/a.mp3")
    m.LoadMusic("b", "data/music/b.mp3")
    m.StartMusic("a")
    m.StartMusic("b")
    assert m.current() == "b"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_music_manager.py -v`
Expected: FAIL at import — `engine.appc.music_manager` does not exist.

- [ ] **Step 3: Implement `MusicManager`**

Create `engine/appc/music_manager.py`:

```python
"""MusicManager — App.g_kMusicManager.

The SDK's DynamicMusic.py owns the music STATE MACHINE (EnqueueMusic,
ProcessQueue, SwitchMusic, OverrideMusic, StandardCombatMusic). This class
supplies only the primitives it drives, mirroring BC's TGMusic lifecycle:
LoadMusic / StartMusic / StopMusic / UnloadMusic / PlayFanfare.

Per the clean-room reference (spec/TGAudio.md section 6, reviewed-not-tested):
TGMusic::StartMusic registers a fade timer, so transitions are volume-ramped
rather than abrupt, and LoadMusic reads a Sound/StreamMusic config toggle.
BC's second path, TGRedbook (CD audio via MCI), does not apply to us.

Playback itself is injected via set_backend so this class stays testable with
no audio device present.
"""


class MusicManager:
    def __init__(self) -> None:
        self._paths: dict[str, str] = {}   # music name -> file path
        self._current: str | None = None
        self._backend = None               # injected by the host, see set_backend

    def set_backend(self, backend) -> None:
        """Host-injected player. None means 'no audio' — the manager still
        tracks state so mission logic and tests behave identically."""
        self._backend = backend

    def LoadMusic(self, name, path) -> None:
        self._paths[str(name)] = str(path)

    def UnloadMusic(self) -> None:
        self.StopMusic()
        self._paths.clear()

    def StartMusic(self, name, looping=1, start_time=0.0) -> None:
        key = str(name)
        path = self._paths.get(key)
        if path is None:
            # Unknown name: stay silent rather than inventing a track. BC
            # registers names before starting them.
            return
        self._current = key
        if self._backend is not None:
            self._backend.play(path, looping=bool(looping),
                               start_time=float(start_time))

    def StopMusic(self) -> None:
        self._current = None
        if self._backend is not None:
            self._backend.stop()

    def PlayFanfare(self, name) -> None:
        """One-shot sting over the current track. Does not become `current`:
        DynamicMusic resumes the queue after it, so the underlying track is
        still what is playing."""
        path = self._paths.get(str(name))
        if path is not None and self._backend is not None:
            self._backend.play_oneshot(path)

    def current(self) -> "str | None":
        return self._current
```

- [ ] **Step 4: Expose the manager and constants on `App`**

In `App.py`, alongside the other manager singletons and `ET_*` constants, add:

```python
from engine.appc.music_manager import MusicManager
g_kMusicManager = MusicManager()
```

and register `ET_MUSIC_DONE` and `ET_MUSIC_CONDITION_CHANGED` the same way the
surrounding `ET_*` event types are declared in this file — follow the existing pattern
exactly (do not invent a second mechanism). They must be distinct ints.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_music_manager.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/music_manager.py App.py tests/unit/test_music_manager.py
git commit -m "feat(audio): add g_kMusicManager and the two music event types

DynamicMusic is driven by the Maelstrom campaign but every engine symbol it
needs was absent, so App.<name> collapsed to a _NamedStub and music was a
silent no-op. Supplies the TGMusic-shaped primitives; the SDK keeps the queue."
```

---

### Task 4: Music playback backend with a volume ramp

**Files:**
- Create: `engine/audio/music.py`
- Test: `tests/audio/test_music_playback.py` (create)

**Interfaces:**
- Consumes: `engine/audio/tg_sound.py` `SetVolume(gain)` (line 141).
- Produces: `MusicPlayer` with `play(path, looping=True) -> None`, `play_oneshot(path) -> None`, `stop() -> None`, `update(dt) -> None`, `volume() -> float`; constant `FADE_SECONDS = 2.0`. (No `start_time`: the SDK's only call is `StartMusic(sMusicName, bLooping)`.)

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_music_playback.py`:

```python
"""Music playback with a volume ramp.

Per the clean-room reference (spec/TGAudio.md section 6, reviewed-not-tested):
TGMusic::StartMusic registers a fade timer, so a track change ramps rather than
cutting. Whether BC crossfades (both tracks audible) or fades out then in is NOT
established by the reference — this implements fade-out-then-in, the
conservative reading, and it needs live confirmation before being called
faithful.
"""
from engine.audio.music import MusicPlayer, FADE_SECONDS


class _FakeSound:
    def __init__(self, path):
        self.path = path
        self.gain = 1.0
        self.stopped = False
    def SetVolume(self, gain): self.gain = gain
    def Stop(self): self.stopped = True


def _player():
    made = []
    def factory(path):
        s = _FakeSound(path)
        made.append(s)
        return s
    return MusicPlayer(sound_factory=factory), made


def test_play_starts_the_track_silent_and_ramps_up():
    p, made = _player()
    p.play("data/music/a.mp3")
    assert made[0].path == "data/music/a.mp3"
    assert p.volume() == 0.0, "must start silent so the ramp is audible"
    p.update(FADE_SECONDS)
    assert p.volume() == 1.0


def test_ramp_is_partial_midway():
    p, _ = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS / 2.0)
    assert 0.0 < p.volume() < 1.0


def test_stop_ramps_down_then_stops_the_sound():
    p, made = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS)
    p.stop()
    p.update(FADE_SECONDS)
    assert p.volume() == 0.0
    assert made[0].stopped is True


def test_playing_a_second_track_stops_the_first():
    p, made = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS)
    p.play("data/music/b.mp3")
    p.update(FADE_SECONDS)
    assert made[0].stopped is True
    assert made[1].path == "data/music/b.mp3"


def test_volume_never_exceeds_one_or_drops_below_zero():
    p, _ = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS * 10.0)
    assert p.volume() == 1.0
    p.stop()
    p.update(FADE_SECONDS * 10.0)
    assert p.volume() == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/audio/test_music_playback.py -v`
Expected: FAIL at import — `engine.audio.music` does not exist.

- [ ] **Step 3: Implement `MusicPlayer`**

Create `engine/audio/music.py`:

```python
"""Music playback with a volume ramp.

Per the clean-room reference (spec/TGAudio.md section 6, reviewed-not-tested):
TGMusic::StartMusic registers a fade timer via TGTimerManager, so track changes
ramp rather than cut. The reference does NOT establish whether BC crossfades
(both tracks audible) or fades out then in; this implements fade-out-then-in as
the conservative reading. Needs live confirmation before being called faithful.

`sound_factory` is injected so this is testable with no audio device.
"""

FADE_SECONDS = 2.0


class MusicPlayer:
    def __init__(self, sound_factory) -> None:
        self._factory = sound_factory
        self._sound = None
        self._volume = 0.0
        self._target = 0.0
        self._pending = None       # (path, looping, start_time) awaiting fade-out
        self._stop_after_fade = False

    def play(self, path, looping=True, start_time=0.0) -> None:
        if self._sound is None:
            self._begin(path, looping, start_time)
            return
        # A track is playing: fade it out first, then swap.
        self._pending = (path, looping, start_time)
        self._target = 0.0

    def play_oneshot(self, path) -> None:
        """Fanfare sting layered over the current track — no ramp, no swap."""
        self._factory(path)

    def stop(self) -> None:
        self._target = 0.0
        self._stop_after_fade = True

    def update(self, dt) -> None:
        if FADE_SECONDS <= 0.0:
            self._volume = self._target
        else:
            step = float(dt) / FADE_SECONDS
            if self._volume < self._target:
                self._volume = min(self._target, self._volume + step)
            elif self._volume > self._target:
                self._volume = max(self._target, self._volume - step)
        if self._sound is not None:
            self._sound.SetVolume(self._volume)

        if self._volume <= 0.0:
            if self._pending is not None:
                path, looping, start_time = self._pending
                self._pending = None
                self._teardown()
                self._begin(path, looping, start_time)
            elif self._stop_after_fade:
                self._stop_after_fade = False
                self._teardown()

    def volume(self) -> float:
        return self._volume

    def _begin(self, path, looping, start_time) -> None:
        self._sound = self._factory(path)
        self._volume = 0.0
        self._target = 1.0
        self._sound.SetVolume(0.0)

    def _teardown(self) -> None:
        if self._sound is not None and hasattr(self._sound, "Stop"):
            self._sound.Stop()
        self._sound = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/audio/test_music_playback.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add engine/audio/music.py tests/audio/test_music_playback.py
git commit -m "feat(audio): music playback with a volume ramp

StartMusic registers a fade timer in BC (spec/TGAudio.md s6), so track changes
ramp. Whether BC crossfades or fades out then in is not established; this is
fade-out-then-in, the conservative reading, pending live confirmation."
```

---

### Task 5: Wire the queue advance and confirm DynamicMusic drives it

`DynamicMusic.MusicDone` advances the queue when `ET_MUSIC_DONE` fires. Without that
event the queue stalls after the first track.

**Files:**
- Modify: `engine/appc/music_manager.py` (fire `ET_MUSIC_DONE` on track end)
- Modify: `tests/unit/test_music_manager.py` (add the wiring tests)

**Interfaces:**
- Consumes: `MusicManager` from Task 3, `MusicPlayer` from Task 4.
- Produces: `MusicManager.notify_track_finished() -> None`, which broadcasts `ET_MUSIC_DONE`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_music_manager.py`:

```python
def test_track_end_broadcasts_et_music_done(monkeypatch):
    """DynamicMusic.MusicDone drives ProcessQueue off this event. Without it the
    queue stalls after the first track and the mission plays one clip forever."""
    import App
    sent = []

    class _EvtMgr:
        def AddBroadcastPythonFuncHandler(self, *a, **k): pass
        def BroadcastEvent(self, evt): sent.append(evt)

    monkeypatch.setattr(App, "g_kEventManager", _EvtMgr(), raising=False)

    m = MusicManager()
    m.LoadMusic("combat", "data/music/combat.mp3")
    m.StartMusic("combat")
    m.notify_track_finished()

    assert sent, "track end must broadcast an event"
    assert m.current() is None, "a finished track is no longer current"


def test_track_end_on_an_idle_manager_is_a_no_op(monkeypatch):
    import App
    sent = []

    class _EvtMgr:
        def AddBroadcastPythonFuncHandler(self, *a, **k): pass
        def BroadcastEvent(self, evt): sent.append(evt)

    monkeypatch.setattr(App, "g_kEventManager", _EvtMgr(), raising=False)

    m = MusicManager()
    m.notify_track_finished()
    assert sent == [], "no track was playing, so nothing finished"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_music_manager.py -v`
Expected: the two new tests FAIL — `notify_track_finished` does not exist.

- [ ] **Step 3: Implement the event broadcast**

Add to `MusicManager` in `engine/appc/music_manager.py`:

```python
    def notify_track_finished(self) -> None:
        """Called by the host when the current track reaches its end.
        Broadcasts ET_MUSIC_DONE, which DynamicMusic.MusicDone handles to
        advance its queue (DynamicMusic.py:121 -> ProcessQueue at :132).
        Without this the queue stalls on the first track."""
        if self._current is None:
            return
        self._current = None
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_MUSIC_DONE)
        App.g_kEventManager.BroadcastEvent(evt)
```

If `TGEvent_Create()` / `SetEventType` do not match this module's existing event-creation
pattern, follow whatever pattern the surrounding `engine/appc/` code uses to build and
broadcast an event — do not introduce a second mechanism.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_music_manager.py -v`
Expected: 8 passed.

- [ ] **Step 5: Wire the player into the manager and pump it**

Tasks 3 and 4 build two halves that do not yet meet: nothing injects a `MusicPlayer`
into `g_kMusicManager`, nothing calls `MusicPlayer.update(dt)`, and nothing calls
`notify_track_finished()`. Without this step the whole group is inert.

In `engine/host_loop.py`, alongside the other audio wiring:

1. Construct a `MusicPlayer` with the host's real sound factory (the same path
   `engine/audio/` already uses to build a `TGSound` from a file) and call
   `App.g_kMusicManager.set_backend(player)` once at boot.
2. Call `player.update(dt)` every frame from the audio pump, using the same `dt` the
   rest of the audio layer uses. Use `_player_dt` if the surrounding audio code does, so
   music freezes under pause rather than sliding on wall-clock — match the neighbours
   rather than choosing independently.
3. When the backing sound reports completion, call
   `App.g_kMusicManager.notify_track_finished()`. If the audio backend has no
   completion callback, poll it in the same per-frame update: a track whose sound is no
   longer playing and was not stopped by us has finished.

Follow the existing registration pattern in `host_loop.py` for the other audio
subsystems; do not invent a parallel lifecycle.

Add a guard test to `tests/unit/test_music_manager.py`:

```python
def test_manager_forwards_playback_to_its_backend():
    """The manager must actually drive a backend — Tasks 3 and 4 are inert
    unless something injects one."""
    class _Backend:
        def __init__(self): self.played, self.stopped = [], 0
        def play(self, path, looping=True, start_time=0.0): self.played.append(path)
        def play_oneshot(self, path): self.played.append(("oneshot", path))
        def stop(self): self.stopped += 1

    b = _Backend()
    m = MusicManager()
    m.set_backend(b)
    m.LoadMusic("combat", "data/music/combat.mp3")
    m.StartMusic("combat")
    assert b.played == ["data/music/combat.mp3"]
    m.StopMusic()
    assert b.stopped == 1
```

Run: `uv run pytest tests/unit/test_music_manager.py -v`
Expected: 9 passed.

- [ ] **Step 6: Confirm DynamicMusic no longer hits stubs**

Run a mission that drives music through the harness and confirm `g_kMusicManager` no
longer appears as an unimplemented attribute:

```bash
uv run python tools/mission_harness.py --mission Maelstrom/Episode1 2>&1 | tail -20
```

If that entry point differs, use whatever invocation `tools/mission_harness.py --help`
documents. The check that matters: `g_kMusicManager` must not be reported as a stub hit.

- [ ] **Step 7: Update the OQ record**

In `docs/gap_analysis.md`, mark OQ-6.1 resolved, citing `engine/appc/music_manager.py`,
`engine/audio/music.py` and their tests. **State plainly that it is not yet
live-verified.** Update the `Still open:` summary line and count — `tests/docs/
test_doc_consistency.py` enforces that it matches. Also update the
`### Gap analysis OQs` block in `CLAUDE.md`.

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/music_manager.py tests/unit/test_music_manager.py docs/gap_analysis.md CLAUDE.md
git commit -m "feat(audio): broadcast ET_MUSIC_DONE so DynamicMusic advances its queue

DynamicMusic.MusicDone drives ProcessQueue off this event; without it the queue
stalls on the first track. Closes OQ-6.1 pending live verification."
```

---

## After this plan

**Mark must verify OQ-6.1 in-game.** Passing tests show the manager, the ramp and the
event wiring behave; they cannot show that music is audible, that the right track plays
for the right gameplay state, or that transitions sound right. Report it as
*implemented, not verified* until he has run it.

Two things to raise with him after the live run:

1. **Crossfade vs fade-out-then-in.** Task 4 implements the latter as the conservative
   reading; the reference does not settle it. If BC crossfades, `MusicPlayer` needs two
   concurrent sounds rather than one.
2. **Warp arrival velocity** (Task 2) is a *chosen* default, not recovered behaviour.
   Worth re-asking the reference once its retrieval scorer improves — the likely section
   scored 0.32 against a 0.35 floor.
