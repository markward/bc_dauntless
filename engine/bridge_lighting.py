"""Bridge-interior lighting rules that live on the Python side.

Spec: docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md §5.
"""
from engine import dev_mode

# Bridge states (spec 2026-10-08-bridge-emitters §13.1); the C++ pass uses the
# same ints (renderer::kBridgeStateOffline / kBridgeStateSpecial).
GREEN, YELLOW, RED, OFFLINE, SPECIAL = 0, 1, 2, 3, 4

# Interior ambient multiplier per bridge state. Green is the brightly lit
# cruising bridge; x2.0 read too bright live (Mark, 2026-10-08). x1.0 is the
# SDK-authored bridge ambient. Offline is "dimmed" (Mark 2026-10-11).
OFFLINE_AMBIENT_SCALE = 0.4   # calibrate live
_ALERT_AMBIENT_SCALE = {GREEN: 1.5, YELLOW: 1.0, RED: 1.0,
                        OFFLINE: OFFLINE_AMBIENT_SCALE, SPECIAL: 1.0}
_special = [False]


def set_special_alert(on) -> None:
    """The generic special-alert hook (§13.1), e.g. a future multi-vector
    assault 'blue alert'. No in-game caller yet."""
    _special[0] = bool(on)


def special_alert() -> bool:
    return _special[0]


def ambient_scale_for_alert(level) -> float:
    return _ALERT_AMBIENT_SCALE.get(int(level), 1.0)


def player_bridge_ambient_scale(player) -> float:
    """The scale for the player's current bridge state (§13.1); 1.0 when there
    is no player (mission swap, cutscene)."""
    if player is None:
        return 1.0
    state = bridge_state_of(player, default=None)
    return 1.0 if state is None else ambient_scale_for_alert(state)


def bridge_ambient_scale(player, preview=None, room=None) -> float:
    """The bridge view's room-light scale (Mark 2026-10-12): `room(level)` is
    the bridge's own level for a state (BridgeRuntime.ambient_scale; None =
    use the default), taken for the editor's preview state or else the
    player's (green with no player). The default is the per-state scale
    above (player_bridge_ambient_scale's rules)."""
    if room is not None:
        if preview is not None:
            level = preview
        elif player is None:
            level = GREEN
        else:
            level = bridge_state_of(player, default=None)
        own = room(level) if level is not None else None
        if own is not None:
            return float(own)
    if preview is not None:
        return ambient_scale_for_alert(preview)
    return player_bridge_ambient_scale(player)


def bridge_state_of(player, default=GREEN):
    """The state the player's bridge shows: offline while the power plant is
    disabled or destroyed, else special while the hook is on, else the alert
    level (0-2). No player -> green; an alert probe that raises -> `default`
    (the ambient keeps the authored x1.0 then, not green's)."""
    if player is None:
        return GREEN
    try:
        power = player.GetPowerSubsystem()
        if power is not None and (power.IsDisabled() or power.IsDestroyed()):
            return OFFLINE
    except Exception as e:  # noqa: BLE001 - never let a probe kill the frame
        dev_mode.log_swallowed("bridge power-state probe", e)
    if _special[0]:
        return SPECIAL
    try:
        level = int(player.GetAlertLevel())
    except Exception as e:  # noqa: BLE001
        dev_mode.log_swallowed("bridge alert probe", e)
        return default
    return level if level in (GREEN, YELLOW, RED) else GREEN


def probe_scales():
    """Ambient scales the five state probes (green, yellow, red, offline,
    special) are captured with (spec 2026-10-17 §4.4)."""
    return tuple(ambient_scale_for_alert(i) for i in range(5))
