# engine/appc/death_cascade.py
"""BC's death cascade — the explosion storm that tears a dying hull open.

Reconstructed from `Effects.ObjectExploding` (sdk/Build/scripts/Effects.py:735)
and its helper `CreateObjectExplosion` (Effects.py:705), which together are the
whole of BC's death sequence:

    fTotalLifeLeft = random(100)/10.0 + 5.0      # 5-15 s, unless already set
    while fExplosionTime < fTotalLifeLeft:
        CreateObjectExplosion(pObject, bSound)   # at GetRandomPointOnModel()
        fExplosionTime += random(4) * 0.15       # mean 0.225 s -> ~4-5 per second

    # inside CreateObjectExplosion:
    if random(10) < 3:
        DeathExplosionDamage(..., fRadius / 4.0, 600.0)     # -> AddDamage

That 30% branch is what makes a BC ship visibly come apart: over a 5-15 s death
it lands roughly 7-20 `AddDamage` calls at fresh points all over the model, and
strength 600 saturates our carve curve (kHullCarveStrengthIso 150 +
450*0.0006 = 0.30 GU, the kHullCarveRadiusMaxGu clamp), so every one of them is
a maximum-size hole. Our previous death sequence was a fixed 5 s of four sprite
puffs that carved nothing at all.

WHY THIS IS REIMPLEMENTED RATHER THAN CALLED. `Effects.ObjectExploding` would be
the faithful thing to invoke, but it calls `SetLifeTime`, which registers the
ship with `engine.appc.object_lifetime`, whose `_expire` calls
`ship_death.retire` -> `_mark_dead` -> a SECOND `ET_OBJECT_DESTROYED` broadcast
racing the one `ship_death` fires at the end of its own throes. 24 SDK missions
do kill-detection on those events, so double-firing them is a correctness bug,
not a cosmetic one. The parameters and structure here are BC's; only the timer
is ours, ticked by `ship_death.advance` so the cascade pauses with the game and
clears on mission swap.

The damage call goes straight to `ship.AddDamage` rather than through BC's
`DamageableObject_GetObjectByID(...)` round-trip: that lookup exists only
because BC defers the call inside a TGSequence that may cross a save/load, and
we fire immediately from a live reference.

See docs/engine/damagetool-and-hull-damage-gaps.md for the carve curve.
"""
import engine.dev_mode as dev_mode

# ── BC constants (Effects.py) ────────────────────────────────────────────────
THROES_MIN = 5.0          # random(100)/10.0 + 5.0 -> [5.0, 15.0)
THROES_MAX = 15.0
LIFETIME_UNSET = 1.0e6    # BC's "lifetime has not been set yet" sentinel

BLAST_SPACING_UNIT = 0.15   # fExplosionTime += random(4) * 0.15
BLAST_SPACING_STEPS = 4     # GetRandomNumber(4) -> 0..3

DAMAGE_CHANCE_IN_10 = 3        # if random(10) < 3
DAMAGE_RADIUS_FRACTION = 0.25  # fRadius / 4.0
DAMAGE_STRENGTH = 600.0        # the "major hull breach" authored tier

BLAST_SIZE_FRACTION = 0.25   # CreateDebrisExplosion(fRadius * 0.25, ...)
BLAST_LIFE = 1.5             # fLife on every debris explosion
SOUND_MIN_GAP = 0.4          # "don't play a sound for every explosion, or we
                             # end up flooding all the 3D sound handles"
FINAL_BARRAGE_LEAD = 2.5     # the big finish lands at fTotalLifeLeft - 2.5

# A zero roll from GetRandomNumber(4) advances BC's loop by nothing, so its
# worst case is unbounded. BC tolerates that; we cap it. The cap is ~3x the
# expected count for the longest window (15 s / 0.225 s mean ~= 67).
MAX_BLASTS = 200


def _rand(n: int) -> int:
    """BC's RNG, so the cascade draws from the same stream the SDK does."""
    import App
    return App.g_kSystemWrapper.GetRandomNumber(n)


def roll_duration(ship, rand=None) -> float:
    """The ship's death window, BC's way: honour an already-set lifetime,
    otherwise roll 5-15 s.

    A mission that set one means it (E7M1's doomed freighter uses 4.0), and BC
    keys off the >1e6 sentinel rather than a null check.
    """
    rand = rand or _rand
    try:
        life = float(ship.GetLifeTime())
    except Exception:
        life = LIFETIME_UNSET * 10.0
    if life > LIFETIME_UNSET:
        return float(rand(100)) / 10.0 + THROES_MIN
    return life


def plan(duration: float, rand=None) -> list:
    """The blast times for a death window, spaced BC's way.

    Returns offsets in seconds from the start of the throes; the first is
    always 0.0 (BC enters the loop at fExplosionTime = 0).
    """
    rand = rand or _rand
    times = []
    t = 0.0
    while t < duration and len(times) < MAX_BLASTS:
        times.append(t)
        t += rand(BLAST_SPACING_STEPS) * BLAST_SPACING_UNIT
    return times


