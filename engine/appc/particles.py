# engine/appc/particles.py
"""Real particle controllers behind the SDK Effects.py factory names (Spec A1).

A controller stores keyframe curves + emit params; it does NOT simulate
particles. The renderer (ParticlePass) derives every particle analytically
from these fields each frame. See
docs/superpowers/specs/2026-06-11-particle-backend-a1-smoke-design.md.
"""
import random as _random

# Known sprite-sheet textures, by lowercase basename -> (cols, rows).
# BC's stock explosion sheets are 256x256 with an 8x8 grid: 8 animation
# frames across, 8 explosion variants down (B is the greyscale twin of A).
# CreateTarget applies these automatically; SetTextureCells can override.
_KNOWN_SHEET_TEXTURES = {
    "explosiona.tga": (8, 8),
    "explosionb.tga": (8, 8),
}


class AnimTSParticleController:
    def __init__(self):
        self._color_keys = []   # (t, r, g, b)
        self._alpha_keys = []   # (t, a)
        self._size_keys  = []   # (t, s)
        self._emit_velocity = 1.0
        self._angle_variance = 0.0
        self._emit_life = 1.0
        self._emit_life_variance = 0.0
        self._emit_frequency = 0.05
        self._effect_life_time = 1.0
        self._inherit = 1.0
        self._draw_old_to_new = 1
        self._texture_path = ""
        self._emit_from = None     # AV object / ship handle (SetEmitFromObject)
        self._attach_node = None   # AttachEffect target
        self._emit_pos = None      # body-frame (attached) or world (SetEmitPositionAndDirection)
        self._emit_dir = None
        self._emit_radius = 0.0
        self._rv_cone = 0.0
        self._rv_speed = 0.0
        self._blend_mode = 0   # 0 = alpha (A1), 1 = additive
        # Texture-sheet animation grid. 1x1 = whole texture (default; hit VFX,
        # plumes). >1 means the texture is an N-column (frames) x M-row
        # (variants) sprite sheet; the renderer steps a per-particle cell
        # (frame from age, row from a per-particle hash).
        self._atlas_cols = 1
        self._atlas_rows = 1
        # Stable per-emitter hash seed. The renderer derives ALL per-particle
        # randomness (jitter, birth offset, variant row) from this, NOT from
        # the emitter's world position — a moving emitter must not re-roll
        # its particles every frame.
        self._seed = _random.random()
        # runtime, owned by the registry
        self._effect_age = 0.0
        self._stop_age = None      # None => still emitting

    # ---- SDK setters --------------------------------------------------
    def AddColorKey(self, t, r, g, b): self._color_keys.append((t, r, g, b))
    def AddAlphaKey(self, t, a):       self._alpha_keys.append((t, a))
    def AddSizeKey(self, t, s):        self._size_keys.append((t, s))
    def SetEmitVelocity(self, v):      self._emit_velocity = v
    def SetAngleVariance(self, deg):   self._angle_variance = deg
    def SetEmitLife(self, l):          self._emit_life = l
    def SetEmitLifeVariance(self, v):  self._emit_life_variance = v
    def SetEmitFrequency(self, f):     self._emit_frequency = f
    def SetEffectLifeTime(self, t):    self._effect_life_time = t
    def SetInheritsVelocity(self, on): self._inherit = 1.0 if on else 0.0
    def SetDrawOldToNew(self, on):     self._draw_old_to_new = 1 if on else 0
    def CreateTarget(self, path):
        self._texture_path = path
        # Auto-detect known sprite-sheet textures so every SDK Effects
        # caller (weapon-hit explosions, smoke, plumes) animates frames
        # instead of billboarding the whole 8x8 grid. SDK scripts never
        # declare the grid — the original engine knew it natively.
        base = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
        cells = _KNOWN_SHEET_TEXTURES.get(base)
        if cells is not None:
            self._atlas_cols, self._atlas_rows = cells
    def SetTextureCells(self, cols, rows):
        """Declare the target texture as a `cols` x `rows` sprite sheet:
        `cols` animation frames per variant, `rows` variants. Default 1x1
        (whole texture). The renderer animates frames over each particle's
        life and picks a random row per particle for variety."""
        self._atlas_cols = max(1, int(cols))
        self._atlas_rows = max(1, int(rows))
    def SetEmitFromObject(self, obj):  self._emit_from = obj
    def AttachEffect(self, node):      self._attach_node = node
    def SetEmitPositionAndDirection(self, pos, d):
        self._emit_pos = pos
        self._emit_dir = d

    def SetEmitRadius(self, r):            self._emit_radius = r
    def SetUpRandomVelocity(self, cone, speed):
        self._rv_cone = cone
        self._rv_speed = speed
    def SetTargetAlphaBlendModes(self, src, dst):
        # The SDK calls this only to request the additive ONE/INV_SRC_ALPHA path
        # (SetTargetAlphaBlendModes(0, 7)). Any call => additive blend.
        self._blend_mode = 1

    def __getattr__(self, name):
        # Tolerate any other SDK Set*/Add* call as a harmless no-op so future
        # Effects.py code never crashes the controller. Real attributes are
        # found before __getattr__ fires.
        if name.startswith("Set") or name.startswith("Add"):
            return lambda *a, **k: None
        raise AttributeError(name)

    # ---- analytic lifecycle (used by the registry + the Spec B handle) -
    def _effective_stop_age(self):
        explicit = self._stop_age if self._stop_age is not None else float("inf")
        cap = min(explicit, self._effect_life_time)
        duration = getattr(self, "_duration", None)
        if duration is not None:
            cap = min(cap, duration)
        return cap

    def stop_emitting(self):
        self._stop_age = self._effect_age

    def has_live_particles(self):
        max_life = self._emit_life + max(0.0, self._emit_life_variance)
        return self._effective_stop_age() + max_life > self._effect_age


