# Contact Index — Stages 1 & 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the target list derive its membership from the player's current system instead of mirroring one set bound at mission load, and close the live `SetTargetable` gap.

**Architecture:** A persistent per-set ship index (`ContactIndex`) maintained by the events `SetClass` already fires. A single read-time query (`perception.contacts_for`) answers "which ships are in this observer's system". `STTargetMenu` keeps a per-ship row cache and projects it over that answer, so its children become derived rather than incrementally maintained.

**Tech Stack:** Python 3, pytest. No C++ changes — nothing here touches `native/`.

**Spec:** `docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md`

## Global Constraints

- **Scope is stages 1–2 only.** No behaviour changes. Detectability stays exactly as it is today: `update_target_list_visibility` keeps writing `IsVisible`, and `can_detect` is not touched. Stages 3–4 (detectability consolidation, cloak/nebula gameplay changes) get their own plan.
- **Shared checkout.** Never run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it to `/tmp`, mutate, restore by `cp`, and `diff` to prove the restore.
- **Branch:** work on `feat/contact-index-perception` (already created, spec committed).
- **Test gate:** `scripts/check_tests.sh` — it builds C++ and runs pytest + ctest, diffing against `tests/known_failures.txt`. Never call a failure "pre-existing" by eyeball. Per-task steps use targeted `pytest` for speed; run the full gate before the final commit of each stage.
- **Units:** distances and ranges are game units. Variables end `_gu` / `_gups`. Never `_m` or `_km` inside the engine.
- **Do not use `hasattr()` to test for engine surface.** `TGObject.__getattr__` returns a truthy `_Stub` for any missing attribute, so `hasattr` is vacuously true. Use `isinstance` or `engine.core.ids.implements()`.

---

### Task 1: `ContactIndex` — ships bucketed by set

**Files:**
- Create: `engine/appc/contact_index.py`
- Test: `tests/unit/test_contact_index.py`

**Interfaces:**
- Consumes: `engine.appc.ships.ShipClass` (for the insert-time type filter)
- Produces:
  - `on_added(pSet, obj) -> None`
  - `on_removed(pSet, obj) -> None`
  - `ships_in(pSet) -> tuple` — insertion-ordered, empty tuple for an unknown set
  - `reset() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_contact_index.py`:

```python
"""ContactIndex buckets ShipClass objects by the set that contains them."""
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_added_ship_appears_in_its_set_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    contact_index.on_added(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_removed_ship_leaves_the_bucket():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    contact_index.on_added(pSet, ship)

    contact_index.on_removed(pSet, ship)

    assert contact_index.ships_in(pSet) == ()


def test_buckets_are_independent():
    contact_index.reset()
    deep_space = SetClass()
    vesuvi = SetClass()
    a, b = _ship("A"), _ship("B")

    contact_index.on_added(deep_space, a)
    contact_index.on_added(vesuvi, b)

    assert contact_index.ships_in(deep_space) == (a,)
    assert contact_index.ships_in(vesuvi) == (b,)


def test_insertion_order_is_preserved():
    contact_index.reset()
    pSet = SetClass()
    a, b, c = _ship("A"), _ship("B"), _ship("C")

    for s in (a, b, c):
        contact_index.on_added(pSet, s)

    assert contact_index.ships_in(pSet) == (a, b, c)


def test_non_ships_never_enter_a_bucket():
    """Waypoints, grids, planets and the bridge-interior ObjectClass are not
    contacts. Filtering at insert means no read-time type test is needed."""
    from engine.appc.objects import ObjectClass
    contact_index.reset()
    pSet = SetClass()
    not_a_ship = ObjectClass()

    contact_index.on_added(pSet, not_a_ship)

    assert contact_index.ships_in(pSet) == ()


def test_unknown_set_reads_empty():
    contact_index.reset()
    assert contact_index.ships_in(SetClass()) == ()


def test_double_add_does_not_duplicate():
    """AddObjectToSet is called again when a mission re-registers a ship
    under the same identifier; the bucket must not grow a second entry."""
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    contact_index.on_added(pSet, ship)
    contact_index.on_added(pSet, ship)

    assert contact_index.ships_in(pSet) == (ship,)


def test_remove_of_absent_ship_is_silent():
    contact_index.reset()
    pSet = SetClass()
    contact_index.on_removed(pSet, _ship("Ghost"))  # must not raise
    assert contact_index.ships_in(pSet) == ()


def test_reset_clears_every_bucket():
    contact_index.reset()
    pSet = SetClass()
    contact_index.on_added(pSet, _ship("Dauntless"))

    contact_index.reset()

    assert contact_index.ships_in(pSet) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_contact_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.contact_index'`

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/contact_index.py`:

```python
"""Ships bucketed by the set that contains them — the persistent half of the
contact model.

The store holds what EXISTS. It is observer-independent by construction: AI
ships and the player ask the same question, and the target, hail and scan lists
all read the same buckets. Anything observer-relative (range, cloak, nebula
concealment) is computed at read time by engine.appc.perception, never stored
here.

Only membership is stored. Authored flags (IsTargetable / IsHailable /
IsScannable), alive-or-dead, and positions are read through to the object at
query time. Copying them here would mean a write per change — and for positions,
a write per ship per frame — with a stale contact on any missed write, which is
the exact failure this index exists to remove.

Maintained by SetClass.AddObjectToSet / RemoveObjectFromSet /
DeleteObjectFromSet, which call in directly (the same shape as the existing
ship_lifecycle.publish_added call beside them).

Keyed by the SetClass OBJECT, not its name: QuickBattle renames a set in place
when reloading a region (QuickBattle.py:2678 appends "Dupe"), so a name key
would silently split one bucket in two.
"""
from __future__ import annotations

