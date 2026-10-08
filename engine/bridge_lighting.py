"""Bridge-interior lighting rules that live on the Python side.

Spec: docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md §5.
"""
from engine import dev_mode

# Interior ambient multiplier per ShipClass alert level (GREEN 0, YELLOW 1,
# RED 2). Green is the brightly lit cruising bridge; x2.0 read too bright live
# (Mark, 2026-10-08). x1.0 is the SDK-authored bridge ambient.
_ALERT_AMBIENT_SCALE = {0: 1.5, 1: 1.0, 2: 1.0}


def ambient_scale_for_alert(level) -> float:
    return _ALERT_AMBIENT_SCALE.get(int(level), 1.0)


def player_bridge_ambient_scale(player) -> float:
    """The scale for the player's current alert level; 1.0 when there is no
    player or the probe fails (mission swap, cutscene)."""
    if player is None:
        return 1.0
    try:
        return ambient_scale_for_alert(player.GetAlertLevel())
    except Exception as e:  # noqa: BLE001 - never let a probe kill the frame
        dev_mode.log_swallowed("alert bridge-ambient probe", e)
        return 1.0