# ---- EffectController ------------------------------------------------------

class EffectController:
    """Mirror of App.EffectController: quality-level enum + getter."""
    LOW    = 0
    MEDIUM = 1
    HIGH   = 2


def EffectController_GetEffectLevel():
    """Always return HIGH so the SDK takes the high-detail particle path."""
    return EffectController.HIGH


# ---- active registry -------------------------------------------------------

_active    = []   # list[AnimTSParticleController]
_tickables = []   # list[objects with .tick(dt) / .is_finished()]


def reset():
    """Drop all active controllers and tickables (mission swap / load)."""
    _active.clear()
    _tickables.clear()


def active_count():
    return len(_active)


def register_tickable(obj):
    """Register an object with .tick(dt) / .is_finished() for per-frame advance."""
    if obj not in _tickables:
        _tickables.append(obj)


def register(controller):
    controller._effect_age = 0.0
    controller._stop_age = None
    if controller not in _active:
        _active.append(controller)


def deregister(controller):
    if controller in _active:
        _active.remove(controller)


def advance(dt):
    """Age every active controller; prune those past EffectLifeTime whose
    particles have all expired.  Also ticks registered tickables (sequences)
    and prunes finished ones."""
    dt = float(dt)
    survivors = []
    for c in _active:
        c._effect_age += dt
        if c._effect_age <= c._effect_life_time or c.has_live_particles():
            survivors.append(c)
    _active[:] = survivors
    live = []
    for s in _tickables:
        s.tick(dt)
        if not s.is_finished():
            live.append(s)
    _tickables[:] = live


def _vec3(p, default=(0.0, 0.0, 0.0)):
    if p is None:
        return default
    if hasattr(p, "x"):
        return (p.x, p.y, p.z)
    return (p[0], p[1], p[2])


def _descriptor_for(c, resolve_attach):
    instance_id = None
    emit_vel_world = (0.0, 0.0, 0.0)
    emit_pos = _vec3(c._emit_pos)
    emit_dir = _vec3(c._emit_dir, default=(0.0, -1.0, 0.0))
    if c._emit_from is not None:
        r = resolve_attach(c._emit_from) if resolve_attach is not None else None
        if r is not None:
            instance_id = r.get("instance_id")
            emit_vel_world = tuple(r.get("velocity", (0.0, 0.0, 0.0)))
            # emit_pos/emit_dir stay body-frame; the pass resolves them.
        else:
            # Attach target has no render instance (e.g. ship removed at the
            # end of its death sequence). Anchor the effect at the object's
            # last world location so it finishes playing at the wreck site
            # instead of snapping to the body-frame origin.
            try:
                wp = c._emit_from.GetWorldLocation()
                emit_pos = (float(wp.x), float(wp.y), float(wp.z))
            except Exception:
                pass
    return {
        "instance_id":       instance_id,
        "emit_pos":          emit_pos,
        "emit_dir":          emit_dir,
        "emit_vel_world":    emit_vel_world,
        "inherit":           float(c._inherit),
        "emit_velocity":     float(c._emit_velocity),
        "angle_variance":    float(c._angle_variance),
        "emit_life":         float(c._emit_life),
        "emit_life_variance":float(c._emit_life_variance),
        "emit_frequency":    float(c._emit_frequency),
        "effect_age":        float(c._effect_age),
        "stop_age":          float(c._effective_stop_age()),
        "draw_old_to_new":   int(c._draw_old_to_new),
        "blend_mode":            int(c._blend_mode),
        "emit_radius":           float(c._emit_radius),
        "random_velocity_cone":  float(c._rv_cone),
        "random_velocity_speed": float(c._rv_speed),
        "damping":           float(getattr(c, "_damping", 0.0)),
        "tail_length":       float(getattr(c, "_tail_length", 0.0)),
        "color_keys":        list(c._color_keys),
        "alpha_keys":        list(c._alpha_keys),
        "size_keys":         list(c._size_keys),
        "texture_path":      c._texture_path,
        "atlas_cols":        int(c._atlas_cols),
        "atlas_rows":        int(c._atlas_rows),
        "seed":              float(c._seed),
    }


