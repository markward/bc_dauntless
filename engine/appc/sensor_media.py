"""Is a target inside a medium that hides its identity?
(sensor continuity/occlusion spec, roadmap decision 8)

Unknown by medium = inside an asteroid field (far_tier.field_strength_at at or
above `field_unknown_threshold`) or in moderate nebula
(sensor_detection.concealment_at at or above `nebula_unknown_threshold`). The
contact stays listed and targetable; only its identity and subsystem detail are
withheld. The dense nebula core is a different, stronger effect (can_detect
drops the contact) and is not decided here.

⚠️ field_strength_at only knows the tile fields last pushed for the VIEWED set,
so a ship in an unviewed set reads 0 -- accepted (spec "Known limits"): only the
player identifies, and the player's set is the viewed one.

Module attributes are looked up at call time (far_tier.field_strength_at,
sensor_detection.concealment_at, is_hidden_by_cloak) so tests can monkeypatch
them on their home modules.
"""
from engine.appc import sensor_dials


def medium_unknown(obj, *, concealment=None) -> bool:
    """*concealment*, when given, MUST be this frame's exact
    ``sensor_detection.concealment_at(obj)`` — never an approximation, a
    cached value from a previous frame, or a value sampled for a different
    object. Pass it only when the caller has already taken that density
    sample this frame for its own reasons (``perception.perceived_by`` is the
    one caller that does, handing the SAME sample it gives ``can_detect``);
    when None (every other caller) it is sampled here, so the default
    behaviour is unchanged. This mirrors the ``dist_sq_gu``/``concealment``
    hand-off precedent on ``sensor_detection.can_detect`` — concealment is a
    density-field sample, not a cheap read, and this function and
    ``can_detect`` are now routinely asked about the SAME target in the SAME
    frame (``perceived_by``), so sampling it twice would double real work on
    the busiest path in the sensor model.
    """
    if obj is None:
        return False
    from engine.rocks import far_tier
    from engine.appc import sensor_detection
    if far_tier.field_strength_at(obj) >= sensor_dials.get("field_unknown_threshold"):
        return True
    if concealment is None:
        try:
            concealment = sensor_detection.concealment_at(obj)
        except Exception as exc:
            from engine import dev_mode
            dev_mode.log_swallowed("sensor_media.medium_unknown concealment_at", exc)
            concealment = 0.0
    return concealment >= sensor_dials.get("nebula_unknown_threshold")


def subsystems_hidden(obj, *, concealment=None) -> bool:
    """A fuzzy sensor return: targetable at ship level, not by subsystem.
    Cloak or an identity-hiding medium. One predicate for player and AI.

    *concealment* is forwarded to ``medium_unknown`` unchanged — see its
    docstring for the hand-off contract.
    """
    from engine.appc import sensor_detection
    return bool(sensor_detection.is_hidden_by_cloak(obj)
                or medium_unknown(obj, concealment=concealment))
