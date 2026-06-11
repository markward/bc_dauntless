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
