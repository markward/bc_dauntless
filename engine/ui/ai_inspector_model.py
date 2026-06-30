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

    # ConditionalAI: conditions + single contained AI. Checked before the
    # generic _contained_ai branch so its conditions are captured.
    conditions = getattr(ai, "_conditions", None)
    if isinstance(conditions, list) and _has_attr_chain(ai, "_contained_ai"):
        out["conditions"] = [
            {"name": _name_of(c), "status": _condition_status(c)}
            for c in conditions
        ]
        contained = getattr(ai, "_contained_ai", None)
        out["contained"] = serialize_ai_tree(contained) if contained is not None else None
        return out

    # PreprocessingAI / BuilderAI: single contained AI + preprocessing method.
    if _has_attr_chain(ai, "_contained_ai") and hasattr(ai, "_preprocessing_method"):
        out["preprocessing_method"] = getattr(ai, "_preprocessing_method", "") or ""
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


def collect_all_ship_ai() -> List[dict]:
    """Walk every live ship and return ``[{ship_name, tree|None}, ...]``.

    ``tree`` is None when the ship has no AI (or no GetAI surface). Every
    per-ship access is guarded so one malformed ship can't abort the walk."""
    from engine.appc.ship_iter import iter_ships

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
        out.append({"ship_name": name, "tree": tree})
    return out
