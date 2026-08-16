"""What an observer can perceive — the read-time half of the contact model.

engine.appc.contact_index holds what EXISTS, bucketed by set. This module
answers the per-observer question, which cannot be stored: the same ship is
perceivable to one observer and not another at the same instant, so a stored
answer would have to be per-observer-per-frame.

STAGE 3 SCOPE: folds range, cloak, and the sensors-offline short-circuit into
one query — `perceived_by` — reproducing the UI detectability rule that used
to live in engine.ui.target_list_visibility (now deleted; the target menu
derives row visibility from these records) and engine.ui.target_list_view
exactly, with NO nebula concealment. Distance was previously recomputed in five places
under two different conventions; it is now computed once here. `contacts_for`
stays as a thin back-compat wrapper for callers not yet migrated to Contact
records. Stage 4 switches perceivability to sensor_detection.can_detect
(which adds nebula concealment with a stateful hysteresis latch) and makes
cloak range-defeatable, both behind a stock-BC fidelity toggle. See
docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.appc import contact_index
from engine.appc.subsystems import _get_xyz
from engine.core.ids import implements


@dataclass(frozen=True)
class Contact:
    """One contact, fully resolved for this frame.

    Consumers do no further arithmetic: the target list reads `targetable`,
    the radar reads `perceivable` plus its own display clip, and the range
    readouts read `surface_gu`. For that listing/radar/readout path, distance
    is now computed once here, replacing five call sites that used to derive
    the same player-to-contact vector under two different conventions.

    That consolidation is NOT total, and two sites still recompute the
    identical squared distance independently — do not describe this class as
    "the only place distance is computed" without naming them:
    `sensor_detection.can_detect` (its own range/cloak/nebula gate, which this
    module does not yet call — see the STAGE 3 SCOPE note above) recomputes it
    every frame **by design**, because a later stage merges the two; and
    `engine.ui.weapons_display_panel`'s phaser-range check derives the same
    vector again for its own arc test — a sixth site the original five-site
    survey never counted. Neither is in scope to fix here; noting them is.
    """
    ship: object
    dist_sq_gu: float
    surface_gu: float
    perceivable: bool
    # ⚠️ NOT observer-generic: `targetable` folds in `IsTargetable()`, which
    # is a TARGET-LIST rule, not a perception rule. The Hail and
    # Science-scan menus ask the same membership+perceivability question but
    # gate on their own authored flags (`IsHailable`, `IsScannable`), and BC
    # lists objects that are hailable or scannable without being targetable.
    # Do NOT read this field for those menus — build their own gate on
    # `perceivable` instead.
    targetable: bool


def perceived_by(observer) -> tuple:
    """Every ship in *observer*'s system, resolved for this frame.

    Empty when there is no observer or it is in no set — which is also what
    makes warp self-correcting: mid-warp the player sits alone in the
    _WarpTransit set, so the list empties without anyone clearing it.
    """
    from engine.appc.sensor_detection import (
        effective_sensor_range, is_hidden_by_cloak)
    from engine.appc.ship_death import _out_of_action, is_targetable_wreck

    if observer is None:
        return ()
    pSet = observer.GetContainingSet()
    # A real SetClass exposes _objects; a _Stub or None does not. hasattr()
    # cannot discriminate — TGObject.__getattr__ answers every name.
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()

    # Sensors offline => effective range 0 => nothing perceivable. One check,
    # before any iteration.
    range_gu = effective_sensor_range(observer)
    range_sq = range_gu * range_gu
    ox, oy, oz = _get_xyz(observer)

    out = []
    for ship in contact_index.ships_in(pSet):
        if ship is observer:
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - ox, sy - oy, sz - oz
        dist_sq = dx * dx + dy * dy + dz * dz
        # Cheap bools before the distance comparison; nothing here samples a
        # field or takes a square root.
        perceivable = (
            range_gu > 0.0
            and not is_hidden_by_cloak(ship)
            and dist_sq <= range_sq
        )
        alive_or_wreck = (not _out_of_action(ship)) or is_targetable_wreck(ship)
        out.append(Contact(
            ship=ship,
            dist_sq_gu=dist_sq,
            surface_gu=_surface_gu(dist_sq, ship),
            perceivable=perceivable,
            targetable=perceivable and alive_or_wreck and bool(ship.IsTargetable()),
        ))
    return tuple(out)


def _surface_gu(dist_sq: float, ship) -> float:
    """Distance to the target's bounding sphere, BC's range-readout convention
    (verified against the original game by orbiting Haven — see
    engine/ui/reticle_text.py). Negligible for ships, decisive for planets."""
    d = dist_sq ** 0.5
    r = ship.GetRadius() if implements(ship, "GetRadius") else 0.0
    return d - r if d > r else 0.0


def contacts_for(observer) -> tuple:
    """Targetable ships in *observer*'s system. Back-compat wrapper over
    perceived_by for callers not yet migrated to Contact records.

    Has zero production callers as of this branch — `_pump_contacts` moved to
    `perceived_by` directly. Only tests call this now. It is kept, not
    deleted, because its tests are real coverage of the membership rule; it is
    just not on a hot path, so there is no obligation to keep it fast or to
    route new production code through it.
    """
    return tuple(c.ship for c in perceived_by(observer) if c.targetable)


def surface_gu_for(ship):
    """This frame's `surface_gu` for *ship*, from the pushed contact record,
    or None when there is no record.

    THE read path for the on-screen range readouts (engine.ui.reticle_text and
    engine.ui.ship_display_panel). It reads the record the host loop already
    pushed (host_loop._pump_contacts, every frame, before the panels render)
    rather than calling perceived_by a second time — a second call would redo
    the whole per-observer pass to answer one number.

    None is a real answer, not a failure, and callers MUST fall back to their
    own read for it. contact_index buckets ShipClass only, so a targeted PLANET
    or station ObjectClass never has a record — and the surface convention
    matters most there (orbiting Haven reads 26 km, not 42). None also covers
    the pre-menu boot frames and the headless fixtures that never push.
    """
    import App
    menu = App.STTargetMenu_GetTargetMenu()
    if menu is None:
        return None
    contact = menu.contact_for(ship)
    return None if contact is None else contact.surface_gu
