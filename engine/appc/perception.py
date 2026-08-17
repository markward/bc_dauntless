"""What an observer can perceive — the read-time half of the contact model.

engine.appc.contact_index holds what EXISTS, bucketed by set. This module
answers the per-observer question, which cannot be stored: the same ship is
perceivable to one observer and not another at the same instant, so a stored
answer would have to be per-observer-per-frame.

Stage 3 folded range, cloak, and the sensors-offline short-circuit into one
query — `perceived_by` — replacing the UI detectability rule that used to live
in engine.ui.target_list_visibility (now deleted; the target menu derives row
visibility from these records) and engine.ui.target_list_view. Distance was
previously recomputed in five places under two different conventions; it is now
computed once here. `contacts_for` stays as a thin back-compat wrapper for
callers not yet migrated to Contact records.

STAGE 4 SCOPE: there is now exactly ONE detection rule.
`sensor_detection.can_detect` — already the gate for weapons, AI targeting and
the player's lock — is what `perceived_by` calls, so the target list and radar
gained nebula concealment and the range-contest cloak. Before this you could
select and hold a target you could not fire on; that is a DELIBERATE gameplay
change, pinned by tests/unit/test_nebula_hides_contacts_from_ui.py.

Both halves sit behind ONE toggle, `sensor_detection.ENHANCED_SENSOR_CONTEST`
(code-only, no UI). Turned off, this module hands `apply_concealment=False` to
`can_detect`, which then answers range + absolute cloak + distance — the
pre-stage-4 rule exactly, with no second copy of it living here. Read that
flag's docstring before touching this: its off state is deliberately
asymmetric (weapons keep applying nebula concealment), because "off" means
"how the game behaved before", warts included.

Two consequences worth knowing before editing the loop below. First,
`can_detect` mutates a per-(observer, target) hysteresis latch, so with the
toggle on this module is a WRITER of that shared state, not just a reader (with
it off the nebula gate is skipped entirely, so nothing is written). The
invariant that protects is IDEMPOTENCY, not call-count: the latch is set
membership, not a counter, and concealment is stable within a frame, so
re-asking the same (observer, target) in the same frame returns the same answer
and leaves the same state. ⚠️ Earlier text here claimed `can_detect` "must be
called EXACTLY ONCE per contact per frame"; that was never true and would have
condemned legitimate call sites that already exist — `host_loop.py:907` (the
per-tick firing chokepoint), `projectiles.py:375` (once per in-flight torpedo),
`sensor_identification.py:127`, and `clear_undetectable_player_lock` all hit the
same key repeatedly in one frame. Do not refuse a needed call on that basis; DO
keep the latch idempotent, because if it ever gains a per-call time or counter
term the UI and the lock guard start disagreeing on the frame a lock breaks
(pinned by tests/unit/test_nebula_hides_contacts_from_ui.py::
test_the_hysteresis_latch_is_idempotent_within_a_frame). Second, it takes the
squared distance this module already computed rather than deriving it again;
that hand-off is what keeps the five-site consolidation from being undone.

See docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md.
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

    That consolidation is NOT total — do not describe this class as "the only
    place distance is computed" without naming the exception.
    `sensor_detection.can_detect` used to recompute the identical squared
    distance every frame; it no longer does for this path, because
    `perceived_by` hands its value in via `dist_sq_gu=`. Still outstanding:
    `engine.ui.weapons_display_panel`'s phaser-range check derives the same
    vector again for its own arc test — a sixth site the original five-site
    survey never counted. Not in scope to fix here; noting it is.
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
    from engine.appc import sensor_detection as sd
    from engine.appc.sensor_detection import can_detect, effective_sensor_range
    from engine.appc.ship_death import _out_of_action, is_targetable_wreck

    if observer is None:
        return ()
    pSet = observer.GetContainingSet()
    # A real SetClass exposes _objects; a _Stub or None does not. hasattr()
    # cannot discriminate — TGObject.__getattr__ answers every name.
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()

    # Sensors offline => effective range 0 => nothing perceivable. One check,
    # before any iteration. can_detect re-derives this per contact and returns
    # False on its own for range 0, so this is purely a saved-work short
    # circuit; the answer is the same either way.
    range_gu = effective_sensor_range(observer)
    ox, oy, oz = _get_xyz(observer)
    # Read the stage-4 toggle ONCE per frame, not per contact, so every row in
    # a frame is answered under one configuration even if it were flipped
    # mid-pass. See the gate note in the loop below.
    apply_conceal = sd.ENHANCED_SENSOR_CONTEST

    out = []
    for ship in contact_index.ships_in(pSet):
        if ship is observer:
            continue
        sx, sy, sz = _get_xyz(ship)
        dx, dy, dz = sx - ox, sy - oy, sz - oz
        dist_sq = dx * dx + dy * dy + dz * dz
        # ONE detection rule, shared with the weapons, AI targeting and the
        # player's lock. can_detect also mutates a per-(observer, target)
        # hysteresis latch, which this loop writes once per contact. That is
        # economy, NOT a uniqueness requirement: other frame-synchronous callers
        # (the firing chokepoint, torpedo guidance, sensor identification, the
        # lock guard) legitimately re-ask the same key in the same frame, and
        # the answer is stable because the latch is set membership and
        # concealment does not move within a frame. See the module docstring.
        # The already-derived squared distance is handed in rather than
        # recomputed inside.
        #
        # `apply_concealment` carries the stage-4 toggle: with it off, the same
        # call yields range + absolute cloak + distance, which IS the
        # pre-stage-4 UI rule exactly — so the off state is a real rollback
        # without a second copy of the rule here to drift out of step.
        perceivable = range_gu > 0.0 and can_detect(
            observer, ship, dist_sq_gu=dist_sq,
            apply_concealment=apply_conceal)
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


def surface_gu_for(ship, observer) -> float:
    """Surface distance from *observer* to *ship*, in GU. ALWAYS answers.

    THE read path for the on-screen range readouts (engine.ui.reticle_text and
    engine.ui.ship_display_panel), and the only distance derivation either of
    them performs. Callers do ONE unconditional read; there is deliberately no
    sentinel for them to branch on, because the branch is how the duplication
    came back last time. Both readouts used to keep their entire original
    computation as a `if dist is None:` fallback, which added a layer instead of
    replacing one.

    Fast path: the record the host loop already pushed this frame
    (host_loop._pump_contacts, before the panels render). Reading it beats
    calling perceived_by again, which would redo the whole per-observer pass to
    answer one number.

    Miss path — same arithmetic, via `_surface_gu`, so there is one
    implementation and not one plus a copy. Three ways to miss, all real:

      * a targeted PLANET or station. contact_index buckets ShipClass only, so
        an ObjectClass never has a record — and this is where the convention
        earns its keep (orbiting Haven reads 26 km, not 42; on a ship the
        radius subtraction is a rounding error).
      * boot frames and headless fixtures, where no menu exists or nothing has
        been pushed yet.
      * a NaN record. STTargetMenu.RebuildShipMenus synthesises
        `surface_gu=NaN` on purpose because it takes a set, not an observer,
        and so cannot answer distance. NaN is treated as a miss here; without
        that, "nan km" would render on screen.

    ⚠️ *observer* is used ONLY on the miss path. The record path returns
    `contact.surface_gu` whoever you pass, because STTargetMenu stores no
    observer alongside its contacts and so cannot check: it holds one frame's
    push, and that push came from the player. `surface_gu_for(ship, other_ship)`
    will therefore silently hand back the PLAYER's distance whenever a record
    exists. Both callers pass the player, so this is consistent today — but do
    not read this function as answering a per-observer question; it does not,
    and making it do so means putting the observer into the pushed record.

    *observer* is required and must not be None: measuring a distance from
    nowhere has no answer, and there is no sentinel to hand back (that is the
    whole point of this function). Both callers already hold the player and bail
    before reaching here without one — ship_display_panel returns (None, None)
    on a null player, and the reticle is not built without one — so requiring it
    deletes two unreachable branches rather than pushing work onto anybody.
    """
    import App
    menu = App.STTargetMenu_GetTargetMenu()
    if menu is not None:
        contact = menu.contact_for(ship)
        # `x != x` is the NaN test that needs no import and no isinstance:
        # Contact.surface_gu is always a float.
        if contact is not None and contact.surface_gu == contact.surface_gu:
            return contact.surface_gu

    ox, oy, oz = _get_xyz(observer)
    sx, sy, sz = _get_xyz(ship)
    dx, dy, dz = sx - ox, sy - oy, sz - oz
    return _surface_gu(dx * dx + dy * dy + dz * dz, ship)