# SetClass -> list of ShipClass, in insertion order.
_buckets: dict = {}


def on_added(pSet, obj) -> None:
    """Record *obj* as present in *pSet*. Non-ships are ignored, so no
    read-time type test is needed. Idempotent."""
    from engine.appc.ships import ShipClass
    if not isinstance(obj, ShipClass):
        return
    bucket = _buckets.setdefault(pSet, [])
    if obj not in bucket:
        bucket.append(obj)


def on_removed(pSet, obj) -> None:
    """Drop *obj* from *pSet*'s bucket. Silent if absent — RemoveObjectFromSet
    is called for objects that were never ships."""
    bucket = _buckets.get(pSet)
    if not bucket:
        return
    try:
        bucket.remove(obj)
    except ValueError:
        pass


def ships_in(pSet) -> tuple:
    """Ships currently in *pSet*, in insertion order. Empty for an unknown set."""
    return tuple(_buckets.get(pSet, ()))


def reset() -> None:
    """Drop every bucket. Called on mission swap and between tests."""
    _buckets.clear()
```

Note on `obj not in bucket` and `bucket.remove(obj)`: `ShipClass` defines no
`__eq__`/`__hash__`, so both use identity comparison, which is what we want.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_contact_index.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/contact_index.py tests/unit/test_contact_index.py
git commit -m "feat(contacts): ContactIndex — ships bucketed by containing set"
```

---

### Task 2: `SetClass` maintains the index

**Files:**
- Modify: `engine/appc/sets.py:181-199` (`AddObjectToSet`), `:236-242` (`RemoveObjectFromSet`), `:244-249` (`DeleteObjectFromSet`)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`, around line 599)
- Test: `tests/unit/test_contact_index_set_maintenance.py`

**Interfaces:**
- Consumes: `contact_index.on_added`, `contact_index.on_removed`, `contact_index.reset` from Task 1
- Produces: nothing new — `ships_in` now reflects real set membership

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_contact_index_set_maintenance.py`:

```python
"""SetClass keeps the ContactIndex in step with real set membership."""
from engine.appc import contact_index
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_add_object_to_set_indexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")

    pSet.AddObjectToSet(ship, "Dauntless")

    assert contact_index.ships_in(pSet) == (ship,)


def test_remove_object_from_set_deindexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    pSet.AddObjectToSet(ship, "Dauntless")

    pSet.RemoveObjectFromSet("Dauntless")

    assert contact_index.ships_in(pSet) == ()


def test_delete_object_from_set_deindexes_the_ship():
    contact_index.reset()
    pSet = SetClass()
    ship = _ship("Dauntless")
    pSet.AddObjectToSet(ship, "Dauntless")

    pSet.DeleteObjectFromSet("Dauntless")

    assert contact_index.ships_in(pSet) == ()


def test_moving_a_ship_between_sets_moves_its_bucket_entry():
    """The warp path removes from the source set then adds to the
    destination (warp.py:344). The index must follow."""
    contact_index.reset()
    deep_space = SetClass()
    vesuvi = SetClass()
    ship = _ship("Dauntless")
    deep_space.AddObjectToSet(ship, "Dauntless")

    deep_space.RemoveObjectFromSet("Dauntless")
    vesuvi.AddObjectToSet(ship, "Dauntless")

    assert contact_index.ships_in(deep_space) == ()
    assert contact_index.ships_in(vesuvi) == (ship,)


def test_non_ship_set_members_are_not_indexed():
    from engine.appc.objects import ObjectClass
    contact_index.reset()
    pSet = SetClass()

    pSet.AddObjectToSet(ObjectClass(), "waypoint1")

    assert contact_index.ships_in(pSet) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_contact_index_set_maintenance.py -v`
Expected: FAIL — first four tests assert a populated/empty bucket but `ships_in` returns `()` / stale, because `SetClass` does not call the index yet. (`test_non_ship_set_members_are_not_indexed` passes vacuously; that is fine.)

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/sets.py`, inside `AddObjectToSet`, extend the existing
`ShipClass` branch (which already calls `ship_lifecycle.publish_added`):

```python
        from engine.appc.ships import ShipClass
        from engine.appc import ship_lifecycle
        from engine.appc import contact_index
        if isinstance(obj, ShipClass):
            ship_lifecycle.publish_added(obj)
            contact_index.on_added(self, obj)
            self._resolve_player_identity_before_broadcast(obj, identifier)
```

In `RemoveObjectFromSet`, add the de-index beside the existing fire:

```python
    def RemoveObjectFromSet(self, name: str):
        obj = self._objects.get(name)
        if obj is not None:
            from engine.appc import contact_index
            contact_index.on_removed(self, obj)
            self._fire("removed", obj, name)
            self._broadcast_set_transition(obj, entered=False)
        return self._objects.pop(name, None)
```

And identically in `DeleteObjectFromSet`:

```python
    def DeleteObjectFromSet(self, name: str) -> None:
        obj = self._objects.get(name)
        if obj is not None:
            from engine.appc import contact_index
            contact_index.on_removed(self, obj)
            self._fire("removed", obj, name)
            self._broadcast_set_transition(obj, entered=False)
        self._objects.pop(name, None)
