"""The golden row vocabulary: the tick tuple's components, each state row
kind's field names, and the helpers that compare and describe rows. Light on
purpose (no engine, SDK or pytest imports): tools load it without a game."""
import json

#: The tick tuple's components, in order.
COMPONENTS = ("tick", "state", "events", "queued", "calls", "presented",
              "notes")

#: Field names of each state row kind, after its kind (index 0 = label).
FIELDS = {
    # tests/helpers/k1_fight._Scene.record
    "system": ("label", "IsFiring", "_fire_held", "_force_update",
               "_last_weapon_idx", "_last_group_fired", "_group_fire_mode",
               "_held_target", "_target_list", "_target_list_is_new"),
    "weapon": ("label", "IsFiring", "_target", "_fire_timer", "_depleted",
               "_charge_level", "_cooldown_remaining", "_num_ready",
               "_target_offset", "offset_first_holder",
               "offset_is_held_offset", "_beam_on_countdown",
               "asleep_not_at_rest"),
    "ship": ("name", "IsDead", "hull_condition", "shields"),
    "torpedo": ("label", "translate", "_velocity", "_target_ship",
                "_target_offset", "_damage",
                "_damage_radius_factor", "_ttl", "_age",
                "_guidance_lifetime", "_max_angular_accel", "_source_ship",
                "in_set", "_is_disruptor"),
    # tests/helpers/k3_fight.py weapon_rows (the posed fight)
    "psystem": ("label", "IsFiring", "_fire_held", "_force_update",
                "_last_weapon_idx", "_last_group_fired", "_held_target",
                "_target_list"),
    "pweapon": ("label", "IsFiring", "_target", "_fire_timer", "_depleted",
                "_dwell", "_beam_on_countdown", "_charge_level",
                "_cooldown_remaining", "_num_ready", "_target_offset",
                "offset_first_holder", "asleep_not_at_rest"),
    # added here, every scene
    "pose": ("name", "position", "rotation", "velocity"),
    "tractor": ("label", "_mode", "_engage_state", "_was_firing",
                "_next_emitter_index", "IsEngaged"),
    "tube": ("label", "_reload_timers", "_last_fire_time"),
    # the subsystem stage's own state (_stage_rows), every scene, last
    "stage": ("name", "_main_battery_power", "_backup_battery_power",
              "_available_power", "conditions", "repair_queue",
              "_cloak_state", "_transition_elapsed", "_charge_accum"),
    # tests/helpers/motion_fight.py (the motion_branches scene only)
    "motion": ("name", "_current_speed", "_current_angular_velocity",
               "_drift_velocity", "_speed_setpoint",
               "_target_angular_velocity_setpoint", "_angular_velocity",
               "_angular_space", "warp_flight", "_warp_consumed", "arriving",
               "impulse_fractions", "effective_motion"),
}

EVENT_FIELDS = ("type", "source", "destination", "tick", "payload")

#: Per-scene vocabularies that differ from the fight scenes': scene name ->
#: (state row fields, event fields). tests/helpers/subsystems_scene.py rows.
SCENE_VOCAB = {
    "native_subsystems_scene": (
        {
            "ship": ("name", "_articulation_poses",
                     "_articulation_transitions"),
            "sub": ("label", "_condition", "_threshold_state",
                    "_in_repair_queue", "_condition_watcher",
                    "_combined_watcher"),
            "shield": ("name", "_charge_accum", "_ramp_fraction",
                       "_current_shields", "_is_on", "_power_wanted",
                       "_power_received", "_efficiency", "_power_factor"),
            "plant": ("name", "_available_power", "_main_battery_power",
                      "_backup_battery_power", "_main_conduit_current",
                      "_backup_conduit_current", "_interval_elapsed",
                      "_power_dispensed", "_power_wanted_total",
                      "_breach_fired", "main_battery_watcher",
                      "backup_battery_watcher"),
            "consumer": ("label", "_power_wanted", "_power_received",
                         "_efficiency", "_power_factor", "_is_on",
                         "_normal_power", "_power_percentage_wanted"),
            "cloak": ("name", "_cloak_state", "_transition_elapsed",
                      "_transition_duration", "_backup_reserve"),
            "repair": ("name", "queue", "cannot_complete_notified"),
        },
        ("tick", "in_stage", "type", "source", "destination", "payload"),
    ),
}


def vocabulary(scene=None):
    """(state fields, event fields) for `scene`, else the fight scenes'."""
    return SCENE_VOCAB.get(scene, (FIELDS, EVENT_FIELDS))


def first_difference(want, got, at=()):
    if isinstance(want, list) and isinstance(got, list):
        for i, (a, b) in enumerate(zip(want, got)):
            d = first_difference(a, b, at + (i,))
            if d is not None:
                return d
        if len(want) != len(got):
            return at + ("length",), len(want), len(got)
        return None
    if type(want) is not type(got) or want != got:
        return at, want, got
    return None


def describe(t, at, want_row, scene=None):
    """`at`, a path into tick `t`'s tuple `want_row`, in words: the
    component, a state row's kind and label and its field's name."""
    fields, event_fields = vocabulary(scene)
    words = ["tick %d" % t]
    if not at:
        return words[0]
    comp = COMPONENTS[at[0]]
    words.append(comp)
    rest = list(at[1:])
    if comp == "state" and rest and isinstance(rest[0], int):
        row = want_row[1][rest[0]]
        words.append("row %d (%s %r)" % (rest[0], row[0], row[1]))
        rest = rest[1:]
        if rest and isinstance(rest[0], int):
            i = rest[0] - 1
            names = fields.get(row[0], ())
            words.append("field %d %s" % (
                i, names[i] if 0 <= i < len(names) else "?"))
            rest = rest[1:]
    elif rest and isinstance(rest[0], int):
        words.append("[%d]" % rest[0])
        rest = rest[1:]
        if comp in ("events", "queued") and rest and isinstance(rest[0], int):
            k = rest[0]
            words.append("field %s" % (
                event_fields[k] if 0 <= k < len(event_fields)
                else "[%d]" % k))
            rest = rest[1:]
    if rest:
        words.append("at %r" % (rest,))
    return ", ".join(words)


def row_difference(t, want_row, got_row, scene=None):
    """None when tick `t`'s rows are equal, else a message naming the
    component, row and field and both values. Takes run_scene's tuple rows
    (first_difference recurses into lists only)."""
    want, got = list(want_row), list(got_row)
    d = first_difference(want, got)
    if d is None:
        return None
    at, w, g = d
    return "%s: %r != %r" % (describe(t, at, want, scene), w, g)


def differences(want, got, limit):
    """Every (at, want, got) where the rows differ, up to `limit`, in
    first_difference's order."""
    out = []
    _collect(want, got, (), limit, out)
    return out


def _collect(want, got, at, limit, out):
    if len(out) >= limit:
        return
    if isinstance(want, list) and isinstance(got, list):
        for i, (a, b) in enumerate(zip(want, got)):
            _collect(a, b, at + (i,), limit, out)
            if len(out) >= limit:
                return
        if len(want) != len(got):
            out.append((at + ("length",), len(want), len(got)))
        return
    if type(want) is not type(got) or want != got:
        out.append((at, want, got))


def norm(v):
    return json.loads(json.dumps(v))