def begin(ship, duration: float, rand=None) -> dict:
    """Start a cascade for `ship` over `duration` seconds. Returns the state
    `advance` ticks; the caller owns it (ship_death parks it on its entry, so
    the registry reset clears cascades too)."""
    return {
        "ship": ship,
        "duration": float(duration),
        "elapsed": 0.0,
        "blasts": plan(float(duration), rand),
        "next_index": 0,
        "last_sound_at": None,   # None = no sound played yet
        "final_fired": False,
        "rand": rand,
    }


def advance(state: dict, dt: float) -> None:
    """Fire every blast whose time has come, then the final barrage."""
    state["elapsed"] += dt
    now = state["elapsed"]

    blasts = state["blasts"]
    while state["next_index"] < len(blasts) and blasts[state["next_index"]] <= now:
        _fire(state, sound_ok=_sound_due(state, blasts[state["next_index"]]))
        state["next_index"] += 1

    # BC schedules the finish at fTotalLifeLeft - 2.5. A window shorter than the
    # lead (an asteroid's 0.5 s) would put it in the past, so it fires at once
    # rather than being skipped.
    if not state["final_fired"]:
        final_at = state["duration"] - FINAL_BARRAGE_LEAD
        if now >= max(0.0, final_at):
            _fire_final(state)
            state["final_fired"] = True


def _sound_due(state: dict, blast_time: float) -> bool:
    """BC throttles death-explosion sounds to one per 0.4 s so the cascade does
    not exhaust the 3D sound handles."""
    last = state["last_sound_at"]
    if last is not None and blast_time - last <= SOUND_MIN_GAP:
        return False
    state["last_sound_at"] = blast_time
    return True


def _fire(state: dict, sound_ok: bool) -> None:
    """One explosion of the cascade: sample a point on the hull, maybe carve
    there, then play the debris explosion (and maybe a sound) at it.

    The carve is done BEFORE the VFX deliberately: a missing effect backend
    must never cost the ship its damage. Raise-safe as a whole -- death logic
    cannot depend on VFX succeeding.
    """
    ship = state["ship"]
    rand = state["rand"] or _rand
    try:
        point = ship.GetRandomPointOnModel()
        radius = float(ship.GetRadius())

        if rand(10) < DAMAGE_CHANCE_IN_10:
            ship.AddDamage(point, radius * DAMAGE_RADIUS_FRACTION, DAMAGE_STRENGTH)

        _debris_explosion(ship, point, radius * BLAST_SIZE_FRACTION)
        _light(ship, radius * BLAST_SIZE_FRACTION)
        if sound_ok:
            _death_sound(ship)
    except Exception as _e:
        dev_mode.log_swallowed("death cascade blast", _e)


def _fire_final(state: dict) -> None:
    """BC's closing barrage: sparks plus full-ship-radius explosions at fresh
    points, two more of them above the MEDIUM effect level."""
    ship = state["ship"]
    try:
        radius = float(ship.GetRadius())
        import App
        import Effects

        pSet = ship.GetContainingSet()
        root = pSet.GetEffectRoot() if pSet is not None else None

        point = ship.GetRandomPointOnModel()
        Effects.CreateDebrisSparks(1.0, point, 0, root).Play()

        count = 2
        if App.EffectController_GetEffectLevel() >= App.EffectController.MEDIUM:
            count = 4
        for _ in range(count):
            Effects.CreateDebrisExplosion(
                radius, BLAST_LIFE, ship.GetRandomPointOnModel(), 1, root).Play()
        _light(ship, radius)
        _death_sound(ship)
    except Exception as _e:
        dev_mode.log_swallowed("death cascade final barrage", _e)


def _debris_explosion(ship, point, size) -> None:
    """BC: CreateDebrisExplosion(fRadius * 0.25, 1.5, pEmitPos, 1, GetNode())."""
    import Effects
    Effects.CreateDebrisExplosion(size, BLAST_LIFE, point, 1, ship.GetNode()).Play()


def _death_sound(ship) -> None:
    """The ship's authored death-explosion sound group (ShipProperty)."""
    import App
    import Effects
    pSet = ship.GetContainingSet()
    if pSet is None:
        return
    action = App.TGSoundAction_Create(Effects.GetDeathExplosionSound(ship), 0,
                                      pSet.GetName())
    action.SetNode(ship.GetNode())
    action.Play()


def _light(ship, size_gu: float) -> None:
    """A dynamic light for one blast, so the cascade actually lights nearby
    hulls.

    Every blast is lit, not just the carving ones: with a 1.5 s light life and
    BC's 0.225 s mean spacing that is only ~7 alive at once per dying ship, and
    `host_loop._budgeted_dynamic_lights` caps the category regardless. Lighting
    the 30% subset instead would make whether the first frame of a death is lit
    a coin flip."""
    from engine.appc import explosion_lights
    explosion_lights.register(ship, size_gu=size_gu, count=1,
                              spacing_s=0.0, life_s=BLAST_LIFE)
