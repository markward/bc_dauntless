"""Per-frame hull-damage eligibility.

Tessellated carving is expensive, so only a bounded set of ships may
accumulate damage: the player (always) plus the N highest-scoring others,
where score combines proximity to the player and ship size (spec §4). The
selection result is stored as a module-level set of object ids that
engine.appc.hit_feedback reads before emitting a carve.

Pure selection lives in select_eligible(); update() is the impure glue that
resolves the current player via App and refreshes the stored set once per
combat tick (called from engine.host_loop._advance_combat).

Proximity (Plan 2, system-frames spec §1) compares by FRAME via
engine.systems.frames.system_distance, not raw world-space numbers: a ship in
another frame (a different set unrelated to the player's) scores zero
proximity credit no matter how close its raw local coordinates look, since
1.0 / (1.0 + inf) == 0.0. Same-frame pairs get the real distance -- identical
to the raw-coordinate arithmetic this replaces.
"""

# Total eligible ships, INCLUDING the player. Tuning knob.
DEFAULT_MAX_ELIGIBLE = 6

# Score weights: proximity vs size. Tuning knobs.
PROX_WEIGHT = 1.0
SIZE_WEIGHT = 1.0

_current: frozenset = frozenset()


def _radius(ship) -> float:
    return float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 0.0


def select_eligible(player, ships, *, max_count: int = DEFAULT_MAX_ELIGIBLE):
    """Return a frozenset of id()s eligible for hull damage/carve.

    The player (if not None) always claims a slot. Remaining slots go to the
    highest-scoring other ships. With a player, score = PROX_WEIGHT * prox +
    SIZE_WEIGHT * size; without one, score = size only. Deterministic for
    fixed inputs (ties broken by id()).

    `max_count` is assumed >= 1. Player-always (spec §4) takes precedence over
    the cap: the player's slot is seeded before the cap loop, so a degenerate
    max_count=0 still yields the player rather than dropping it.
    """
    ships = list(ships)
    eligible: set = set()
    if player is not None:
        eligible.add(id(player))

    max_r = max((_radius(s) for s in ships), default=0.0) or 1.0

    def score(s) -> float:
        from engine.systems import frames
        size = _radius(s) / max_r
        if player is None:
            return SIZE_WEIGHT * size
        # frames.system_distance is math.inf across frames, so a ship in
        # another frame (e.g. an unrelated set numerically overlapping the
        # player's) scores zero proximity credit no matter how close its raw
        # local coordinates look. Same-frame pairs get the real distance.
        prox = 1.0 / (1.0 + frames.system_distance(s, player))
        return PROX_WEIGHT * prox + SIZE_WEIGHT * size

    others = [s for s in ships if player is None or id(s) != id(player)]
    others.sort(key=lambda s: (-score(s), id(s)))
    for s in others:
        if len(eligible) >= max_count:
            break
        eligible.add(id(s))
    return frozenset(eligible)


def set_current(ids) -> None:
    """Replace the stored eligible-id set."""
    global _current
    _current = frozenset(ids)


def current() -> frozenset:
    """The current eligible-id set."""
    return _current


def is_eligible(ship) -> bool:
    """True iff `ship` is in the current eligible set."""
    return id(ship) in _current


def reset() -> None:
    """Clear eligibility (tests, mission swaps, view-mode transitions)."""
    set_current(frozenset())


def update(ships) -> None:
    """Resolve the current player via App and refresh the eligible set.

    Called once per combat tick before hits are processed. Safe when no game
    / player is available (falls back to size-only selection).
    """
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception:
        player = None
    set_current(select_eligible(player, ships))
