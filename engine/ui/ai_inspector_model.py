"""Pure introspection helpers for the developer AI-tree inspector.

``serialize_ai_tree`` recursively turns a live AI node (engine.appc.ai)
into a JSON-able nested dict that the CEF inspector renders.
``collect_all_ship_ai`` walks every live ship via engine.appc.ship_iter
and pairs each ship name with its serialized tree (None when the ship has
no AI).

Everything is defensive: an unexpected node shape (a half-built tree, a
custom AI subclass, a condition without a name) must never raise, because
this runs against arbitrary mission-built AI graphs while the sim is live.
Modeled on BC's AIActiveLogView.py socket monitor, rendered through the
existing CEF panel system instead.
"""
from __future__ import annotations

from typing import List, Optional

from engine.appc.ai import ArtificialIntelligence


# US_* status int -> display string. Anything off the map renders as the
# raw int so a future status value is still visible rather than swallowed.
_STATUS_NAMES = {
    ArtificialIntelligence.US_ACTIVE: "ACTIVE",
    ArtificialIntelligence.US_DONE: "DONE",
    ArtificialIntelligence.US_DORMANT: "DORMANT",
    ArtificialIntelligence.US_INVALID: "INVALID",
}


def _status_of(ai) -> str:
    """Map an AI node's status int to a display string.

    The AI base class stores status on ``_status`` (there is no GetStatus
    on ArtificialIntelligence — only on TGCondition); we read GetStatus()
    if present, else fall back to the attribute, defaulting to ACTIVE."""
    getter = getattr(ai, "GetStatus", None)
    if callable(getter):
        try:
            raw = getter()
        except Exception:
            raw = getattr(ai, "_status", ArtificialIntelligence.US_ACTIVE)
    else:
        raw = getattr(ai, "_status", ArtificialIntelligence.US_ACTIVE)
    return _STATUS_NAMES.get(raw, str(raw))


def _has_focus(ai) -> bool:
    try:
        return bool(ai.HasFocus())
    except Exception:
        return bool(getattr(ai, "_has_focus", False))


