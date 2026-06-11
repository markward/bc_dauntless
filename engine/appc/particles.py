# engine/appc/particles.py
"""Real particle controllers behind the SDK Effects.py factory names (Spec A1).

A controller stores keyframe curves + emit params; it does NOT simulate
particles. The renderer (ParticlePass) derives every particle analytically
from these fields each frame. See
docs/superpowers/specs/2026-06-11-particle-backend-a1-smoke-design.md.
"""


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
    def CreateTarget(self, path):      self._texture_path = path
    def SetEmitFromObject(self, obj):  self._emit_from = obj
    def AttachEffect(self, node):      self._attach_node = node
    def SetEmitPositionAndDirection(self, pos, d):
        self._emit_pos = pos
        self._emit_dir = d

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
        return min(explicit, self._effect_life_time)

    def stop_emitting(self):
        self._stop_age = self._effect_age

    def has_live_particles(self):
        max_life = self._emit_life + max(0.0, self._emit_life_variance)
        return self._effective_stop_age() + max_life > self._effect_age


# ---- active registry -------------------------------------------------------

_active = []   # list[AnimTSParticleController]


def reset():
    """Drop all active controllers (mission swap / load)."""
    _active.clear()


def active_count():
    return len(_active)


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
    particles have all expired."""
    dt = float(dt)
    survivors = []
    for c in _active:
        c._effect_age += dt
        if c._effect_age <= c._effect_life_time or c.has_live_particles():
            survivors.append(c)
    _active[:] = survivors


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
    if c._emit_from is not None and resolve_attach is not None:
        r = resolve_attach(c._emit_from)
        if r is not None:
            instance_id = r.get("instance_id")
            emit_vel_world = tuple(r.get("velocity", (0.0, 0.0, 0.0)))
            # emit_pos/emit_dir stay body-frame; the pass resolves them.
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
        "color_keys":        list(c._color_keys),
        "alpha_keys":        list(c._alpha_keys),
        "size_keys":         list(c._size_keys),
        "texture_path":      c._texture_path,
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

    def Stop(self):
        deregister(self._controller)

    def GetController(self):
        return self._controller


def AnimTSParticleController_Create():
    return AnimTSParticleController()


def EffectAction_Create(controller):
    return EffectAction(controller)
