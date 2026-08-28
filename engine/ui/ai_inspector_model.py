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
        out["conditions"] = [
            {"name": _condition_label(c),
             "class": type(c).__name__,
             "status": _condition_status(c)}
            for c in conditions
        ]
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


def _weapon_report(ship) -> dict:
    """What the weapon-readiness CONDITIONS are actually reading.

    An exported tree can show every fire gate DORMANT and give no hint why.
    The gates ask whether a bank is charged and whether a tube has ammo, so
    report those directly: "the AI will not fire" and "the weapons say they
    are not ready" are different findings with different fixes, and the tree
    alone cannot tell them apart.
    """
    out = {"banks": [], "tubes": [], "ready_banks": 0, "ready_tubes": 0}
    try:
        import App
        # CT_WEAPON_SYSTEM, not 0. Passing 0 matched nothing at all and the
        # first capture reported ready_banks=0 for every ship INCLUDING the
        # player -- which read as "all weapons dead" when it actually meant
        # "this probe found no weapons". A measurement that fails silently in
        # the direction of the hypothesis is worse than no measurement.
        it = ship.StartGetSubsystemMatch(App.CT_WEAPON_SYSTEM)
        while True:
            sub = ship.GetNextSubsystemMatch(it)
            if sub is None:
                break
            kind = type(sub).__name__
            try:
                if hasattr(sub, "_charge_level") and hasattr(sub, "_max_charge"):
                    lvl = float(getattr(sub, "_charge_level", 0.0) or 0.0)
                    mx = float(getattr(sub, "_max_charge", 0.0) or 0.0)
                    can = bool(sub.CanFire()) if callable(getattr(sub, "CanFire", None)) else None
                    out["banks"].append(
                        {"name": _name_of(sub), "type": kind, "charge": lvl,
                         "max_charge": mx, "can_fire": can})
                    if can:
                        out["ready_banks"] += 1
                elif "Torpedo" in kind or hasattr(sub, "GetAmmo"):
                    ammo = None
                    for attr in ("GetAmmo", "GetNumTorpedoes", "_ammo"):
                        g = getattr(sub, attr, None)
                        try:
                            ammo = int(g()) if callable(g) else (int(g) if g is not None else None)
                        except Exception:
                            ammo = None
                        if ammo is not None:
                            break
                    can = bool(sub.CanFire()) if callable(getattr(sub, "CanFire", None)) else None
                    out["tubes"].append(
                        {"name": _name_of(sub), "type": kind,
                         "ammo": ammo, "can_fire": can})
                    if can:
                        out["ready_tubes"] += 1
            except Exception:
                continue
        ship.EndGetSubsystemMatch(it)
    except Exception:
        pass
    return out


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
    for ship in iter_ships():
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
        row["weapons"] = _weapon_report(ship)
        row["defence"] = _defence_report(ship)
        out.append(row)
    return out