def _name_of(node, attr: str = "_name") -> str:
    getter = getattr(node, "GetName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return str(getattr(node, attr, ""))


def _condition_label(cond) -> str:
    """A condition's identity is its CLASS -- ConditionTorpedoReady and friends
    carry no name and no _name, so _name_of returns "" for every one of them.

    That is not cosmetic. An exported tree showing `conds=?:1, ?:0, ?:0, ?:0`
    tells you a gate is shut and nothing about WHICH input shut it, which is
    exactly the question when an AI has stopped engaging.
    """
    return _name_of(cond) or type(cond).__name__


def _plain_arg(val):
    """A condition argument as JSON: scalars verbatim, a point as [x, y, z],
    anything else as its type name (never the object, never a raise)."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    vec = _vec(val)
    if vec is not None:
        return vec
    if isinstance(val, (list, tuple)):
        return [_plain_arg(v) for v in val[:8]]
    return type(val).__name__


def _condition_entry(cond) -> dict:
    """One condition's identity, inputs and latched status.

    Every SDK condition is a ConditionScript, so the class says nothing; the
    script name does. Even that is not enough: RearTorpsReadyRearShieldOk and
    TorpsReadyAndNotInEnemyFiringArc both hold a ConditionTorpsReady, and only
    the direction argument says which tubes each one watches.
    """
    out = {"name": _condition_label(cond),
           "class": type(cond).__name__,
           "status": _condition_status(cond)}
    script = cond.__dict__.get("_class_name") if hasattr(cond, "__dict__") else None
    if isinstance(script, str) and script:
        out["script"] = script
        args = cond.__dict__.get("_args")
        if isinstance(args, tuple):
            out["args"] = [_plain_arg(a) for a in args]
    return out


def _condition_status(cond) -> int:
    getter = getattr(cond, "GetStatus", None)
    if callable(getter):
        try:
            return int(getter())
        except Exception:
            return 0
    return int(getattr(cond, "_status", 0))


def _is_dispatchable(ai) -> bool:
    """A PriorityListAI child is 'active' if it is neither DONE nor DORMANT."""
    raw = getattr(ai, "_status", ArtificialIntelligence.US_ACTIVE)
    return raw not in (ArtificialIntelligence.US_DONE,
                       ArtificialIntelligence.US_DORMANT)


def serialize_ai_tree(ai) -> dict:
    """Recursively serialize an AI node to a JSON-able dict.

    Common keys on every node: ``name``, ``type``, ``status``, ``focus``.
    Type-specific keys are added per the node's shape (children, conditions,
    contained AI, script module, etc.). getattr fallbacks keep an unexpected
    node shape from ever raising."""
    out = {
        "name": _name_of(ai),
        "type": type(ai).__name__,
        "status": _status_of(ai),
        "focus": _has_focus(ai),
    }

    # --- Cadence + bypass diagnostics -------------------------------------
    # Why these: a node can read ACTIVE and FOCUSED while its own Update has
    # not run for a long time, and the static status cannot show the
    # difference. Two mechanisms stop an Update without changing any status:
    #
    #  * the cadence gate -- game_time < _next_update_time
    #  * the non-interruptable bypass in _tick_preprocessing, which runs the
    #    CONTAINED ai and returns before the preprocessor's own Update
    #
    # Both present as "the tree looks fine but nothing is happening", which is
    # unfalsifiable without these numbers.
    nut = ai.__dict__.get("_next_update_time")
    if isinstance(nut, (int, float)):
        out["next_update_time"] = float(nut)
        try:
            import App
            now = float(App.g_kUtopiaModule.GetGameTime())
            out["due_in"] = float(nut) - now
            out["overdue"] = (float(nut) <= now)
        except Exception:
            pass
    interruptable = getattr(ai, "_interruptable", None)
    if interruptable is not None:
        out["interruptable"] = bool(interruptable)

    # ConditionalAI: conditions + single contained AI. Checked before the
    # generic _contained_ai branch so its conditions are captured.
    conditions = getattr(ai, "_conditions", None)
    if isinstance(conditions, list) and _has_attr_chain(ai, "_contained_ai"):
        out["conditions"] = [_condition_entry(c) for c in conditions]
        contained = getattr(ai, "_contained_ai", None)
        out["contained"] = serialize_ai_tree(contained) if contained is not None else None
        return out

    # PreprocessingAI / BuilderAI: single contained AI + preprocessing method.
    if _has_attr_chain(ai, "_contained_ai") and hasattr(ai, "_preprocessing_method"):
        out["preprocessing_method"] = getattr(ai, "_preprocessing_method", "") or ""
        out["preprocessor"] = _preprocessor_state(
            ai.__dict__.get("_preprocessing_instance"))
        contained = getattr(ai, "_contained_ai", None)
        out["contained"] = serialize_ai_tree(contained) if contained is not None else None
        return out

    # RandomAI: children via GetAIs(); mark _current_child.
    if hasattr(ai, "_current_child") and hasattr(ai, "GetAIs"):
        current = getattr(ai, "_current_child", None)
        kids = []
        for child in ai.GetAIs():
            if child is None:
                continue
            cd = serialize_ai_tree(child)
            cd["current"] = (child is current)
            kids.append(cd)
        out["children"] = kids
        return out

    # PriorityListAI: ._ais is a list of (priority, ai) tuples.
    # SequenceAI: ._ais is a list of plain AIs.
    children = getattr(ai, "_ais", None)
    if isinstance(children, list):
        if children and isinstance(children[0], tuple):
            # PriorityListAI — mark first dispatchable child as active.
            active_marked = False
            kids = []
            for prio, child in children:
                if child is None:
                    continue
                cd = serialize_ai_tree(child)
                cd["priority"] = int(prio)
                is_active = (not active_marked) and _is_dispatchable(child)
                cd["active"] = is_active
                if is_active:
                    active_marked = True
                kids.append(cd)
            out["children"] = kids
        else:
            # SequenceAI — include current_index.
            out["current_index"] = int(getattr(ai, "_current_index", 0))
            out["children"] = [
                serialize_ai_tree(child) for child in children if child is not None
            ]
        return out

    # PlainAI leaf: script module + next update time.
    if hasattr(ai, "_script_module"):
        out["script_module"] = getattr(ai, "_script_module", "") or ""
        out["next_update_time"] = float(getattr(ai, "_next_update_time", 0.0) or 0.0)
        return out

    return out


def _has_attr_chain(obj, name: str) -> bool:
    """hasattr but only counting real instance/class attrs.

    Some engine objects use __getattr__ stubs that make hasattr always
    True; AI nodes don't, but be explicit about what we probe so the
    branch selection above is unambiguous."""
    return name in getattr(obj, "__dict__", {}) or hasattr(type(obj), name)


def _preprocessor_state(inst) -> Optional[dict]:
    """The preprocessor INSTANCE's own scalar state.

    A PreprocessingAI can be ACTIVE, focused and updating on cadence while
    doing nothing at all, because the decision lives in the script instance
    rather than in the node. FireScript is the case in point: its Update
    returns early and fires NOTHING when ``lWeapons`` is empty
    (AI/Preprocessors.py), and ``bCallUsingWeaponTypeFunc`` is a one-shot latch
    whose broadcast is the only thing that ever sets ConditionUsingWeapon. Node
    status shows neither.

    Deliberately generic -- scalars verbatim, containers as lengths, callables
    and engine handles skipped -- so this reports whatever a preprocessor
    happens to carry instead of hard-coding FireScript's fields and going
    blind on the next one.
    """
    if inst is None:
        return None
    out = {"class": type(inst).__name__}
    for key, val in list(getattr(inst, "__dict__", {}).items()):
        if key.startswith("pCode") or callable(val):
            continue
        if isinstance(val, bool) or isinstance(val, (int, float, str)):
            out[key] = val
        elif isinstance(val, (list, tuple, dict, set)):
            out[key + "__len"] = len(val)
            # A weapon list is the field that matters; name what is in it.
            if key.lower().startswith("lweapon"):
                names = []
                for w in list(val)[:12]:
                    try:
                        names.append(_name_of(w) or type(w).__name__)
                    except Exception:
                        names.append("?")
                out[key + "__items"] = names
        elif val is None:
            out[key] = None
    return out


def _defence_report(ship) -> dict:
    """Alert level and per-facing shield state.

    Added for "AI ships randomly drop and raise shields in combat". Shields are
    raised by ALERT LEVEL, which the AlertLevel preprocessor owns -- and its
    LostFocus() restores the PREVIOUS level, so a node flickering on and off
    the active path lowers and raises shields with it. A single snapshot cannot
    show a flicker, but it can show WHICH of the two is moving: the alert level
    (AlertLevel is doing it) or the shield charge alone (PowerManagement, or
    the 0.5 s charge cadence, is).
    """
    out = {}
    try:
        out["alert_level"] = ship.GetAlertLevel()
    except Exception:
        out["alert_level"] = None
    try:
        shields = ship.GetShields()
        out["shields_up"] = bool(shields.IsOn()) if shields is not None else None
        if shields is not None:
            facings = []
            try:
                n = int(shields.GetNumShields())
            except Exception:
                n = 0
            for i in range(n):
                try:
                    facings.append(round(float(shields.GetSingleShieldPercentage(i)), 4))
                except Exception:
                    facings.append(None)
            out["shield_percent_by_facing"] = facings
    except Exception:
        out["shields_up"] = None
    return out


def _num(fn) -> Optional[float]:
    """Call a getter and keep the result only if it is a real number.

    TGObject.__getattr__ hands back a truthy _Stub for any missing method, and
    int(stub) is 0 -- which is how the first version of this report printed
    "ammo 0, can_fire True" for every ship. A value that is not a number is
    reported as None (unknown), never coerced.
    """
    if not callable(fn):
        return None
    try:
        v = fn()
    except Exception:
        return None
    if isinstance(v, bool):
        return float(v)
    return float(v) if isinstance(v, (int, float)) else None


def _vec(p) -> Optional[list]:
    """A TGPoint3-like as [x, y, z] rounded to 3 places, or None."""
    try:
        xyz = (p.x, p.y, p.z)
    except Exception:
        return None
    if not all(isinstance(c, (int, float)) for c in xyz):
        return None
    return [round(float(c), 3) for c in xyz]


def _flag(fn) -> Optional[bool]:
    v = _num(fn)
    return None if v is None else bool(v)


def _tube_report(tube) -> dict:
    from engine.appc.weapon_subsystems import _SLOT_LOADED
    cooling = [t for t in getattr(tube, "_reload_timers", []) if t != _SLOT_LOADED]
    ready, most = _num(tube.GetNumReady), _num(tube.GetMaxReady)
    return {
        "name": _name_of(tube),
        "num_ready": None if ready is None else int(ready),
        "max_ready": None if most is None else int(most),
        # Seconds of reload banked by the furthest-along cooling slot (power
        # scales the rate), or None when every slot is loaded.
        "reload_progress": round(max(cooling), 3) if cooling else None,
        "reload_delay": _num(tube.GetReloadDelay),
        "can_fire": _flag(tube.CanFire),
        "disabled": _flag(tube.IsDisabled),
        "direction": _vec(tube.GetDirection()),
    }


def _bank_report(bank) -> dict:
    return {
        "name": _name_of(bank),
        "charge": _num(bank.GetChargeLevel),
        "max_charge": _num(bank.GetMaxCharge),
        "min_firing_charge": _num(bank.GetMinFiringCharge),
        "can_fire": _flag(bank.CanFire),
        "firing": _flag(bank.IsFiring),
        "disabled": _flag(bank.IsDisabled),
    }


def _weapon_report(ship) -> dict:
    """What the weapon-readiness CONDITIONS are actually reading.

    An exported tree can show every fire gate DORMANT, or a torpedo gate
    latched ready, and give no hint whether that matches the weapons. So
    report the weapons themselves, per tube and per bank: "the AI will not
    fire" and "the weapons say they are not ready" are different findings with
    different fixes, and the tree alone cannot tell them apart.

    Reads the ship's four weapon systems by their own getters and classifies
    each child by isinstance against the engine classes -- never by probing
    for a method, which a stub always satisfies. ConditionTorpsReady latches
    its status from tube events, so a latched 1 beside tubes all at
    num_ready 0 is a stale gate, not a ready weapon.
    """
    from engine.appc.weapon_subsystems import (
        TorpedoSystem, TorpedoTube, _EnergyWeaponFireMixin)

    out = {"systems": [], "ready_banks": 0, "ready_tubes": 0}
    for getter in ("GetTorpedoSystem", "GetPhaserSystem",
                   "GetPulseWeaponSystem", "GetTractorBeamSystem"):
        try:
            system = getattr(ship, getter)()
        except Exception:
            continue
        if system is None or type(system).__name__ == "_Stub":
            continue
        entry = {"name": _name_of(system), "type": type(system).__name__,
                 "on": _flag(system.IsOn),
                 "disabled": _flag(system.IsDisabled)}
        children = []
        try:
            children = [system.GetChildSubsystem(i)
                        for i in range(int(system.GetNumChildSubsystems()))]
        except Exception:
            pass
        if isinstance(system, TorpedoSystem):
            entry["ammo_slot"] = _num(system.GetCurrentAmmoSlot)
            entry["ammo_slot"] = (None if entry["ammo_slot"] is None
                                  else int(entry["ammo_slot"]))
            ammo = []
            try:
                for slot in range(int(system.GetNumAmmoTypes())):
                    a = system.GetAmmoType(slot)
                    if a is None:
                        continue
                    avail = _num(a.GetAvailable)
                    ammo.append({"slot": slot, "name": _name_of(a, "_name") or a.GetAmmoName(),
                                 "available": None if avail is None else int(avail)})
            except Exception:
                pass
            entry["ammo"] = ammo
            entry["tubes"] = []
            for c in children:
                if isinstance(c, TorpedoTube):
                    try:
                        t = _tube_report(c)
                    except Exception:
                        continue
                    entry["tubes"].append(t)
                    if t["can_fire"]:
                        out["ready_tubes"] += 1
        else:
            entry["banks"] = []
            for c in children:
                if isinstance(c, _EnergyWeaponFireMixin):
                    try:
                        b = _bank_report(c)
                    except Exception:
                        continue
                    entry["banks"].append(b)
                    if b["can_fire"]:
                        out["ready_banks"] += 1
        out["systems"].append(entry)
    return out


def _bearing_deg(forward: list, delta: list) -> Optional[float]:
    """Angle in degrees between a unit forward and a world-space offset."""
    import math
    d = math.sqrt(sum(c * c for c in delta))
    if d <= 1e-9:
        return None
    dot = sum(f * c for f, c in zip(forward, delta)) / d
    return round(math.degrees(math.acos(max(-1.0, min(1.0, dot)))), 2)


def _motion_report(ship) -> Optional[dict]:
    """Where the ship is, how fast it is going and what it has been told to do.

    The tree says which maneuver is running; only this says what it is doing
    to the ship. "Holding" and "a slow tail-first rear torpedo run" have the
    same tree and very different numbers. All in game units (engine/units.py).
    """
    import math
    pos = _vec(ship.GetWorldLocation())
    if pos is None:
        return None
    out = {"position_gu": pos,
           "velocity_gups": _vec(ship.GetVelocityTG()),
           "forward": _vec(ship.GetWorldRotation().GetCol(1)),
           "angular_velocity": _vec(ship.GetAngularVelocityTG())}
    v = out["velocity_gups"]
    out["speed_gups"] = round(math.sqrt(sum(c * c for c in v)), 3) if v else None
    # The commanded speed (absolute GU/s -- SetImpulse scales the SDK's
    # fraction by max speed) beside what the ship is actually doing.
    sp = ship.__dict__.get("_speed_setpoint")
    out["speed_setpoint_gups"] = (round(float(sp[0]), 3)
                                  if isinstance(sp, tuple) and sp
                                  and isinstance(sp[0], (int, float)) else None)
    out["impulse_fraction"] = _num(getattr(ship, "GetImpulse", None))
    ies = ship.GetImpulseEngineSubsystem()
    out["max_speed_gups"] = _num(ies.GetMaxSpeed) if ies is not None else None
    return out


def _target_geometry(ship, target) -> Optional[dict]:
    """Distance (centre to centre), bearing off the nose and closing speed.

    bearing_deg is 0 dead ahead and 180 dead astern. closing_speed_gups is
    positive while the gap shrinks.
    """
    if target is None:
        return None
    a, b = _vec(ship.GetWorldLocation()), _vec(target.GetWorldLocation())
    if a is None or b is None:
        return None
    import math
    delta = [bb - aa for aa, bb in zip(a, b)]
    dist = math.sqrt(sum(c * c for c in delta))
    out = {"distance_gu": round(dist, 3), "bearing_deg": None,
           "closing_speed_gups": None, "target_speed_gups": None}
    fwd = _vec(ship.GetWorldRotation().GetCol(1))
    if fwd is not None:
        out["bearing_deg"] = _bearing_deg(fwd, delta)
    va = _vec(ship.GetVelocityTG())
    vb = _vec(target.GetVelocityTG()) if hasattr(target, "GetVelocityTG") else None
    if vb is not None:
        out["target_speed_gups"] = round(math.sqrt(sum(c * c for c in vb)), 3)
    if va is not None and vb is not None and dist > 1e-9:
        rel = [x - y for x, y in zip(vb, va)]
        out["closing_speed_gups"] = round(
            -sum(r * d for r, d in zip(rel, delta)) / dist, 3)
    return out


def _nearest_ship(ship, others) -> Optional[dict]:
    """The closest OTHER ship and where it sits relative to this one's nose.

    Avoidance (PhasedAvoidObstacles, fFrontSpeed 0) stops a ship that has
    another hull in its front cone, so a group that flies in a column can
    hold each other in place; this is what tells that apart from the AI.
    """
    a = _vec(ship.GetWorldLocation())
    fwd = _vec(ship.GetWorldRotation().GetCol(1))
    if a is None:
        return None
    import math
    best = None
    for other in others:
        if other is ship:
            continue
        b = _vec(other.GetWorldLocation())
        if b is None:
            continue
        delta = [bb - aa for aa, bb in zip(a, b)]
        d = math.sqrt(sum(c * c for c in delta))
        if best is None or d < best[0]:
            best = (d, other, delta)
    if best is None:
        return None
    d, other, delta = best
    return {"name": _name_of(other), "distance_gu": round(d, 3),
            "bearing_deg": _bearing_deg(fwd, delta) if fwd is not None else None}


def collect_all_ship_ai() -> List[dict]:
    """Walk every live ship and return ``[{ship_name, tree|None}, ...]``.

    ``tree`` is None when the ship has no AI (or no GetAI surface). Every
    per-ship access is guarded so one malformed ship can't abort the walk."""
    from engine.appc.ship_iter import iter_ships

    try:
        import App
        now = float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        now = None

    out: List[dict] = []
    ships = list(iter_ships())
    for ship in ships:
        name = _name_of(ship)
        tree: Optional[dict] = None
        getter = getattr(ship, "GetAI", None)
        if callable(getter):
            try:
                ai = getter()
            except Exception:
                ai = None
            if ai is not None:
                try:
                    tree = serialize_ai_tree(ai)
                except Exception:
                    tree = None
        # Ship-level facts the tree cannot show. Chasing "NPCs stop engaging
        # after the first volley" stalled on exactly these: the tree said the
        # fire branch was ACTIVE and FOCUSED while every readiness gate read 0,
        # and nothing recorded whether the ship still had a target, whether its
        # AI tree was still being walked, or what the weapons themselves said.
        row = {"ship_name": name, "tree": tree}
        tgt = None
        try:
            tgt = ship.GetTarget()
            row["target"] = _name_of(tgt) if tgt is not None else None
        except Exception:
            row["target"] = None
        try:
            sub = ship.GetTargetSubsystem()
            row["target_subsystem"] = _name_of(sub) if sub is not None else None
        except Exception:
            row["target_subsystem"] = None
        # The sleep scheduler's stamp: if this sits far ahead of game time the
        # whole tree is being skipped, which no per-node status reveals.
        due = ship.__dict__.get("_ai_next_walk_due")
        if isinstance(due, (int, float)):
            row["ai_next_walk_due"] = float(due)
            if now is not None:
                row["ai_walk_due_in"] = float(due) - now
        # Each section guarded on its own: one unreadable ship must cost only
        # that section, never the row or the walk.
        for key, fn in (("motion", lambda: _motion_report(ship)),
                        ("target_geometry", lambda: _target_geometry(ship, tgt)),
                        ("nearest_ship", lambda: _nearest_ship(ship, ships))):
            try:
                row[key] = fn()
            except Exception:
                row[key] = None
        row["weapons"] = _weapon_report(ship)
        row["defence"] = _defence_report(ship)
        out.append(row)
    return out
