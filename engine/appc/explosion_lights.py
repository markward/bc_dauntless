"""Dynamic point lights for death-explosion fireballs.

BC's death explosion is a SPRITE-ONLY effect: the fireball reads bright but
contributes nothing to the shading of hulls near it, so a ship alongside a
detonation is lit exactly as if nothing had happened. This module registers a
short-lived point light per blast so the fireball actually casts onto nearby
hulls.

WHY A SCHEDULE RATHER THAN A PER-PUFF HOOK. The particle backend is
*analytic*: a controller stores keyframe curves and the renderer derives every
puff from them each frame (see engine/appc/particles.py's module docstring), so
there is no per-puff callback for Python to hang a light on. What Python does
know is the schedule -- ship_death spawns a fixed number of blasts evenly
across the throes window -- and that is deterministic, so the blast times are
reproduced here rather than observed.

The schedule itself is NOT duplicated: `engine.appc.death_cascade` owns BC's
blast constants (spacing, BLAST_LIFE, and the fireball size formula) and calls
register() once per blast as it fires. This module owns only the LIGHT tunables
below. Two homes, one for each concern, so neither can drift into a second
interpreter of the other's numbers.

TUNING: every look-affecting value lives in this file and nowhere else, so
retuning after a live look is a Python edit with no rebuild -- the same rule
the depth-of-field work settled on.
"""

# ── Light tunables — the only home for these numbers ─────────────────────
# Deliberately conservative; expect to calibrate up and then back down after a
# live look.
PEAK_INTENSITY = 3.0      # intensity at the top of the bloom.
                          #
                          # MEASURED, not guessed: native/tests/renderer/
                          # explosion_light_frame_test.cc renders a hull lit by
                          # exactly this light and reads the pixel back. Summed
                          # RGB, 765 = saturated white, 30 = the unlit baseline:
                          #     i=1.0  ->  422 at 10 GU, 293 at 20 GU
                          #     i=1.5  ->  554 at 10 GU, 424 at 20 GU
                          #     i=6.0  ->  765 at 10 GU, 752 at 20 GU (blown out)
                          # 6.0 was the original guess and clips everywhere
                          # close. 1.5 was the measured starting point; 3.0 is
                          # Mark's live-chosen value -- brighter, still short of
                          # the clipping 6.0.
RADIUS_FACTOR = 34.0      # light reach as a multiple of the fireball's drawn
                          # size.
                          #
                          # MUST clear renderer's kDynLightShipCeilingGU (40 GU)
                          # by a wide margin, and that is not a matter of taste.
                          # Below the ceiling the attenuation reference is 1, so
                          # the light falls off as 1/(d^2+1) with d in GAME UNITS
                          # -- a curve meant for lights sitting ON a hull, like
                          # the subsystem emitters. It dies within a few GU.
                          # Above the ceiling the reference grows and the light
                          # actually carries between ships.
                          #
                          # Measured, at PEAK_INTENSITY 6 and a warbird-sized
                          # fireball, effective brightness on a hull 20 GU away:
                          #   factor  3 -> radius  33 GU -> 0.011   (invisible)
                          #   factor 10 -> radius 110 GU -> 3.28
                          # The first shipped at 3 and could not be seen even
                          # with 50 ships packed together.
                          #
                          # 10 died by 100 GU, ordinary combat spacing. Raised
                          # to 20, then to 34 -- Mark's live-chosen value.
                          # Ceiling is 60; see nudge_radius_factor for what the
                          # top of that range does to the falloff.
MIN_LIGHT_RADIUS_GU = 60.0  # floor, comfortably clear of the renderer's 40 GU
                          # ship-scale ceiling. RADIUS_FACTOR alone is not
                          # enough: a shuttle's per-blast fireball (a quarter
                          # of its radius) would land at ~20 GU -- under
                          # the ceiling, on the hull-local falloff curve, and
                          # invisible. Small craft get a light that carries;
                          # capital ships still scale past this by size.
COLOR = (1.0, 0.62, 0.28)  # warm orange; r > g > b is what reads as fire
RISE_FRACTION = 0.12      # fraction of a blast's life spent brightening
DECAY_EXPONENT = 2.0      # >1 fades fast at first, then lingers

# Nudge steps for the live dev keys (engine/dev_keybindings.py). Sized as a
# sensible FRACTION of the value each moves, so a press is visible without
# being a third of the range. The intensity step was cut 1.0 -> 0.25
# alongside the 6.0 -> 1.5 recalibration, for the same reason.
PEAK_INTENSITY_STEP = 0.25
RADIUS_FACTOR_STEP = 2.0

# Live, per-session values seeded from the constants above. The dev keys move
# THESE, never the module constants: a live experiment must not become the
# shipped default by accident -- you read the number off stderr and paste it
# in deliberately. Deliberately NOT cleared by reset(), which is mission
# state; tuning survives a mission swap so a calibration session is not lost
# to loading a different mission.
_peak_intensity = PEAK_INTENSITY
_radius_factor = RADIUS_FACTOR


def nudge_peak_intensity(delta):
    """Move the bloom's peak brightness. Dev tuning only."""
    global _peak_intensity
    _peak_intensity = max(0.0, min(60.0, _peak_intensity + delta))
    return _peak_intensity