```

De-index **before** `_fire` so a subscriber that reads the index during dispatch
sees the post-removal state.

In `tests/conftest.py`, inside `_reset_leakable_engine_globals`, add a reset
block alongside the existing ones:

```python
    # ContactIndex buckets ships by SetClass; sets created in one test would
    # otherwise leak into the next and make membership assertions order-dependent.
    try:
        from engine.appc import contact_index
        contact_index.reset()
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_contact_index_set_maintenance.py tests/unit/test_contact_index.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Check nothing else broke**

Run: `uv run pytest tests/unit -q`
Expected: no new failures versus `tests/known_failures.txt`

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sets.py tests/conftest.py tests/unit/test_contact_index_set_maintenance.py
git commit -m "feat(contacts): SetClass maintains the ContactIndex on add/remove/delete"
```

---

### Task 3: `perception.contacts_for(observer)`

**Files:**
- Create: `engine/appc/perception.py`
- Test: `tests/unit/test_perception_contacts_for.py`

**Interfaces:**
- Consumes: `contact_index.ships_in` from Task 1
- Produces: `contacts_for(observer) -> tuple` — ships in the observer's containing set, excluding the observer. Empty tuple when the observer is `None` or has no containing set.

This is the seam stages 3–4 grow into. It is deliberately thin now.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_perception_contacts_for.py`:

```python
"""contacts_for answers 'which ships are in this observer's system'."""
from engine.appc import contact_index
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_lists_ships_sharing_the_observers_set():
    contact_index.reset()
    pSet = SetClass()
    player, other = _ship("player"), _ship("Galor")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(other, "Galor")

    assert contacts_for(player) == (other,)


def test_excludes_the_observer_itself():
    contact_index.reset()
    pSet = SetClass()
    player = _ship("player")
    pSet.AddObjectToSet(player, "player")

    assert contacts_for(player) == ()


def test_excludes_ships_in_other_systems():
    """The reported bug: QuickBattle spawns into the set the player left."""
    contact_index.reset()
    deep_space, vesuvi = SetClass(), SetClass()
    player, phantom = _ship("player"), _ship("Galor")
    vesuvi.AddObjectToSet(player, "player")
    deep_space.AddObjectToSet(phantom, "Galor")

    assert contacts_for(player) == ()


def test_follows_the_observer_across_a_set_change():
    contact_index.reset()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")
    local = _ship("Sovereign")
    deep_space.AddObjectToSet(player, "player")
    vesuvi.AddObjectToSet(local, "Sovereign")

    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")

    assert contacts_for(player) == (local,)


def test_observer_with_no_set_reads_empty():
    contact_index.reset()
    assert contacts_for(_ship("Adrift")) == ()


def test_none_observer_reads_empty():
    contact_index.reset()
    assert contacts_for(None) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_perception_contacts_for.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.perception'`

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/perception.py`:

```python
"""What an observer can perceive — the read-time half of the contact model.

engine.appc.contact_index holds what EXISTS, bucketed by set. This module
answers the per-observer question, which cannot be stored: the same ship is
perceivable to one observer and not another at the same instant, so a stored
answer would have to be per-observer-per-frame.

STAGE 1 SCOPE: membership only. Detectability (range, cloak, nebula) is still
applied downstream by engine.ui.target_list_visibility exactly as before, so
this change alters no behaviour. Stage 3 folds those rules in here and deletes
that module; stage 4 changes the rules themselves. See
docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md.
"""
from __future__ import annotations

from engine.appc import contact_index


