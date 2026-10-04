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


@contextmanager
def _display_name_as(obj, label):
    """Temporarily make obj.GetDisplayName() answer *label* (instance attr)."""
    obj.GetDisplayName = lambda: label
    try:
        yield
    finally:
        try:
            del obj.GetDisplayName
        except AttributeError:
            pass


def _unknown_label(obj):
    from engine.appc import sensor_contacts
    if obj is None or sensor_contacts.player_knows(obj):
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
