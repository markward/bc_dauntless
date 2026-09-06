"""Depth-of-field focus control — and the ONE home for every DOF tuning value.

Deep focus is the default: with no subject the solver reports blend 0 and the
host skips the DOF pass entirely, so the frame is byte-identical to the
pre-DOF renderer. Focus exists only when something has deliberately been
focused on, which is what keeps DOF a directorial signal rather than a blanket
filter that would fight readability.

TUNING. The four lens constants below are pushed to the shader as uniforms, so
editing them needs NO REBUILD -- change the number, relaunch, look. Under
--developer two key pairs nudge the live lens (see engine/dev_keybindings.py)
and print all four values to stderr, so a value can be found in one session
rather than three rebuild-and-relaunch rounds:

    ','  '.'   MAX_RADIUS_FRAC  -- overall blur magnitude, the "don't
                                  over-blur" control
    ';'  "'"   FAR_CEILING      -- how much the distant background is allowed
                                  to mush

Those are the two knobs that actually move the picture. The STRENGTHS are NOT
on keys, and the reason is worth keeping: the far field is ceiling-bound, not
strength-bound. A background object at 10x the focus distance has dd = 0.9, so
FAR_STRENGTH has to fall below 0.44 before the ceiling stops clipping it --
six presses of a 0.1 strength nudge with ZERO visible change, and no upward
press can ever affect the distant background at all. On the near side anything
at z <= focus/2 is already clamped at the hard -1, so raising NEAR_STRENGTH
above 1.0 only widens a narrow band. nudge_strength() is kept for anyone who
wants it from a console, but it is not what "tweak the strength" means here.

Spec: docs/superpowers/specs/2026-09-06-depth-of-field-design.md
"""
import math

# ── Lens shape — pushed to the shader as uniforms ────────────────────────
# Deliberately conservative. Expect to calibrate UP and then back down after a
# live look, the way the directional ambient gradient went 0.6 -> 1.0 -> 0.8.
NEAR_STRENGTH = 1.0      # foreground defocus gain
FAR_STRENGTH = 1.0       # background defocus gain, before the ceiling
FAR_CEILING = 0.4        # hard cap on far-field CoC -- the anti-mush knob
MAX_RADIUS_FRAC = 0.008  # max blur radius as a fraction of screen height

# ── Focus behaviour — consumed here, never reaches the shader ────────────
RACK_TAU_S = 0.35        # focus-pull time constant
BLEND_TAU_S = 0.25       # engage/release ramp

# ── Bounds and step sizes for the live dev nudges ────────────────────────
STRENGTH_MIN = 0.0
STRENGTH_MAX = 3.0

# MAX_RADIUS_FRAC. At 1080p the default 0.008 is a 8.6 px max blur radius, so a
# 0.002 step is ~2.2 px -- a 25% change per press, visible immediately, and four
# presses either doubles it or takes it to zero. A smaller step would reproduce
# the "press it six times and nothing happens" problem the strength keys had.
# The ceiling of 0.04 is 43 px at 1080p: far past anything usable, which is what
# a bound is for.
MAX_RADIUS_FRAC_MIN = 0.0
MAX_RADIUS_FRAC_MAX = 0.04
MAX_RADIUS_FRAC_STEP = 0.002

# FAR_CEILING is the value this design is least confident in, so it gets the
# other key pair. Default 0.4, step 0.05 -- eight presses down reaches 0.0 (a
# perfectly sharp background), twelve up reaches 1.0, where the ceiling never
# binds and the far field is governed by FAR_STRENGTH alone. 1.0 is the natural
# maximum: it is the magnitude the NEAR side hard-clamps at.
FAR_CEILING_MIN = 0.0
FAR_CEILING_MAX = 1.0
FAR_CEILING_STEP = 0.05

# Below this the blend is snapped to exactly 0 so the host can skip the pass.
# An exponential ease is asymptotic and would otherwise leave DOF running
# forever at an invisible strength.
_BLEND_EPSILON = 1e-3

# A subject closer than this is treated as no subject: the thin-lens term
# degenerates as focus approaches the near plane.
MIN_FOCUS_GU = 0.5

# ...and so is a subject at or beyond the camera's FAR plane, which is
# 5000 GU on the exterior view (host_loop's r.set_camera(near=1.0, far=5000.0)).
#
# This is not a tidiness bound, it is the anti-mush bound. The CoC term is
# dd = 1 - focus/z, so with focus >= far EVERY visible pixel has dd < 0 -- the
# whole frame is near field -- and everything nearer than focus/2 clamps to the
# hard -1, i.e. MAXIMUM blur. The far ceiling cannot help, because no part of
# the frame is far field. The result is the entire scene mushed behind a sharp
# starfield: exactly the over-blur this feature exists to avoid.
#
# It is reachable in normal play, not a theoretical edge: sensor_detection's
# FALLBACK_RANGE_GU is 30000 GU, six times the far plane, and a lock is only
# dropped when can_detect fails. Racking past infinity has no meaning anyway,
# so a subject out there reads as NO subject and the lens releases to deep
# focus -- the same behaviour as having no target at all.
MAX_FOCUS_GU = 5000.0


def _ease(current, target, dt, tau):
    """Frame-rate-independent exponential approach to `target`."""
    if tau <= 0.0:
        return target      # zero time constant: instantaneous by definition
    if dt <= 0.0:
        return current     # no time passed (paused frame): nothing moves
    return current + (target - current) * (1.0 - math.exp(-dt / tau))