def contacts_for(observer) -> tuple:
    """Ships in *observer*'s containing set, excluding *observer*.

    Empty when there is no observer or it is in no set — which is also what
    makes warp self-correcting: mid-warp the player sits alone in the
    _WarpTransit set, so the list empties without anyone clearing it.
    """
    if observer is None:
        return ()
    pSet = observer.GetContainingSet() if hasattr(observer, "GetContainingSet") else None
    # A real SetClass exposes _objects; a _Stub or None does not. hasattr()
    # cannot discriminate — TGObject.__getattr__ answers every name.
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()
    return tuple(s for s in contact_index.ships_in(pSet) if s is not observer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_perception_contacts_for.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/perception.py tests/unit/test_perception_contacts_for.py
git commit -m "feat(contacts): perception.contacts_for — membership query for one observer"
```

---

### Task 4: `STTargetMenu` derives its children

**Files:**
- Modify: `engine/appc/target_menu.py:58-131` (`STTargetMenu.__init__` and traversal), `:102-105` (`ClearTargetList`), `:130-166` (`RebuildShipMenu`), `:209-231` (`RebuildShipMenus`)
- Test: `tests/unit/test_target_menu_derived_children.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–3 directly — membership arrives via `set_contacts`, so the menu stays testable in isolation
- Produces:
  - `STTargetMenu.set_contacts(ships) -> None`
  - `STTargetMenu.RebuildShipMenu(ship)` now populates the row cache instead of appending a child
  - All child accessors project the cache over the pushed contacts

**Why a row cache:** `CycleTarget` calls `GetObjectEntry(target)` then walks `GetNextChild` from the returned row (`TacticalInterfaceHandlers.py:711-730`), so row identity must be stable across calls. Only *membership* is derived.

**No eviction, deliberately.** A row for a ship that leaves the world becomes unreachable, because the projection only ever walks the pushed contact list. The singleton is recreated on mission swap (`_reset_target_menu_singleton`), so cached rows cannot outlive a mission. Adding a `ship_lifecycle` subscription would buy nothing and introduce a subscriber-lifetime bug class.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_target_menu_derived_children.py`:

```python
"""STTargetMenu children are a projection of the row cache over pushed contacts."""
import App
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def test_pushed_contacts_become_children():
    menu = _menu()
    a, b = _ship("Galor"), _ship("Keldon")

    menu.set_contacts([a, b])

    assert menu.GetNumChildren() == 2
    assert menu.GetFirstChild().GetShip() is a
    assert menu.GetLastChild().GetShip() is b


def test_children_follow_a_new_push_without_any_clear():
    """The whole point: changing system is a change of answer, not a rebuild."""
    menu = _menu()
    old, new = _ship("Galor"), _ship("Sovereign")
    menu.set_contacts([old])

    menu.set_contacts([new])

    assert menu.GetNumChildren() == 1
    assert menu.GetFirstChild().GetShip() is new


def test_row_identity_is_stable_across_pushes():
    """CycleTarget resolves a row then walks siblings from it; a row object
    that changed between calls would break sibling traversal."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([ship])
    first = menu.GetObjectEntry(ship)

    menu.set_contacts([ship])

    assert menu.GetObjectEntry(ship) is first


def test_row_survives_leaving_and_re_entering_the_contact_list():
    """A warp round-trip must not pay to rebuild subsystem trees."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([ship])
    original = menu.GetObjectEntry(ship)

    menu.set_contacts([])
    menu.set_contacts([ship])

    assert menu.GetObjectEntry(ship) is original


def test_object_entry_is_none_for_a_ship_outside_the_contact_list():
    """GetObjectEntry must agree with the listing, or CycleTarget could
    select a contact the panel refuses to draw."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([ship])
    menu.set_contacts([])

    assert menu.GetObjectEntry(ship) is None


def test_sibling_traversal_walks_the_projection():
    menu = _menu()
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    menu.set_contacts([a, b, c])

    first = menu.GetFirstChild()
    second = menu.GetNextChild(first)
    third = menu.GetNextChild(second)

    assert (first.GetShip(), second.GetShip(), third.GetShip()) == (a, b, c)
    assert menu.GetNextChild(third) is None
    assert menu.GetPrevChild(second) is first


def test_rebuild_ship_menu_populates_subsystem_rows():
    """RebuildShipMenu still refreshes a row's subsystem tree — it is real
    SDK surface (MissionLib.HideSubsystems), it just no longer adds a child."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([ship])

    menu.RebuildShipMenu(ship)

    assert menu.GetObjectEntry(ship) is not None


def test_rebuild_ship_menu_for_a_non_contact_does_not_list_it():
    """MissionLib may refresh a ship in another set; that must not list it."""
    menu = _menu()
    elsewhere = _ship("Faraway")

    menu.RebuildShipMenu(elsewhere)

    assert menu.GetNumChildren() == 0


def test_non_ships_are_ignored():
    from engine.appc.objects import ObjectClass
    menu = _menu()
    menu.set_contacts([ObjectClass()])
    assert menu.GetNumChildren() == 0


def test_children_attribute_reflects_the_projection():
    """Nothing may bypass the projection by reading _children directly."""
    menu = _menu()
    ship = _ship("Galor")
    menu.set_contacts([ship])

    assert [c.GetShip() for c in menu._children] == [ship]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_target_menu_derived_children.py -v`
Expected: FAIL — `AttributeError`/`_Stub` on `set_contacts`, which does not exist yet

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/target_menu.py`, replace `STTargetMenu.__init__` and the
traversal block:

```python
class STTargetMenu(STTopLevelMenu):
    """The whole target list — children are STSubsystemMenu rows.

    Children are DERIVED, not stored. `_row_cache` holds one row per ship ever
    seen (identity-stable, because CycleTarget resolves a row then walks
    siblings from it); `_contacts` is the membership pushed each frame. The
    child list is their intersection, computed on read.

    This is why warp needs no target-list code: mid-warp the player is alone in
    the _WarpTransit set, so the pushed list is empty and the menu empties
    itself; on arrival it fills from the destination set.
    """

    def __init__(self, label: str = ""):
        # Set before super().__init__ — the base assigns self._children, which
        # is a property here whose getter reads these.
        self._row_cache: dict = {}
        self._contacts: tuple = ()
        super().__init__(label)
        # The last ship the player manually selected. Survives across mission
        # saves so a reload restores the selection.
        self._persistent_target_name: str | None = None

    # ── Derived membership ───────────────────────────────────────────────────

    def set_contacts(self, ships) -> None:
        """Push this frame's membership (from perception.contacts_for).

        Idempotent and cheap: rows are built once per ship and reused, so a
        repeated push costs a dict lookup per contact.
        """
        from engine.appc.ships import ShipClass
        self._contacts = tuple(s for s in ships if isinstance(s, ShipClass))
        for ship in self._contacts:
            if ship not in self._row_cache:
                self.RebuildShipMenu(ship)

    def _rows(self) -> list:
        """The projection: cached rows for the current contacts, in order.

        Defensive on both attributes: `_children` is a property, so anything
        that reads it during base-class construction would land here before
        __init__ finishes. TGObject.__getattr__ raises for _private names, so
        getattr-with-default is the guard that works.
        """
        cache = getattr(self, "_row_cache", None)
        contacts = getattr(self, "_contacts", None)
        if not cache or not contacts:
            return []
        return [cache[s] for s in contacts if s in cache]

    @property
    def _children(self) -> list:
        # STMenu.__init__ assigns self._children = []; the setter below absorbs
        # that. Everything that reads children — base class, SDK, our CEF views
        # — goes through this, so nothing can bypass the projection.
        return self._rows()

    @_children.setter
    def _children(self, value) -> None:
        # Membership is derived; there is nothing to store. STMenu.__init__ and
        # KillChildren both assign here and both are correctly no-ops.
        pass

    # ── Sibling traversal required by CycleTarget ──
    def GetFirstChild(self):
        rows = self._rows()
        return rows[0] if rows else None

    def GetLastChild(self):
        rows = self._rows()
        return rows[-1] if rows else None

    def GetNextChild(self, child):
        rows = self._rows()
        try:
            i = rows.index(child)
        except ValueError:
            return None
        return rows[i + 1] if i + 1 < len(rows) else None

    def GetPrevChild(self, child):
        rows = self._rows()
        try:
            i = rows.index(child)
        except ValueError:
            return None
        return rows[i - 1] if i > 0 else None

    def GetNumChildren(self) -> int:
        return len(self._rows())

    def GetObjectEntry(self, ship):
        """Return the listed STSubsystemMenu whose GetShip() is ``ship``.

        Returns None for a ship that is not a current contact even if a row is
        cached, so this agrees with the listing by construction — SDK
        CycleTarget must never be able to select a contact the panel drops.
        """
        if ship not in self._contacts:
            return None
        return self._row_cache.get(ship)
```

Then change `ClearTargetList` and `RebuildShipMenu`:

```python
    def ClearTargetList(self) -> None:
        """SDK: Multiplayer/MissionShared.py:353.

        Under a derived list this can only drop the cached rows — the contents
        come back on the next push if those ships are still present. That is
        correct for its real caller (MissionShared.ClearShips deletes the ships
        immediately afterwards, so the next push is empty anyway).
        """
        self._row_cache.clear()
        self._contacts = ()
```

```python
    def RebuildShipMenu(self, ship) -> None:
        """Create or refresh the cached row for ``ship``.

        SDK callsites: MissionLib.py:2200, 2225 (HideSubsystems /
        ShowSubsystems). It no longer decides whether the ship is LISTED —
        set_contacts does that — so a mission may refresh a ship in another
        set harmlessly.

        Silently no-ops for non-ships: TGObject.__getattr__ returns a truthy
        _Stub for any missing attribute, so hasattr cannot reject the
        bridge-interior ObjectClass, and walking its subsystems would loop
        forever. The isinstance check rejects non-ships at the boundary.
        """
        import App as _App
        from engine.appc.ships import ShipClass
        if ship is None or not isinstance(ship, ShipClass):
            return
        row = self._row_cache.get(ship)
        if row is None:
            # Label uses the localized display name ("USS Sovereign"), not the
            # raw identifier ("player"). Affiliation/group lookups still key
            # off GetName().
            row = STSubsystemMenu(ship, ship.GetDisplayName())
            self._row_cache[ship] = row
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            self._add_subsystem_row(row, sub)
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)
```

Finally, `RebuildShipMenus` becomes a push (keeping its signature, since tests
and `host_loop` call it with a set):

```python
    def RebuildShipMenus(self, source_set=None) -> None:
        """Bulk refresh from a set. Never called from SDK Python.

        Retained for the existing callers; it now pushes membership rather than
        appending children, so its effect is the same as set_contacts over that
        set's ships.
        """
        import App as _App
        from engine.appc.ships import ShipClass
        if source_set is None:
            source_set = _App.g_kSetManager.GetSet("bridge")
        if source_set is None:
            return
        self.set_contacts([o for o in source_set.GetObjectList()
                           if isinstance(o, ShipClass)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_target_menu_derived_children.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the target-list suite and fix fallout**

Run: `uv run pytest tests/unit -k "target" tests/integration -k "target" -v`

Expected fallout, all legitimate and to be updated in this commit:
- Tests that call `menu.AddChild(row)` directly and then assert on children — membership is now pushed, so switch them to `set_contacts([ship])`.
- Tests asserting `ClearTargetList` leaves a previously-added row retrievable — it no longer does.
- `tests/unit/test_target_menu_bridge_subscription.py` — the subscription path is retired in Task 5; leave it failing here **only if** it fails solely on membership assertions, and fix it there. If it fails for any other reason, stop and report.

Do not delete a failing test to make the suite green. Update it to the new
surface, or report it as BLOCKED.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/target_menu.py tests/unit/test_target_menu_derived_children.py
git commit -m "feat(contacts): STTargetMenu children derive from a row cache + pushed contacts"
```

Include in this commit any test files you updated in Step 5, staged by explicit path.

---

### Task 5: Drive it from the host loop, retire the subscription

**Files:**
- Modify: `engine/host_loop.py:5810-5837` (`_wire_target_menu_to_player_set`), `:6991-6998` (per-frame block)
- Modify: `engine/appc/target_menu.py:301-332` (remove `_on_bridge_set_event`, `wire_to_bridge_set`, `unwire_from_bridge_set`)
- Modify: `engine/appc/warp.py:138-163` (`_clear_all_targets`)
- Modify: `tests/unit/test_target_menu_bridge_subscription.py` (retire — see Step 5)
- Test: `tests/integration/test_target_list_follows_player_system.py`

**Interfaces:**
- Consumes: `perception.contacts_for` (Task 3), `STTargetMenu.set_contacts` (Task 4)
- Produces: nothing new

- [ ] **Step 1: Write the failing regression test**

This is the reported bug, both directions. Create
`tests/integration/test_target_list_follows_player_system.py`:

```python
"""The target list tracks the player's current system, both directions.

Reported live 2026-08-16: ships loaded in QuickBattle after warping to another
system appeared in the target list despite being spawned into the set the
player had left.
"""
import App
from engine.appc import contact_index
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def _menu():
    App._reset_target_menu_singleton()
    return App.STTargetMenu_CreateW("Targets")


def _pump(menu, player):
    """One frame of the host loop's contact push."""
    menu.set_contacts(contacts_for(player))


def test_ships_spawned_into_the_departed_system_do_not_appear():
    contact_index.reset()
    menu = _menu()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")

    deep_space.AddObjectToSet(player, "player")
    _pump(menu, player)

    # Warp: the player moves to Vesuvi.
    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    _pump(menu, player)

    # QuickBattle spawns into g_pSet, still pointing at Deep Space.
    deep_space.AddObjectToSet(_ship("Galor"), "Galor")
    _pump(menu, player)

    assert menu.GetNumChildren() == 0


def test_ships_already_in_the_destination_system_do_appear():
    """The other half of the same fault: the old subscription stayed bound to
    the departed set, so arriving contacts got no rows at all."""
    contact_index.reset()
    menu = _menu()
    deep_space, vesuvi = SetClass(), SetClass()
    player = _ship("player")
    resident = _ship("Sovereign")

    deep_space.AddObjectToSet(player, "player")
    vesuvi.AddObjectToSet(resident, "Sovereign")
    _pump(menu, player)
    assert menu.GetNumChildren() == 0

    deep_space.RemoveObjectFromSet("player")
    vesuvi.AddObjectToSet(player, "player")
    _pump(menu, player)

    assert menu.GetNumChildren() == 1
    assert menu.GetFirstChild().GetShip() is resident


def test_warp_transit_empties_the_list_with_no_explicit_clear():
    """Mid-warp the player is alone in _WarpTransit, so the list empties
    itself — this is the test of whether the derived model is right."""
    from engine.appc.warp import _WARP_TRANSIT_SET_NAME
    contact_index.reset()
    menu = _menu()
    deep_space = SetClass()
    transit = SetClass()
    transit.SetName(_WARP_TRANSIT_SET_NAME)
    player = _ship("player")

    deep_space.AddObjectToSet(player, "player")
    deep_space.AddObjectToSet(_ship("Galor"), "Galor")
    _pump(menu, player)
    assert menu.GetNumChildren() == 1

    deep_space.RemoveObjectFromSet("player")
    transit.AddObjectToSet(player, "player")
    _pump(menu, player)

    assert menu.GetNumChildren() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_target_list_follows_player_system.py -v`
Expected: these should already PASS, because Tasks 3–4 built the mechanism. If any fail, stop — the mechanism is wrong and the remaining steps would paper over it.

If they pass, this test is the guard for the wiring changes below: it must stay green through Steps 3–6.

**Know what this test does not cover.** `_pump` calls `contacts_for` and `set_contacts` directly, so it proves the *mechanism* is right but never executes the host-loop call site added in Step 3. Nothing headless can — the host loop needs a renderer and a live SDK boot. That gap is exactly what the live verification checklist at the end of this plan is for. Do not treat a green run here as evidence the wiring works in-game.

- [ ] **Step 3: Push contacts from the host loop**

In `engine/host_loop.py`, replace the per-frame block at `:6991-6998`. It
currently resolves `_player_set` and calls `update_target_list_visibility`.
Keep the visibility call — stage 1 changes no detectability — and add the push
before it:

```python
                # Contact membership — push the player's current system every
                # frame. Worst case this is one frame stale; it can never be
                # permanently wrong, which is what the old set-subscription was
                # (bound at mission load, never rebound on warp).
                _menu = App.STTargetMenu_GetTargetMenu()
                _game = Game_GetCurrentGame()
                _player = _game.GetPlayer() if _game is not None else None
                if _menu is not None and _player is not None:
                    from engine.appc.perception import contacts_for
                    _menu.set_contacts(contacts_for(_player))

                # Sensor-visibility update — flip per-row IsVisible based on
                # range from the player. TargetListView filters rows where
                # IsVisible() == 0. Unchanged in stage 1; stage 3 folds this
                # into the perception query and deletes the module.
                _player_set = getattr(_player, "_containing_set", None) if _player is not None else None
                if _menu is not None and _player is not None and _player_set is not None:
                    update_target_list_visibility(
                        _menu, _player_set.GetObjectList(), _player
                    )
```

- [ ] **Step 4: Retire the set subscription**

In `engine/host_loop.py`, `_wire_target_menu_to_player_set` (`:5810`) loses its
subscription and bulk rebuild, keeping only singleton creation:

```python
def _ensure_target_menu(controller) -> None:
    """Create the target-menu singleton if the mission load cleared it.

    Membership is no longer wired here. It is derived every frame from the
    player's containing set (see the contact push in the host loop), so there
    is no subscription to bind and nothing to rebind on warp — which is exactly
    the fault this replaced: the old wiring bound to one set at mission load
    and never rebound, so ships spawned into a departed system kept getting
    rows while the destination system got none.
    """
    import App as _App
    if _App.STTargetMenu_GetTargetMenu() is None:
        _App.STTargetMenu_CreateW("Targets")
```

Update its call site at `:6452` to `_ensure_target_menu(controller)`.

In `engine/appc/target_menu.py`, delete `_on_bridge_set_event`,
`wire_to_bridge_set` and `unwire_from_bridge_set` (`:301-332`) entirely. Then
find and remove the `unwire_from_bridge_set` call in `reset_sdk_globals`:

Run: `grep -rn "wire_to_bridge_set\|unwire_from_bridge_set\|_on_bridge_set_event" engine/ tests/`

Every remaining reference must go. If a call site is not obviously removable,
stop and report BLOCKED rather than guessing.

- [ ] **Step 5: Retire the subscription test file**

`tests/unit/test_target_menu_bridge_subscription.py` tests a mechanism that no
longer exists. Its behavioural intent — "a ship entering the player's world
gets a row, a ship leaving loses it" — is now covered by
`test_target_list_follows_player_system.py` and
`test_target_menu_derived_children.py`.

Delete the file:

```bash
git rm tests/unit/test_target_menu_bridge_subscription.py
```

This is a deletion of tests for deleted surface, not orphaning behaviour. Do
not delete any other test file in this task.

- [ ] **Step 6: Drop the warp target clear**

In `engine/appc/warp.py`, `_clear_all_targets` keeps clearing the player's
target and subsystem lock but no longer touches the list:

```python
def _clear_all_targets(ship) -> None:
    """Drop the player's target + subsystem lock the instant warp engages.

    The target LIST needs no clearing: mid-warp the player is alone in the
    _WarpTransit set, so the derived membership is empty by construction and
    repopulates from the destination on arrival. Fail-open: a failure here
    never blocks the warp.
    """
    try:
        if ship is not None:
            if hasattr(ship, "SetTarget"):
                ship.SetTarget(None)
            if hasattr(ship, "SetTargetSubsystem"):
                ship.SetTargetSubsystem(None)
    except Exception:
        pass
    try:
        from engine.appc.target_menu import STTargetMenu_GetTargetMenu
        menu = STTargetMenu_GetTargetMenu()
        if menu is not None:
            menu.ClearPersistentTarget()
    except Exception:
        pass
```

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failure absent from `tests/known_failures.txt`. If the gate names a
new failure, fix it or report BLOCKED — do not baseline it.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py engine/appc/target_menu.py engine/appc/warp.py \
        tests/integration/test_target_list_follows_player_system.py
git commit -m "fix(contacts): target list follows the player's system, not one bound set

Fixes ships spawned into a departed system appearing in the target list
after warp, and the inverse — contacts in the destination system getting
no rows because the subscription stayed bound to the set the player left.

Membership is now derived every frame from the player's containing set,
so warp needs no target-list handling at all."
```

---

### Task 6: Object-level `SetTargetable` / `IsTargetable`

**Files:**
- Modify: `engine/appc/objects.py:75-100` (`__init__` defaults), `:155-200` (accessors, beside the hailable/scannable pair)
- Modify: `engine/appc/perception.py` (apply the gate)
- Test: `tests/unit/test_object_targetable.py`

**Interfaces:**
- Consumes: `contacts_for` from Task 3
- Produces:
  - `ObjectClass.SetTargetable(value) -> None`
  - `ObjectClass.IsTargetable() -> int`
  - `contacts_for` now excludes ships whose `IsTargetable()` is 0

**Why this belongs here:** `ShipClass.SetTargetable` is real published Appc surface (`sdk/Build/scripts/App.py:5480`) but is unimplemented, so it reaches `TGObject.__getattr__` and silently no-ops. `docs/stub_heatmap.md:175` records it live — rank 161, 18 hits. Ten-plus SDK missions use it to hide a contact until a reveal beat (`E3M1.py:1695`, `E3M2.py:3049`, `E6M4.py:1932`, `E6M2.py:746`, `E5M2.py:239`, `E3M5.py:2029`, plus the E2M1/Belaruz4/Cebalrai1 asteroid fields). Every one of those ships is currently still targetable.

**No change broadcast.** BC defines `ET_HAILABLE_CHANGE` and `ET_SCANNABLE_CHANGE` but no targetable equivalent — verified against `sdk/Build/scripts/App.py`. Those two exist because the Hail and Science menus are imperatively maintained button lists needing a rebuild signal; BC's target list is engine-built and re-reads the flag. Inventing an event would be unfaithful and pointless.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_object_targetable.py`:

```python
"""Object-level targetable — missions hide a contact until a reveal beat."""
from engine.appc import contact_index
from engine.appc.objects import ObjectClass
from engine.appc.perception import contacts_for
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass()
    s.SetName(name)
    return s


def test_objects_are_targetable_by_default():
    """The vast majority of SDK ships never touch the flag, so the default
    must be the one that makes targeting work without opting in — the same
    reasoning that settled _scannable."""
    assert ObjectClass().IsTargetable() == 1


def test_ships_are_targetable_by_default():
    assert _ship("Galor").IsTargetable() == 1


def test_set_targetable_zero_clears_the_flag():
    ship = _ship("Kessok")
    ship.SetTargetable(0)
    assert ship.IsTargetable() == 0


def test_set_targetable_round_trips():
    ship = _ship("Kessok")
    ship.SetTargetable(0)
    ship.SetTargetable(1)
    assert ship.IsTargetable() == 1


def test_sdk_false_constant_is_accepted():
    """E3M1.py:1695 passes FALSE, E6M4.py:1932 passes 0 — both must work."""
    ship = _ship("Amagon")
    ship.SetTargetable(False)
    assert ship.IsTargetable() == 0


def test_non_targetable_ship_is_not_a_contact():
    contact_index.reset()
    pSet = SetClass()
    player, hidden = _ship("player"), _ship("Kessok")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(hidden, "Kessok")
    hidden.SetTargetable(0)

    assert contacts_for(player) == ()


def test_revealing_a_ship_makes_it_a_contact_again():
    """E6M4.py:2094 flips it back on the reveal beat. Because membership is
    derived, the next query picks it up with no rebuild and no event."""
    contact_index.reset()
    pSet = SetClass()
    player, hidden = _ship("player"), _ship("Kessok")
    pSet.AddObjectToSet(player, "player")
    pSet.AddObjectToSet(hidden, "Kessok")
    hidden.SetTargetable(0)
    assert contacts_for(player) == ()

    hidden.SetTargetable(1)

    assert contacts_for(player) == (hidden,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_object_targetable.py -v`
Expected: FAIL — `IsTargetable()` returns a `_Stub`, so `== 1` is False

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/objects.py`, add to `ObjectClass.__init__` beside `_hailable`
and `_scannable`:

```python
        # Whether this object may be targeted at all. Default True: across the
        # SDK, SetTargetable(0) is only ever used to narratively hide a specific
        # ship until a reveal beat (E3M1's Amagon, E3M2's Warbird + Kessok,
        # E6M4's Kessok + Keldon, E6M2's probe, E5M2's outpost, E3M5's Gon
        # device, and several asteroid fields), and the same ships are
        # SetTargetable(1)'d back on reveal. The overwhelming majority of ships
        # never touch it, which only makes sense if the engine default is
        # targetable — the same argument that settled _scannable above. Eager
        # init so IsTargetable reads a real bool rather than a _Stub.
        self._targetable: bool = True
```

Add the accessors beside the hailable/scannable pair:

```python
    # ── Targetable state ──────────────────────────────────────────────────────
    # BC's ObjectClass::IsTargetable / ShipClass::IsTargetable are real published
    # surface (sdk/Build/scripts/App.py:3924, :5480). Unlike hailable/scannable
    # there is NO ET_TARGETABLE_CHANGE in BC: the Hail and Science menus are
    # imperatively maintained button lists that need a rebuild signal, whereas
    # the target list is engine-built and re-reads the flag. Ours is derived for
    # the same reason, so a reveal is picked up by the next query.
    def SetTargetable(self, value) -> None:
        self._targetable = bool(value)

    def IsTargetable(self) -> int:
        return 1 if self._targetable else 0
```

In `engine/appc/perception.py`, apply the gate:

```python
def contacts_for(observer) -> tuple:
    """Ships in *observer*'s containing set that it may target, excluding
    *observer* itself.

    Empty when there is no observer or it is in no set — which is also what
    makes warp self-correcting: mid-warp the player sits alone in the
    _WarpTransit set, so the list empties without anyone clearing it.

    The targetable gate is the mission's authored flag (SetTargetable), read
    through to the object rather than stored here: the mission owns it and
    flips it on reveal beats, and a copy would go stale on any missed write.
    """
    if observer is None:
        return ()
    pSet = observer.GetContainingSet() if hasattr(observer, "GetContainingSet") else None
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()
    return tuple(
        s for s in contact_index.ships_in(pSet)
        if s is not observer and s.IsTargetable()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_object_targetable.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: no failure absent from `tests/known_failures.txt`.

Watch specifically for asteroid tests: `tests/unit/test_target_list_inert_objects.py` covers hardpoints that call `SetTargetable(0)` on *subsystems*. Those are `ShipSubsystem.SetTargetable`, a different method on a different class, and must be unaffected. If they change behaviour, the new accessor is shadowing the subsystem one — stop and report.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/objects.py engine/appc/perception.py tests/unit/test_object_targetable.py
git commit -m "feat(contacts): implement object-level SetTargetable/IsTargetable

Real Appc surface (App.py:3924, :5480) that was unimplemented, so it hit
TGObject.__getattr__ and silently no-opped — stub_heatmap rank 161, 18
live hits. Ten-plus SDK missions use it to hide a contact until a reveal
beat; every one of those ships was still targetable.

No ET_TARGETABLE_CHANGE: BC has none, because its target list re-reads
the flag rather than being imperatively rebuilt. Ours does too."
```

---

## Verification

After Task 6, confirm the whole stage:

- [ ] `scripts/check_tests.sh` passes with no failure absent from `tests/known_failures.txt`
- [ ] `grep -rn "wire_to_bridge_set\|unwire_from_bridge_set\|_on_bridge_set_event" engine/ tests/` returns nothing
- [ ] `git log --oneline main..HEAD` shows six commits plus the spec

**Live verification is required before this counts as done.** Headless tests cannot see the real QuickBattle path, the CEF target panel, or the SDK's `CycleTarget`. Mark verifies in-game:

1. Load QuickBattle, add an enemy, confirm it is listed and targetable.
2. Set Course to another system and warp. Confirm the target list empties.
3. Add enemies from the QuickBattle setup panel. **Confirm they do NOT appear** — this is the reported bug.
4. Warp back to Deep Space. Confirm the previously-added ships DO appear.
5. Tab through targets and confirm cycling matches the visible list.
6. Confirm the radar still shows contacts and still respects its own zoom range.

## Out of scope

Deferred to the stage 3–4 plan, recorded so they are not lost:

- Detectability consolidation onto `can_detect`; deleting `engine/ui/target_list_visibility.py`
- Distance computed once and carried on the contact record; the `GetTranslate()` vs `GetWorldLocation()` split between `reticle_text` and `ship_display_panel`
- Nebula list hoisted to per-set state
- Cloak at 1% of effective sensor range; nebula concealment reaching the UI; the fidelity toggle
- `FALLBACK_RANGE_GU = 30000` being 15× a Galaxy's real sensor range
- Hail and scan adopting the shared query
