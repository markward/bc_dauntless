"""Quick Battle is a simulation: when it ends, every REAL object in the
battle region is as it was before (spec 2026-10-25-home-stations §7).

Real = owned (engine/systems/owners.py, whenever it appeared), or unowned and
either present before StartSimulation2 or built by the battle region's own
`Initialize` inside ChangeRegion. Everything else (the ships GenerateShips
made) belongs to the battle.

- `ChangeRegion` moves EVERY ship in the player's set into the new battle
  region; the wrapper puts each owned object back into the set it was in, at
  the pose it had. After the change it snapshots every real damageable object
  in the battle set as a `Record`.
- `EndSimulation` deletes every damageable object except the player. After
  BC's own, the wrapper un-flags each real object the battle left untouched,
  and rebuilds each one it changed or destroyed (an owned object through its
  owner), then puts back its pre-battle condition.

`install(qb)` replaces module attributes, so every SDK caller that reaches the
function through its module global (StartSimulation2 calls ChangeRegion,
RestartSimulation calls EndSimulation; ET_PRELOAD_DONE resolves
StartSimulation2 by name at dispatch) gets the wrapper without an SDK edit.
Each wrapper carries `_dauntless_sim_restore_orig`; install walks every
`_dauntless_*_orig` link, so a wrapper of ours under another module's (spawn's
EndSimulation hook) is still found and never installed twice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from engine.appc.math import TGMatrix3, TGPoint3
from engine.systems import owners

_log = logging.getLogger(__name__)

_MARK = "_dauntless_sim_restore_orig"

_SHIELD_FACES = 6

# Condition values closer than this count as unchanged.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Record:
    """One real object as the battle found it; what an owner's
    `rebuild(old, record)` receives. `pset` is the set OBJECT (BC may rename
    it `<name>Dupe`), `script` the ship script's leaf name."""
    obj: object
    pset: object
    name: str
    script: str
    location: TGPoint3
    rotation: TGMatrix3
    scale: float
    condition: dict
    owner: str | None
    key: object


# {id: object} of every object in every set when StartSimulation2 began. The
# objects are held, not just their ids, so a deleted one's id can never be
# recycled by a battle ship and pass for it.
_pre_sim: dict = {}

# The real objects of the running battle; [] when none.
_snapshot: list = []


def reset() -> None:
    """Forget the running battle (mission swap, test teardown)."""
    _pre_sim.clear()
    _snapshot.clear()


# ── A ship's condition ───────────────────────────────────────────────────────

def _bound(obj, name):
    """`obj.name()` when the CLASS defines it, else None: an instance getattr
    would answer an unknown name with a TGObject stub."""
    get = getattr(type(obj), name, None)
    return get(obj) if get is not None else None


def condition_of(ship) -> dict:
    """Every subsystem's condition (iter_subsystems order), the six shield
    faces and each torpedo slot's rounds; [] for a part the ship lacks, and
    None for an empty torpedo slot."""
    from engine.appc.subsystems import iter_subsystems
    shields = _bound(ship, "GetShields")
    torps = _bound(ship, "GetTorpedoSystem")
    ammo = []
    if torps is not None:
        for slot in range(torps.GetNumAmmoTypes()):
            kind = torps.GetAmmoType(slot)
            ammo.append(None if kind is None else kind.GetAvailable())
    return {
        "subsystems": [s.GetCondition() for s in iter_subsystems(ship)],
        "shields": ([] if shields is None else
                    [shields.GetCurShields(f) for f in range(_SHIELD_FACES)]),
        "ammo": ammo,
    }


def apply_condition(ship, cond) -> None:
    """Write `cond` (condition_of of the same kind of ship) back."""
    from engine.appc.subsystems import iter_subsystems
    for sub, value in zip(iter_subsystems(ship), cond["subsystems"]):
        sub.SetCondition(value)
    shields = _bound(ship, "GetShields")
    if shields is not None:
        for face, value in enumerate(cond["shields"]):
            shields.SetCurShields(face, value)
    torps = _bound(ship, "GetTorpedoSystem")
    if torps is not None:
        for slot, value in enumerate(cond["ammo"]):
            kind = torps.GetAmmoType(slot)
            if kind is not None and value is not None:
                kind.SetAvailable(value)


def _owned_in_player_set() -> list:
    """(object, its set, location copy, rotation copy) for every owned object
    in the player's set; [] with no player or set."""
    import App
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    pSet = player.GetContainingSet() if player is not None else None
    if pSet is None:
        return []
    out = []
    for obj in pSet.GetObjectList():
        if owners.owner_of(obj) is None:
            continue
        loc = obj.GetWorldLocation()
        rot = TGMatrix3()
        rot.set_from_tuple(obj.GetWorldRotation().as_tuple())
        out.append((obj, pSet, TGPoint3(loc.x, loc.y, loc.z), rot))
    return out


