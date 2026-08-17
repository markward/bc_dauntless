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

WHAT THIS MODULE IS NOT: a cache accessor. `surface_gu_for` used to live here
and read the frame's pushed record out of `App.STTargetMenu_GetTargetMenu()`,
which made the model layer depend on the UI layer —
perception -> App -> target_menu -> perception, a cycle held apart only by lazy
imports. It is now `target_menu.surface_gu_to`, on the class that owns the
record; what stayed is the measurement it falls back to,
`measure_surface_gu`. This module imports no App and knows nothing about menus.

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

    ONLY `surface_gu` IS CARRIED. The squared centre distance is a LOCAL in
    `perceived_by` — it feeds `can_detect`'s `dist_sq_gu=` hand-off and
    `_surface_gu` — and was deliberately taken off this record because nothing
    downstream read it: the radar's clip is in its own DISC PLANE, which a 3D
    centre distance cannot answer (see engine/ui/sensors_panel.py), and the
    readouts want the surface convention. Do not re-add it "for completeness";
    a field with no reader is a claim that some consumer needs it.

    The consolidation is NOT total — do not describe this class as "the only
    place distance is computed" without naming the exception.
    `sensor_detection.can_detect` used to recompute the identical squared
    distance every frame; it no longer does for this path, because
    `perceived_by` hands its local in via `dist_sq_gu=`. Still outstanding:
    `engine.ui.weapons_display_panel`'s phaser-range check derives the same
    vector again for its own arc test — a sixth site the original five-site
    survey never counted. Not in scope to fix here; noting it is.
    """
    ship: object
    surface_gu: float
    # KEPT ON PURPOSE THOUGH NO PRODUCTION READER ASKS FOR IT TODAY — and yes,
    # that is the same criterion that removed `dist_sq_gu`. The two cases are
    # not alike, so do not "finish the job" by deleting this one:
    #
    #   * `dist_sq_gu` was a CONSTRUCTION ARTIFACT — a value that happened to
    #     be computed on the way to something else, with no consumer present
    #     or planned. Carrying it claimed a need nobody had.
    #   * `perceivable` is the PERCEPTION CORE. It is deliberately separate
    #     from `targetable` (the target-list gate) because the Hail and
    #     Science-scan menus are expected to read it with their own authored
    #     gates when they adopt this query — see the ⚠️ note on `targetable`
    #     just below, which is the same point from the other side. Removing it
    #     now and re-adding it then is churn, and collapsing the two fields
    #     into one would lose this module's central idea: perceivability is
    #     observer state, targetability is a per-menu policy on top of it.
    #
    # Its last in-tree reader was engine/ui/sensors_panel.py, whose check was
    # dropped once `targetable ⇒ perceivable` was pinned at the source
    # (tests/unit/test_perceived_by.py::test_targetable_always_implies_perceivable);
    # it is still exercised directly by that test and by
    # tests/unit/test_nebula_hides_contacts_from_ui.py.
    perceivable: bool
    # ⚠️ NOT observer-generic: `targetable` folds in `IsTargetable()`, which
    # is a TARGET-LIST rule, not a perception rule. The Hail and
    # Science-scan menus ask the same membership+perceivability question but
    # gate on their own authored flags (`IsHailable`, `IsScannable`), and BC
    # lists objects that are hailable or scannable without being targetable.
    # Do NOT read this field for those menus — build their own gate on
    # `perceivable` instead.
    targetable: bool
    # Named for the EFFECT, not the CAUSE: a fuzzy sensor return you can
    # target at ship level but not pick apart by subsystem. Cloak is the only
    # producer today (a cloaked contact inside its detection bubble is
    # `targetable` but not `subsystems_targetable` — you can shoot at it, not
    # snipe its warp core), but nebula concealment is a plausible second one
    # later, and a field called `cloaked` would then be a lie. Defaults True
    # so every pre-existing `Contact(...)` construction site (tests, the bulk
    # `RebuildShipMenus` synthesiser) keeps its prior "subsystems visible"
    # behaviour without editing every call site.
    subsystems_targetable: bool = True


def perceived_by(observer) -> tuple:
    """Every ship in *observer*'s system, resolved for this frame.

    Empty when there is no observer or it is in no set — which is also what
    makes warp self-correcting: mid-warp the player sits alone in the
    _WarpTransit set, so the list empties without anyone clearing it.
    """
    from engine.appc import sensor_detection as sd
    from engine.appc.sensor_detection import can_detect, effective_sensor_range
    from engine.appc.sets import SetClass
    from engine.appc.ship_death import _out_of_action, is_targetable_wreck

    if observer is None:
        return ()
    pSet = observer.GetContainingSet()
    # Ask the TYPE, not the private dict. This used to be
    # `not hasattr(pSet, "_objects")` — a duck-type test reaching into
    # SetClass's own internals, i.e. exactly the structure contact_index
    # replaced as the membership source. `contact_index` buckets by SetClass,
    # so SetClass is the honest precondition; a `_Stub` or a None set is
    # rejected the same way it was before.
    if not isinstance(pSet, SetClass):
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
        # A cloaked contact is a fuzzy sensor return: targetable at ship level
        # (once it clears the checks above) but not down to individual
        # subsystems. `is_hidden_by_cloak` is an absolute IsCloaked() read, not
        # a detectability gate — `perceivable`/`targetable` above already
        # settled detectability via can_detect's range-contest cloak bubble,
        # so a cloaked ship well inside that bubble is routinely perceivable
        # AND cloaked at once. That combination is exactly what this field
        # exists to express.
        out.append(Contact(
            ship=ship,
            surface_gu=_surface_gu(dist_sq, ship),
            perceivable=perceivable,
            targetable=perceivable and alive_or_wreck and bool(ship.IsTargetable()),
            subsystems_targetable=not sd.is_hidden_by_cloak(ship),
        ))
    return tuple(out)


def _surface_gu(dist_sq: float, ship) -> float:
    """Distance to the target's bounding sphere, BC's range-readout convention
    (verified against the original game by orbiting Haven — see
    engine/ui/reticle_text.py). Negligible for ships, decisive for planets."""
    d = dist_sq ** 0.5
    r = ship.GetRadius() if implements(ship, "GetRadius") else 0.0
    return d - r if d > r else 0.0


def measure_surface_gu(observer, ship) -> float:
    """Measure *observer* → *ship* surface distance from LIVE world positions.

    THE arithmetic, in one place. `perceived_by` reaches `_surface_gu`
    directly because it already holds the squared centre distance (it computed
    it for `can_detect`'s `dist_sq_gu=` hand-off, and re-deriving it here would
    undo exactly the consolidation this module exists for); every other caller
    wants this, which does the vector too.

    Named for the VERB because the distinction matters at the call site: this
    always measures, where `target_menu.surface_gu_to` prefers the frame's
    already-pushed record and falls back to this. A caller that wants "the
    number on screen" wants that one; this is the measurement it delegates to,
    and keeping it here is what stops a second copy of the convention growing
    inside the menu.

    *ship*'s bounding radius is what is subtracted, so the two arguments are
    NOT interchangeable despite both being positions.
    """
    ox, oy, oz = _get_xyz(observer)
    sx, sy, sz = _get_xyz(ship)
    dx, dy, dz = sx - ox, sy - oy, sz - oz
    return _surface_gu(dx * dx + dy * dy + dz * dz, ship)


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