def snapshot_descriptors(resolve_attach=None):
    """Build one render descriptor per active controller. `resolve_attach`
    maps an emit-from object -> {'instance_id', 'velocity'} or None."""
    return [_descriptor_for(c, resolve_attach) for c in _active]


class EffectAction:
    """Mirror of the SDK action wrapper: Start() registers the controller in
    the active set, Stop() deregisters it."""
    def __init__(self, controller):
        self._controller = controller

    def Start(self):
        register(self._controller)

    def Play(self):
        self.Start()

    def Stop(self):
        deregister(self._controller)

    def GetController(self):
        return self._controller


def AnimTSParticleController_Create():
    return AnimTSParticleController()


def ExplosionPlumeController_Create():
    """Stand-in for the SDK's ExplosionPlumeController.

    The real engine type has SetUpRandomVelocity / SetDetachEmitObject on top
    of the AnimTSParticleController API.  Our AnimTSParticleController's
    __getattr__ no-ops any unknown Set*/Add* call, so returning one here lets
    Effects.CreateExplosionPlumeHigh run without crashing while the full
    ExplosionPlumeController implementation is deferred to A2."""
    return AnimTSParticleController()


class SparkParticleController(AnimTSParticleController):
    """Spark/debris particles: damped ballistic motion + a motion-streak tail.
    SDK ctor is SparkParticleController_Create(total_life, duration, emit_rate)."""
    def __init__(self, total_life=1.0, duration=1.0, emit_rate=0.005):
        super().__init__()
        self._effect_life_time = total_life   # ctor arg 1
        self._emit_frequency = emit_rate      # ctor arg 3
        self._duration = duration             # ctor arg 2 — emission window
        self._damping = 0.0
        self._tail_length = 0.0

    def SetDamping(self, d):    self._damping = d
    def SetTailLength(self, l): self._tail_length = l


def SparkParticleController_Create(total_life=1.0, duration=1.0, emit_rate=0.005):
    return SparkParticleController(total_life, duration, emit_rate)


def EffectAction_Create(controller):
    return EffectAction(controller)


import importlib as _importlib


_SPHERICAL_ANGLE = 150.0   # wide spread approximating omni for SPHERICAL plumes


def _call_factory(factory_name, first_param, fLife, fSize, emit_from, emit_pos, emit_dir):
    """Call an SDK Effects.py factory by name and return its EffectAction.

    ``first_param`` is the first positional parameter after the standard
    preamble:
      - CreateSmokeHigh    → fVelocity
      - CreateExplosionPlumeHigh → fConeAngle

    Signature: (first_param, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo)

    WARNING — arity coupling: this helper is only valid for factories with the
    7-arg (fVel/fCone, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo)
    shape — i.e. CreateSmokeHigh and CreateExplosionPlumeHigh, the two that the
    Spec B built-in table drives.  It is NOT a general SDK-factory caller.
    CreateWeaponSmoke(fDuration, fSize, pEvent, pEffectRoot) and
    CreateDebrisSmoke(fDuration, fSize, pEmitFrom, bOwnsEmitFrom, pEffectRoot)
    have different arities and must be called directly, not through this helper.
    """
    Effects = _importlib.import_module("Effects")
    fn = getattr(Effects, factory_name)
    return fn(first_param, fLife, fSize, emit_from, emit_pos, emit_dir, emit_from)


class _ControllerHandle:
    """Spec B handle wrapping a live controller."""
    def __init__(self, controller):
        self._c = controller

    def stop_emitting(self):
        self._c.stop_emitting()

    def has_live_particles(self):
        return self._c.has_live_particles()


class ParticleBackend:
    """Spec A1 implementation of the Spec B §5 backend interface."""

    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode,
               ship=None):
        from engine.appc import subsystem_emitters as se
        # Map generic param names to the factory's leading positional.
        # CreateSmokeHigh uses fVelocity; CreateExplosionPlumeHigh uses fConeAngle.
        first_param = float(params.get("fVelocity",
                            params.get("fConeAngle", 1.0)))
        fLife = float(params.get("fLife", 1.0))
        fSize = float(params.get("fSize", 1.0))
        action = _call_factory(factory, first_param, fLife, fSize, ship,
                               emit_pos_body, emit_dir)
        controller = action.GetController()
        if direction_mode == se.DirectionMode.SPHERICAL:
            controller.SetAngleVariance(max(controller._angle_variance,
                                           _SPHERICAL_ANGLE))
        # Sustained plume: emit until explicitly stopped (large EffectLifeTime).
        controller.SetEffectLifeTime(1.0e9)
        action.Start()
        return _ControllerHandle(controller)

    def fire_one_shot(self, factory, emit_pos_body, emit_dir, ship=None):
        action = _call_factory(factory, 1.0, 1.0, 1.0, ship,
                               emit_pos_body, emit_dir)
        controller = action.GetController()
        controller.SetEffectLifeTime(min(controller._effect_life_time, 1.5))
        action.Start()