def nudge_radius_factor(delta):
    """Move the light's reach, as a multiple of the fireball's drawn size.

    Ceiling raised 20 -> 60 on request after a live look. Worth knowing what
    the top of that range does: the renderer's attenuation reference GROWS with
    radius above the 40 GU ship-scale ceiling, so a very large radius flattens
    the falloff rather than merely extending it. At factor 60 a warbird
    fireball reaches 660 GU and lights nearly everything on screen about
    equally, which reads as the whole scene brightening rather than as a blast
    throwing light. If that is the look, it is available.
    """
    global _radius_factor
    _radius_factor = max(0.0, min(60.0, _radius_factor + delta))
    return _radius_factor


def tuning_values():
    """The whole live tuning state, for a one-line stderr readout."""
    return (("peak_intensity", _peak_intensity),
            ("radius_factor", _radius_factor))


# Below this an entry contributes nothing worth the per-instance top-K scan
# that runs for every hull on screen, so it is dropped rather than emitted.
_MIN_EMITTED_INTENSITY = 1e-3

# Blasts that have been born and are still glowing.
# Each: {"position": (x, y, z), "radius": float, "age": float, "life": float}
_active: list[dict] = []

# Death sequences that still have blasts to bear.
# Each: {"ship", "size_gu", "remaining", "spacing_s", "life_s", "next_at"}
_sequences: list[dict] = []


def register(ship, *, size_gu, count, spacing_s, life_s) -> None:
    """Schedule `count` blasts for a dying ship, `spacing_s` apart.

    Mirrors the emission ship_death sets up on the particle controller: births
    land at i*spacing for i in 0..count-1, so the first blast is at t=0 and
    fires on the next advance().

    `size_gu` is the fireball's drawn size, computed by ship_death -- passed in
    rather than recomputed here so this file never becomes a second
    interpreter of that formula.
    """
    if count <= 0 or size_gu <= 0.0 or life_s <= 0.0:
        return
    _sequences.append({
        "ship":      ship,
        "size_gu":   float(size_gu),
        "remaining": int(count),
        "spacing_s": float(spacing_s),
        "life_s":    float(life_s),
        "next_at":   0.0,      # blast 0 is immediate
    })


def advance(dt: float) -> None:
    """Bear any blasts whose time has come, then age the live ones."""
    if dt <= 0.0:
        return

    for seq in _sequences:
        seq["next_at"] -= dt
        # A long frame can cross more than one birth time; bear them all
        # rather than silently dropping blasts on a stutter.
        while seq["remaining"] > 0 and seq["next_at"] <= 0.0:
            _bear(seq)
            seq["remaining"] -= 1
            seq["next_at"] += seq["spacing_s"]
    _sequences[:] = [s for s in _sequences if s["remaining"] > 0]

    for blast in _active:
        blast["age"] += dt
    _active[:] = [b for b in _active if b["age"] < b["life"]]


def _bear(seq) -> None:
    """Add one blast at the ship's CURRENT world position.

    Position is captured here and then fixed: the hull is removed after the
    throes while the last blast is still burning (ship_death anchors it at the
    wreck site), so holding the ship would leave a dangling reference. A
    fireball barely moves relative to its own size, so a fixed point is a fair
    reading of a puff that tracked the hull.
    """
    pos = _world_position(seq["ship"])
    if pos is None:
        return
    _active.append({
        "position": pos,
        "size_gu":  seq["size_gu"],
        "age":      0.0,
        "life":     seq["life_s"],
    })


def _world_position(ship):
    """(x, y, z) for `ship`, or None if it cannot be read.

    Every scheduled birth lands while the hull still exists, so None is not
    expected -- but this runs inside the per-frame render path, where an
    exception would take the frame down rather than merely lose a light.
    """
    try:
        get_loc = getattr(ship, "GetWorldLocation", None)
        if not callable(get_loc):
            return None
        p = get_loc()
        if p is None:
            return None
        return (float(p.x), float(p.y), float(p.z))
    except Exception:
        return None


def envelope(t_norm: float) -> float:
    """Intensity scale over a blast's normalised life, in [0, 1].

    Fast bloom, slow fade -- a fireball reaches full brightness almost at once
    and then falls away, so the peak sits early rather than mid-life.
    """
    if t_norm <= 0.0 or t_norm >= 1.0:
        return 0.0
    if t_norm < RISE_FRACTION:
        return t_norm / RISE_FRACTION
    decay = (t_norm - RISE_FRACTION) / (1.0 - RISE_FRACTION)
    return (1.0 - decay) ** DECAY_EXPONENT


def render_data() -> list:
    """Light descriptors for the current frame.

    Shape mirrors _build_dynamic_light_render_data's torpedo descriptors:
    position / color / radius / intensity.
    """
    out = []
    for blast in _active:
        # Radius and intensity resolve HERE rather than at birth, so a live
        # nudge moves blasts that are already burning instead of only the
        # next one -- which is the difference between tuning by eye and
        # tuning by waiting for another ship to die.
        intensity = _peak_intensity * envelope(blast["age"] / blast["life"])
        if intensity <= _MIN_EMITTED_INTENSITY:
            continue
        out.append({
            "position":  blast["position"],
            "color":     COLOR,
            "radius":    max(blast["size_gu"] * _radius_factor,
                                 MIN_LIGHT_RADIUS_GU),
            "intensity": intensity,
        })
    return out


def reset() -> None:
    """Clear every blast and pending sequence (mission swap / test teardown).

    Called from the host loop's swap drain beside ship_death.reset(). Without
    it a ship that died in the previous mission would keep lighting the next
    one from its old world position.
    """
    _active.clear()
    _sequences.clear()
