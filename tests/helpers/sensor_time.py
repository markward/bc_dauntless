"""Drive the player-only contact manager to identification in a fixture."""
from engine.appc import sensor_contacts, sensor_dials


def settle_identification(player, start_gt: float = 0.0) -> float:
    """One sweep, then one tick a full dwell later: every contact that was in
    the near band and detectable at start_gt is identified. Returns the end
    game time."""
    sensor_contacts.tick(player, start_gt)
    end = start_gt + sensor_dials.get("identification_time_s")
    sensor_contacts.tick(player, end)
    return end