def _proximity(pSet):
    get = getattr(type(pSet), "GetProximityManager", None)
    return get(pSet) if get is not None else None


def _leave(obj, now, name) -> None:
    """Take `obj` out of `now` and out of its proximity index: BC's loop
    UpdateObject'ed it into the battle set's manager, and leaving the set
    does not drop that entry."""
    if now.GetObject(name) is obj:
        now.RemoveObjectFromSet(name)
    pm = _proximity(now)
    if pm is not None:
        pm.RemoveObject(obj)


def _return_home(obj, home, name, loc, rot) -> None:
    home.AddObjectToSet(obj, name)
    obj.SetTranslate(loc)
    obj.SetMatrixRotation(rot)
    obj.UpdateNodeOnly()
    pm = _proximity(home)
    if pm is not None:
        pm.UpdateObject(obj)


def _put_back(records) -> None:
    """Every record gets its own try, and leaving the wrong set is tried
    apart from going home: one bad record, or a failure while leaving, can
    never strand an object in no set."""
    for obj, home, loc, rot in records:
        try:
            now = obj.GetContainingSet()
            if now is home:
                continue
            name = obj.GetName()
        except Exception:  # noqa: BLE001 - the other records still go home
            _log.exception("quickbattle: reading an owned object failed")
            continue
        if now is not None:
            try:
                _leave(obj, now, name)
            except Exception:  # noqa: BLE001 - still send it home
                _log.exception("quickbattle: %s did not leave %s", name,
                               now.GetName())
        try:
            _return_home(obj, home, name, loc, rot)
        except Exception:  # noqa: BLE001 - the other records still go home
            _log.exception("quickbattle: %s did not go back to %s", name,
                           home.GetName())


# ── The snapshot ─────────────────────────────────────────────────────────────

def _every_object() -> dict:
    """{id: object} for every object in every set."""
    import App
    out = {}
    for pSet in list(App.g_kSetManager._sets.values()):
        for obj in list(pSet._objects.values()):
            out[id(obj)] = obj
    return out


def _record(obj, pSet) -> Record:
    owned = owners.owner_of(obj)
    loc = obj.GetWorldLocation()
    rot = TGMatrix3()
    rot.set_from_tuple(obj.GetWorldRotation().as_tuple())
    return Record(
        obj=obj, pset=pSet, name=obj.GetName(),
        script=str(obj.GetScript()).rsplit(".", 1)[-1],
        location=TGPoint3(loc.x, loc.y, loc.z), rotation=rot,
        scale=float(obj.GetScale()), condition=condition_of(obj),
        owner=owned[0].name if owned is not None else None,
        key=owned[1] if owned is not None else None)


def _take_snapshot(qb, pre_change: dict) -> None:
    """Record every real damageable object in the battle set, the player
    excepted: owned, present before the battle, or built by ChangeRegion (the
    region's Initialize). One bad object never stops the rest."""
    import App
    _snapshot.clear()
    pSet = qb.__dict__.get("g_pSet")
    if pSet is None:
        return
    player = App.Game_GetCurrentGame().GetPlayer()
    for obj in pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT):
        if obj is player:
            continue
        real = (owners.owner_of(obj) is not None
                or _pre_sim.get(id(obj)) is obj
                or pre_change.get(id(obj)) is not obj)
        if not real:
            continue
        try:
            _snapshot.append(_record(obj, pSet))
        except Exception:  # noqa: BLE001 - the other objects are still recorded
            _log.exception("quickbattle: recording a real object failed")


# ── The restore ──────────────────────────────────────────────────────────────

def _same(a: dict, b: dict) -> bool:
    for key in ("subsystems", "shields", "ammo"):
        x, y = a[key], b[key]
        if len(x) != len(y):
            return False
        for u, v in zip(x, y):
            if u is None or v is None:
                if u is not v:
                    return False
            elif abs(u - v) > _TOLERANCE:
                return False
    return True


def _untouched(record: Record) -> bool:
    from engine.appc import ship_death
    old, pSet = record.obj, record.pset
    return (not ship_death._out_of_action(old)
            and old.GetContainingSet() is pSet
            and pSet.GetObject(record.name) is old
            and _same(condition_of(old), record.condition))


