"""EngRepairPane — snapshot + click logic for the CEF repair-queue UI.

Widget identity lives in App.py (EngRepairPaneWidget, created by the
UNMODIFIED sdk Bridge/EngineerMenuHandlers.py:84 via EngRepairPane_Create
and added as a child of the Engineering STTopLevelMenu). CrewMenuPanel
projects it into CEF using this module's snapshot; clicks post
ET_REPAIR_INCREASE_PRIORITY back at the player's repair bay.

Spec: docs/superpowers/specs/2026-07-05-repair-system-design.md §4.
Three areas mirror stock (ship-subsystems.md §Engineering panel UI):
REPAIR = first NumRepairTeams queue entries, WAITING = the rest,
DESTROYED = ship subsystems at zero condition (derived from the ship's
subsystem list, NOT the queue; destroyed-but-still-queued entries are
excluded from REPAIR/WAITING).
"""
from __future__ import annotations

from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui import ui_attention
from engine.ui.damage_icons import icon_num_for_subsystem


def _row(sub, register) -> dict:
    wid = ensure_widget_id(sub)
    register(wid, sub)
    mx = sub.GetMaxCondition()
    pct = int(round(100.0 * sub.GetCondition() / mx)) if mx > 0 else 0
    row = {
        "id": wid,
        "label": sub.GetName() or "",
        "icon": icon_num_for_subsystem(sub),
        "pct": pct,
    }
    ui_attention.apply(row, wid)
    return row


def _iter_ship_subsystems(ship):
    """Every top-level subsystem with a condition bar. Reuses the damage
    subview's walk (engine/ui/ship_display_panel.py:_iter_damage_subsystems)
    so the DESTROYED area matches what the damage display already shows."""
    from engine.ui.ship_display_panel import _iter_damage_subsystems
    return _iter_damage_subsystems(ship)


def repair_pane_snapshot(ship, register) -> dict:
    """Build the three-area snapshot. `register(wid, sub)` records the
    id->subsystem mapping in the caller's click-dispatch table."""
    empty = {"repair": [], "waiting": [], "destroyed": []}
    if ship is None:
        return empty
    bay = ship.GetRepairSubsystem() if hasattr(ship, "GetRepairSubsystem") else None
    if bay is None or not hasattr(bay, "_queue"):
        return empty
    teams = bay.GetNumRepairTeams()
    live = [s for s in bay._queue if s.GetCondition() > 0.0]
    destroyed = [s for s in _iter_ship_subsystems(ship) if s.IsDestroyed()]
    return {
        "repair":    [_row(s, register) for s in live[:teams]],
        "waiting":   [_row(s, register) for s in live[teams:]],
        "destroyed": [_row(s, register) for s in destroyed],
    }
