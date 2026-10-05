"""Keep Science's "Scan Object" buttons on the "Unknown N" placeholder until
the contact is identified (sensor-tiers spec Sec6, roadmap decision 5).

Science adds a button labelled GetDisplayName() on ET_TARGET_LIST_OBJECT_ADDED
as well as on identification (Bridge/ScienceMenuHandlers.py:91-94), which
would leak an unknown ship's real name. Two SDK functions are wrapped, by
module attribute -- handlers resolve by name at dispatch
(engine/appc/events.py:_resolve_handler), so the wrap reaches live events:

  * CreateScanButton -- sees the placeholder as the object's display name, so
    its GetButtonW de-dupe and STButton_CreateW label both use it.
  * ExitedSet -- removes by the placeholder while the object is unknown.

On identification ``sensor_identification._identify_one`` calls
``rename_on_identify`` AFTER ``AddKnownObject`` but BEFORE posting
ET_SENSORS_SHIP_IDENTIFIED; otherwise ShipIdentified's de-dupe (by the real
name) would miss the placeholder button and add a duplicate.
"""
from contextlib import contextmanager

import App
from engine.appc import unknown_labels


# Sentinel for "obj had no instance-level GetDisplayName override" -- distinct
# from any real value (including None), so it can't collide with one.
_NO_PRIOR_OVERRIDE = object()


@contextmanager
def _display_name_as(obj, label):
    """Temporarily make obj.GetDisplayName() answer *label* (instance attr).

    Save/restore, not a blind delete: a caller may already have its own
    instance-level GetDisplayName override in place, and this context can
    also be entered reentrantly on the SAME object (e.g. a wrapped
    CreateScanButton call nested inside a wrapped ExitedSet call during one
    event dispatch). An unconditional `del obj.GetDisplayName` in `finally`
    would either permanently destroy a pre-existing override, or -- in the
    nested case -- have the INNER call's cleanup delete the attribute the
    OUTER call still relies on for the rest of its own `with` block.

    Checked via `obj.__dict__`, not `getattr`/`hasattr`: every ObjectClass
    has a class-level GetDisplayName method, so a getattr-based check would
    always see "an override" and never restore to the class method.
    """
    prior = obj.__dict__.get("GetDisplayName", _NO_PRIOR_OVERRIDE)
    obj.GetDisplayName = lambda: label
    try:
        yield
    finally:
        if prior is _NO_PRIOR_OVERRIDE:
            try:
                del obj.GetDisplayName
            except AttributeError:
                pass
        else:
            obj.GetDisplayName = prior


def _unknown_label(obj):
    """The placeholder CreateScanButton should show for *obj*, or None to use
    its real name.

    Only allocates a NEW number when the SDK would actually build a button
    for it -- mirrors CreateScanButton's own early returns (IsScannable,
    not cloaking/cloaked) by calling the SAME predicates it is built from,
    not by re-deriving cloak state here. An already-allocated number is
    always returned regardless (`unknown_labels.current`), so a contact that
    loses scannability/decloaks mid-flight keeps its placeholder rather than
    being silently renumbered."""
    from engine.appc import sensor_contacts
    if obj is None or sensor_contacts.shows_identity(obj):
        return None
    current = unknown_labels.current(obj)
    if current is not None:
        return current
    is_scannable = getattr(obj, "IsScannable", None)
    if is_scannable is None or not is_scannable():
        return None
    # CreateScanButton's own cloak check is gated on `App.ShipClass_Cast`
    # succeeding -- mirror that gate, not just the predicates, or a non-ship
    # (planet, station) falls through to `TGObject.__getattr__`'s truthy
    # `_Stub` for GetCloakingSubsystem and reads as permanently "cloaking"
    # (combat.cloak_shields_suspended resolves it off the INSTANCE, not the
    # class, so it has no stub guard of its own).
    from engine.appc.ships import ShipClass
    if isinstance(obj, ShipClass):
        from engine.appc.sensor_detection import is_hidden_by_cloak
        from engine.appc.combat import cloak_shields_suspended
        if is_hidden_by_cloak(obj) or cloak_shields_suspended(obj):
            return None
    return unknown_labels.placeholder(obj)


def _wrap_create(orig):
    def CreateScanButton(pObject):
        obj = App.ObjectClass_Cast(pObject)
        label = _unknown_label(obj)
        if label is None:
            return orig(pObject)
        with _display_name_as(obj, label):
            return orig(pObject)
    CreateScanButton._unknown_labelled = True
    return CreateScanButton


def _wrap_exited(orig):
    def ExitedSet(pObject, pEvent=None):
        obj = App.ObjectClass_Cast(pEvent.GetDestination() if pEvent else pObject)
        label = unknown_labels.current(obj) if obj is not None else None
        if label is None:
            return orig(pObject, pEvent)
        with _display_name_as(obj, label):
            return orig(pObject, pEvent)
    ExitedSet._unknown_labelled = True
    return ExitedSet


def install() -> None:
    try:
        import Bridge.ScienceMenuHandlers as smh
    except ImportError:
        return
    if not getattr(smh.CreateScanButton, "_unknown_labelled", False):
        smh.CreateScanButton = _wrap_create(smh.CreateScanButton)
    if not getattr(smh.ExitedSet, "_unknown_labelled", False):
        smh.ExitedSet = _wrap_exited(smh.ExitedSet)


def rename_on_identify(obj) -> None:
    """Rename the contact's Scan Object button from its placeholder to its
    real display name, so Science's ShipIdentified dedupe (which looks the
    button up by the REAL name) finds it instead of adding a duplicate.

    No-op if *obj* has no live placeholder (already identified, or never had
    a row) or the Scan Object submenu cannot be resolved."""
    label = unknown_labels.current(obj)
    if label is None:
        return
    try:
        import MissionLib
        menu = MissionLib.GetCharacterSubmenu("Science", "Scan Object")
    except Exception:
        return
    if menu is None:
        return
    menu.RenameButton(label, obj.GetDisplayName())