def _rebuild(record: Record) -> None:
    """Replace a changed or destroyed real object with a fresh one in its
    pre-battle condition; the owner builds an owned one."""
    from engine.appc import ship_death
    from engine.appc.objects import broadcast_object_deleted
    old, pSet = record.obj, record.pset
    ship_death.forget(old)
    if pSet.GetObject(record.name) is old:
        pSet.RemoveObjectFromSet(record.name)
        broadcast_object_deleted(old)
    owner = owners.get(record.owner) if record.owner is not None else None
    if record.owner is not None:
        new = owner.rebuild(old, record) if owner is not None else None
    else:
        import loadspacehelper
        new = loadspacehelper.CreateShip(record.script, pSet, record.name,
                                         "", 0, 0)
        if new is not None:
            new.SetTranslate(record.location)
            new.SetMatrixRotation(record.rotation)
            if record.scale != 1.0:
                new.SetScale(record.scale)
            new.UpdateNodeOnly()
    if new is None:
        print(f"[sim-restore] {record.name} was not rebuilt "
              f"(owner {record.owner!r})", flush=True)
        return
    apply_condition(new, record.condition)
    if owner is not None:
        owner.after_rebuild(new, record)


def _restore_after_end(qb) -> None:
    """After BC's EndSimulation: owned objects the battle never recorded (they
    appeared mid-battle) are un-flagged; each record is un-flagged when the
    battle left it alone, else rebuilt. Each record has its own try."""
    records = list(_snapshot)
    reset()
    recorded = {id(r.obj) for r in records}
    pSet = qb.__dict__.get("g_pSet")
    if pSet is not None:
        try:
            for obj in pSet.GetObjectList():
                if id(obj) not in recorded and owners.owner_of(obj) is not None:
                    obj.SetDeleteMe(0)
        except Exception:  # noqa: BLE001 - the records are still restored
            _log.exception("quickbattle: keeping owned objects failed")
    for record in records:
        try:
            if _untouched(record):
                record.obj.SetDeleteMe(0)
            else:
                _rebuild(record)
        except Exception:  # noqa: BLE001 - the other records are still restored
            _log.exception("quickbattle: restoring %s failed", record.name)


# ── Installing ───────────────────────────────────────────────────────────────

def _chain(fn):
    """`fn`, then each function it wraps, following any `_dauntless_*_orig`
    link (ours or another module's)."""
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        yield fn
        links = getattr(fn, "__dict__", {})
        fn = next((v for k, v in links.items()
                   if k.startswith("_dauntless_") and k.endswith("_orig")),
                  None)


def _wrapper_count(fn) -> int:
    return sum(1 for f in _chain(fn) if _MARK in getattr(f, "__dict__", {}))


def _wrap(qb, name, make) -> bool:
    current = qb.__dict__.get(name)
    if current is None or _wrapper_count(current):
        return False
    wrapper = make(current)
    setattr(wrapper, _MARK, current)
    setattr(qb, name, wrapper)
    return True


def _make_start_simulation2(orig):
    def StartSimulation2(*args):
        try:
            _pre_sim.update(_every_object())
        except Exception:  # noqa: BLE001 - never stop BC's start
            _log.exception("quickbattle: listing pre-battle objects failed")
        try:
            return orig(*args)
        finally:
            _pre_sim.clear()
    return StartSimulation2


def _make_change_region(qb):
    def make(orig):
        def ChangeRegion(*args):
            try:
                records = _owned_in_player_set()
            except Exception:  # noqa: BLE001 - never stop BC's region change
                _log.exception("quickbattle: recording owned objects failed")
                records = []
            try:
                pre_change = _every_object()
            except Exception:  # noqa: BLE001 - never stop BC's region change
                _log.exception("quickbattle: listing objects failed")
                pre_change = {}
            try:
                return orig(*args)
            finally:
                # Also when BC's ChangeRegion raises partway: whatever it
                # already moved still goes home, and the exception still
                # propagates.
                _put_back(records)
                if qb.__dict__.get("bInSimulation"):
                    try:
                        _take_snapshot(qb, pre_change)
                    except Exception:  # noqa: BLE001 - never stop the start
                        _log.exception("quickbattle: snapshot failed")
        return ChangeRegion
    return make


def _make_end_simulation(qb):
    def make(orig):
        def EndSimulation(*args):
            try:
                return orig(*args)
            finally:
                try:
                    _restore_after_end(qb)
                except Exception:  # noqa: BLE001 - never mask BC's end
                    _log.exception("quickbattle: restore failed")
        return EndSimulation
    return make


def install(qb) -> bool:
    """Wrap the Quick Battle module's functions; True when any wrapper was
    installed by this call."""
    installed = False
    installed |= _wrap(qb, "StartSimulation2", _make_start_simulation2)
    installed |= _wrap(qb, "ChangeRegion", _make_change_region(qb))
    installed |= _wrap(qb, "EndSimulation", _make_end_simulation(qb))
    return installed
