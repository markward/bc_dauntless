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


class ProbeBlend:
    """Green <-> yellow/red reflection-probe mix (spec 2026-10-08-bridge-emitters
    §9.4): 0 = green, 1 = yellow/red, moving at 1/fade_s per second. The first
    update lands on its target. Feed it the paused-aware player dt."""

    def __init__(self, fade_s=0.5):
        self._fade_s = max(float(fade_s), 1e-6)
        self._mix = None

    def update(self, alert_level, dt) -> float:
        target = 0.0 if int(alert_level) == 0 else 1.0
        if self._mix is None:
            self._mix = target
            return self._mix
        step = max(float(dt), 0.0) / self._fade_s
        if self._mix < target:
            self._mix = min(target, self._mix + step)
        else:
            self._mix = max(target, self._mix - step)
        return self._mix


def probe_scales():
    """Ambient scales the green and the yellow/red probes are captured with."""
    return ambient_scale_for_alert(0), ambient_scale_for_alert(1)
