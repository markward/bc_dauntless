# tests/unit/test_subsystem_emitters_backend.py
from engine.appc import subsystem_emitters as se


class FakeHandle:
    """Models a sustained controller: alive until stop_emitting(), then it has
    `linger` ticks of in-flight particles before has_live_particles() goes False."""
    def __init__(self, factory, params, emit_pos_body, emit_dir, direction_mode,
                 ship=None, linger=2):
        self.factory = factory
        self.params = params
        self.emit_pos_body = emit_pos_body
        self.emit_dir = emit_dir
        self.direction_mode = direction_mode
        self.ship = ship
        self.emitting = True
        self._linger = linger

    def stop_emitting(self):
        self.emitting = False

    def has_live_particles(self):
        if self.emitting:
            return True
        self._linger -= 1
        return self._linger >= 0


class FakeControllerBackend:
    """Test double for the Spec A particle-controller backend."""
    def __init__(self):
        self.created = []     # all sustained handles ever made
        self.one_shots = []   # (factory, emit_pos_body, emit_dir) death puffs

    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode,
               ship=None):
        h = FakeHandle(factory, params, emit_pos_body, emit_dir, direction_mode,
                       ship=ship)
        self.created.append(h)
        return h

    def fire_one_shot(self, factory, emit_pos_body, emit_dir, ship=None):
        self.one_shots.append((factory, emit_pos_body, emit_dir))


def test_null_backend_create_returns_inert_handle():
    b = se.NullBackend()
    h = b.create("CreateSmokeHigh", {}, (0, 0, 0), (0, -1, 0),
                 se.DirectionMode.FIXED_BODY_VECTOR)
    # NullBackend handle must satisfy the manager's queries without error.
    h.stop_emitting()
    assert h.has_live_particles() is False
    b.fire_one_shot("CreateExplosionPlumeHigh", (0, 0, 0), (0, -1, 0))  # no error


def test_fake_handle_fade_lifecycle():
    b = FakeControllerBackend()
    h = b.create("CreateSmokeHigh", {"fSize": 1.0}, (1, -2, 0), (0, -1, 0),
                 se.DirectionMode.FIXED_BODY_VECTOR)
    assert h.has_live_particles() is True
    h.stop_emitting()
    assert h.has_live_particles() is True   # linger 2 -> 1
    assert h.has_live_particles() is True   # linger 1 -> 0
    assert h.has_live_particles() is False  # linger 0 -> -1