def focus_subject(player, camera_mode=None):
    """The object the lens should focus on, or None for deep focus.

    Priority: the active camera mode names its own subject (only TorpCameraMode
    does, returning the torpedo it is riding), otherwise the player's selected
    target, otherwise nothing. The hook is optional -- most modes will never
    grow one -- so its absence falls through rather than raising.
    """
    if camera_mode is not None:
        hook = getattr(camera_mode, "focus_subject", None)
        if callable(hook):
            subject = hook()
            if subject is not None:
                return subject
    if player is not None:
        get_target = getattr(player, "GetTarget", None)
        if callable(get_target):
            return get_target()
    return None


def subject_distance_gu(eye, subject):
    """Distance in game units from the camera to `subject`, or None.

    Both ships and torpedoes expose GetWorldLocation(); anything that does not
    -- or that hands back something whose components are not numbers, which a
    stubbed attribute will -- is treated as unfocusable rather than raising,
    because a focus failure must never take the frame down. This runs deep in
    the render path with no `except` between it and process exit, so "must
    never" is literal: catch broadly and report no subject.
    """
    if subject is None:
        return None
    get_loc = getattr(subject, "GetWorldLocation", None)
    if not callable(get_loc):
        return None
    try:
        p = get_loc()
        if p is None:
            return None
        dx = float(p.x) - eye[0]
        dy = float(p.y) - eye[1]
        dz = float(p.z) - eye[2]
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
    except Exception:
        # A missing/stub .x, a non-numeric component, a GetWorldLocation that
        # raises: all mean "cannot focus on this", never "take the frame down".
        return None
    if not math.isfinite(d):
        return None
    return d


class FocusSolver:
    """Eases the lens toward the current subject and reports the pass's params.

    Lens values are seeded from the module constants and held per instance, so
    a live dev nudge is per-session and never writes back to the module.
    """

    def __init__(self):
        self.near_strength = NEAR_STRENGTH
        self.far_strength = FAR_STRENGTH
        self.far_ceiling = FAR_CEILING
        self.max_radius_frac = MAX_RADIUS_FRAC
        # Held as a dioptre (1/distance); 0 means "not focused on anything".
        self._inv_focus = 0.0
        self._blend = 0.0

    @property
    def focus_gu(self):
        """Current focus distance in game units; 0.0 when disengaged."""
        return (1.0 / self._inv_focus) if self._inv_focus > 0.0 else 0.0

    @property
    def blend(self):
        """0..1 engage ramp. Exactly 0 means the host skips the pass."""
        return self._blend

    def update(self, distance_gu, dt):
        """Advance one frame toward `distance_gu` (None = deep focus)."""
        if (distance_gu is not None
                and MIN_FOCUS_GU < distance_gu < MAX_FOCUS_GU):
            target_inv = 1.0 / distance_gu
            if self._inv_focus <= 0.0:
                # First acquisition SNAPS the distance. Racking from nowhere
                # would swing the lens wildly the moment a target is selected;
                # what should ease in is the engagement, not the distance.
                self._inv_focus = target_inv
            else:
                # Eased in DIOPTRES, not distance. A real focus pull moves the
                # barrel in 1/distance, and easing linear distance would make a
                # rack outward take visibly longer than the same rack inward.
                self._inv_focus = _ease(self._inv_focus, target_inv,
                                        dt, RACK_TAU_S)
            self._blend = _ease(self._blend, 1.0, dt, BLEND_TAU_S)
        else:
            self._blend = _ease(self._blend, 0.0, dt, BLEND_TAU_S)
            if self._blend < _BLEND_EPSILON:
                self._blend = 0.0
                self._inv_focus = 0.0
        return self

    def nudge_strength(self, delta):
        """Move both defocus strengths by `delta`, clamped. Dev tuning only.

        Deliberately NOT on a keybinding -- see the module docstring for why
        the strengths are the wrong knob to hand someone calibrating live.
        Kept because they are still real lens parameters.
        """
        self.near_strength = min(STRENGTH_MAX,
                                 max(STRENGTH_MIN, self.near_strength + delta))
        self.far_strength = min(STRENGTH_MAX,
                                max(STRENGTH_MIN, self.far_strength + delta))
        return (self.near_strength, self.far_strength)

    def nudge_max_radius_frac(self, delta):
        """Move the overall blur magnitude by `delta`, clamped. Dev tuning only.

        The primary "don't over-blur" control: it scales the whole kernel, so
        one press changes every defocused pixel in the frame.
        """
        self.max_radius_frac = min(
            MAX_RADIUS_FRAC_MAX,
            max(MAX_RADIUS_FRAC_MIN, self.max_radius_frac + delta))
        return self.max_radius_frac

    def nudge_far_ceiling(self, delta):
        """Move the far-field CoC cap by `delta`, clamped. Dev tuning only.

        The background-mush control. Lower keeps distant ships readable; at
        FAR_CEILING_MAX the cap never binds and the far field is governed by
        far_strength alone.
        """
        self.far_ceiling = min(FAR_CEILING_MAX,
                               max(FAR_CEILING_MIN, self.far_ceiling + delta))
        return self.far_ceiling

    def lens_values(self):
        """The whole live lens, ordered for a one-line readout.

        All four are printed on every nudge so the complete state can be read
        off in one line and pasted back into the module constants above --
        printing only the knob that moved makes the developer reconstruct the
        rest from memory across a session of presses.
        """
        return (("max_radius_frac", self.max_radius_frac),
                ("far_ceiling", self.far_ceiling),
                ("near_strength", self.near_strength),
                ("far_strength", self.far_strength))
