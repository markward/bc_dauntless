"""Target-list / sensor-display visibility helper.

Flips each target-menu row visible or invisible based on range and the
player's sensor state. This is a UI concern (the radar panel and
target-list view both filter on ``row.IsVisible()``); it lives here
rather than in the appc subsystem module that owns the simulation state.

The generic subsystem-state and position predicates it relies on
(``_is_offline``, ``_get_xyz``) stay in engine.appc.subsystems — they are
shared with engine.appc.sensor_detection and the host loop — so we import
them from there.
"""

from engine.appc.subsystems import _is_offline, _get_xyz


def update_target_list_visibility(target_menu, ships, player, range_units: float | None = None) -> None:
    """Flip STSubsystemMenu.SetVisible/SetNotVisible on each row based
    on the ship's distance from the player.

    Args:
        target_menu: the STTargetMenu singleton (or any object exposing
            GetObjectEntry).
        ships: iterable of ship objects expected to be in the menu.
        player: the player ship (for distance computation).
        range_units: maximum range to consider visible. Default ``None``
            means compute from the player's sensor condition via
            ``effective_sensor_range(player)`` (scales linearly with
            condition%, 0.0 when offline, FALLBACK_RANGE_GU when no
            sensor subsystem is present). Pass an explicit value to
            override (e.g. existing callers that supply 30000.0 GU).

    Real Appc filters by sensor subsystem state (charged, undamaged,
    not jammed). Phase-2 takes only range into account; the property
    chain will be wired in a later iteration.

    Project 5 sensor gate (§4.3): when the player's own SensorSubsystem
    reports _is_offline, every row in the menu goes invisible regardless
    of range. The radar panel and target-list view both filter on
    row.IsVisible(), so contacts disappear automatically.
    """
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if _is_offline(sensors):
        for ship in ships:
            row = target_menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            row.SetNotVisible()
        return
    # Range source: an explicit range_units overrides; otherwise scale by the
    # player's sensor condition (engine/appc/sensor_detection). Lazy import
    # avoids an import cycle (sensor_detection imports this module).
    if range_units is None:
        from engine.appc.sensor_detection import effective_sensor_range
        range_units = effective_sensor_range(player)
    from engine.appc.sensor_detection import is_hidden_by_cloak
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
    for ship in ships:
        row = target_menu.GetObjectEntry(ship)
        if row is None or not isinstance(row, STSubsystemMenu):
            continue
        # A fully cloaked ship is invisible regardless of range — both the
        # radar panel and the target-list view hide NotVisible rows.
        if is_hidden_by_cloak(ship):
            row.SetNotVisible()
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - px, sy - py, sz - pz
        if dx * dx + dy * dy + dz * dz <= range_sq:
            row.SetVisible()
        else:
            row.SetNotVisible()
