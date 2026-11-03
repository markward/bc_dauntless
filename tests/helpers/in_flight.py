"""What a fight leaves in flight: the module-level accumulator lists that
production drains per mission tick.

ONE list, shared by tests/conftest.py's `_reset_leakable_engine_globals`
(cleared between tests) and tests/helpers/headless_mission.py's
`clear_in_flight` (cleared between the arms of a test that loads a mission
twice). Each entry is (module name, attribute); the attribute has `.clear()`.

Not a list, so not here: the combat effect queue's held entries (a condition
write's or a hit's effects awaiting the tick boundary, the death check among
them). tests/conftest.py drops them through native_combat.reset();
headless_mission.clear_in_flight through effect_queue.reset().
"""

IN_FLIGHT = (
    ("engine.appc.projectiles", "_active"),
    ("engine.appc.hit_vfx", "_active"),
    ("engine.appc.ship_death", "_active"),
    # A hull-0 ship's pending subsystem cascade: left queued, it destroys
    # the dead arm's ship's subsystems in the next arm (or test), posting
    # ET_SUBSYSTEM_DESTROYED there.
    ("engine.appc.subsystem_cascade", "_active"),
    ("engine.appc.object_lifetime", "_timed"),
    ("engine.appc.visible_damage", "_pending"),
    ("engine.appc.internal_blast", "_pending"),
    ("engine.appc.warp_core_breach", "_growing"),
    # The single-fire guarantee's queue + set: a ship armed or breached
    # by one test would never detonate (or detonate) in a later one.
    ("engine.appc.warp_core_breach", "_armed"),
    ("engine.appc.warp_core_breach", "_breached"),
    ("engine.audio.attached_sources", "_attached"),
    ("engine.audio.hum_allocator", "_humming"),
    # Detached hull chunks + the per-ship breakup throttle: a chunk left
    # live by one test is yielded by collisions.iter_collidables() in
    # every later test, and a stale _pending_wear entry re-runs a split
    # on a ship that no longer exists.
    ("engine.appc.debris_chunk", "_live"),
    ("engine.appc.hull_breakup", "_pending_wear"),
    ("engine.appc.hull_breakup", "_last_wear_check"),
    ("engine.appc.hull_breakup", "_severed"),
    ("engine.appc.hull_breakup", "_part_labels"),
    ("engine.appc.hull_breakup", "_awaiting"),
)
