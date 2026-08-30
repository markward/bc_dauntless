import types
import pytest

from engine.appc import hull_hit_smoke, particles
from engine.appc.math import TGPoint3


class _RNG:
    """Deterministic App.g_kSystemWrapper.GetRandomNumber stand-in.
    Returns queued values in order; falls back to `default` when drained."""
    def __init__(self, values, default=0):
        self._values = list(values)
        self._default = default
        self.calls = []

    def GetRandomNumber(self, n):
        self.calls.append(n)
        return self._values.pop(0) if self._values else self._default


@pytest.fixture
def captured(monkeypatch):
    """Capture the CreateSmokeHigh call args; return a dict updated on emit."""
    box = {}

    def fake_create(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo):
        box.update(dict(fVelocity=fVelocity, fLife=fLife, fSize=fSize,
                        emit_from=pEmitFrom, emit_pos=kEmitPos, emit_dir=kEmitDir,
                        attach_to=pAttachTo))
        controller = types.SimpleNamespace(
            SetInheritsVelocity=lambda on: box.__setitem__("inherit", on))
        return types.SimpleNamespace(
            GetController=lambda: controller,
            Start=lambda: box.__setitem__("started", True))

    fake_effects = types.SimpleNamespace(CreateSmokeHigh=fake_create)
    monkeypatch.setitem(__import__("sys").modules, "Effects", fake_effects)
    # Detail defaults HIGH; world_to_body returns a fixed body anchor.
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    monkeypatch.setattr(hull_hit_smoke.host_io, "world_to_body",
                        lambda iid, p, n: ((0.1, 0.2, 0.3), (0.0, 0.0, 1.0)))
    return box


@pytest.fixture(autouse=True)
def _clear_throttle():
    """The beam throttle is keyed by id(ship), and these tests reuse the
    interned string "ship" as their ship — so without this the first test to
    emit would silence every later one."""
    hull_hit_smoke.reset()
    yield
    hull_hit_smoke.reset()


def _emit(rng_values, weapon, monkeypatch, ship_instances=None):
    if ship_instances is None:
        ship_instances = {"ship": 7}
    rng = _RNG(rng_values)
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        weapon, ship_instances=ship_instances)
    return rng


def test_torpedo_emits_below_threshold(captured, monkeypatch):
    # roll 1 < 2  -> emit ; then fLife roll 5 -> 2.0 + 0.5
    _emit([1, 5], "torpedo", monkeypatch)
    assert captured.get("started") is True
    assert captured["fVelocity"] == 0.2
    assert captured["fSize"] == 0.3
    assert captured["fLife"] == pytest.approx(2.5)
    assert captured["emit_pos"] == (0.1, 0.2, 0.3)      # body-frame anchor
    assert captured["emit_dir"] == (0.0, 0.0, 1.0)
    assert captured["emit_from"] == "ship"
    assert captured["inherit"] == 0                     # released into world space


def test_torpedo_silent_at_threshold(captured, monkeypatch):
    _emit([2], "torpedo", monkeypatch)                  # 2 >= 2 -> no emit
    assert "started" not in captured


def test_phaser_threshold_is_three(captured, monkeypatch):
    _emit([2, 0], "phaser", monkeypatch)                # 2 < 3 -> emit
    assert captured.get("started") is True


def test_unknown_weapon_never_emits(captured, monkeypatch):
    _emit([0], None, monkeypatch)
    assert "started" not in captured


def test_detail_below_medium_suppresses(captured, monkeypatch):
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.LOW)
    _emit([0], "torpedo", monkeypatch)
    assert "started" not in captured


def test_missing_normal_skips(captured, monkeypatch):
    rng = _RNG([0, 0])
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), None, "torpedo",
        ship_instances={"ship": 7})
    assert "started" not in captured


def test_no_instance_skips(captured, monkeypatch):
    _emit([0, 0], "torpedo", monkeypatch, ship_instances={})   # ship not mapped
    assert "started" not in captured


def test_ship_instances_none_skips(captured, monkeypatch):
    rng = _RNG([0, 0])
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0), "torpedo")
    assert "started" not in captured


# ── Beam throttle ──────────────────────────────────────────────────────────
# combat.apply_hit dispatches once per TICK for a continuous phaser, so
# maybe_emit was rolling 60x/s where stock BC's PhaserHullHit handler sees one
# hull-hit event per 0.5 s beam pulse. Each passing roll starts a 10.3 s
# emitter, so the artefact compounds into a permanent smoke stream.


class _Clock:
    """Monkeypatchable game-time stand-in for hull_hit_smoke._now."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(hull_hit_smoke, "_now", c)
    return c


def _beam(monkeypatch, ship="ship", source="attacker", weapon="phaser"):
    """One weapon-impact tick. RNG always passes the roll, so the ONLY thing
    that can suppress an emit is the throttle."""
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", _RNG([], default=0))
    hull_hit_smoke.maybe_emit(
        ship, TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        weapon, ship_instances={ship: 7}, source=source)


def test_sustained_beam_rolls_once_per_interval(captured, clock, monkeypatch):
    """A 1 s beam at 60 Hz gets 3 rolls (t=0, 0.5, 1.0), not 61."""
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))
    for tick in range(61):
        clock.t = tick / 60.0
        _beam(monkeypatch)
    assert len(emits) == 3


def test_beam_throttle_is_per_attacker(captured, clock, monkeypatch):
    """Two ships beaming the same target each get their own pulse cadence —
    being swarmed must look worse than being hit by one attacker."""
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))
    _beam(monkeypatch, source="attacker_a")
    _beam(monkeypatch, source="attacker_b")
    assert len(emits) == 2


def test_beam_throttle_is_per_target(captured, clock, monkeypatch):
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))
    _beam(monkeypatch, ship="ship_a")
    _beam(monkeypatch, ship="ship_b")
    assert len(emits) == 2


def test_torpedoes_are_not_throttled(captured, clock, monkeypatch):
    """Torpedoes already arrive at stock's event rate — one dispatch per
    discrete impact — so a salvo landing inside one interval must still puff
    per hit. Only the per-tick beam path is the artefact."""
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))
    for _ in range(5):
        _beam(monkeypatch, weapon="torpedo")
    assert len(emits) == 5


def test_reset_clears_beam_throttle(captured, clock, monkeypatch):
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))
    _beam(monkeypatch)
    _beam(monkeypatch)
    assert len(emits) == 1
    hull_hit_smoke.reset()
    _beam(monkeypatch)
    assert len(emits) == 2


def test_throttle_gates_before_the_roll(captured, clock, monkeypatch):
    """The throttle must run BEFORE the probability roll, so a suppressed tick
    does not consume an RNG draw. Rolling first and throttling after would emit
    on ~every interval instead of ~30% of them."""
    rng = _RNG([], default=0)
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke", lambda *a: None)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        "phaser", ship_instances={"ship": 7}, source="attacker")
    draws_after_first = len(rng.calls)
    hull_hit_smoke.maybe_emit(     # same interval -> throttled
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        "phaser", ship_instances={"ship": 7}, source="attacker")
    assert len(rng.calls) == draws_after_first


def test_emitted_puff_lives_in_world_space(monkeypatch):
    """Puffs must be released into world space, not pinned to the ship.

    Stock attaches the smoke geometry to the SET's world-space effect root
    (`pSet.GetEffectRoot()`), so a moving hull leaves a trail. Our particle pass
    expresses "particle lives in world space" as inherit == 0: it back-projects
    the emitter's motion out of each particle via
    `- emit_vel_world * (1 - inherit) * age` (particle_pass.cc). Stock
    CreateSmokeHigh's own `SetInheritsVelocity(1)` cancels that term, pinning
    every puff to the ship's current transform (the cloud rides the hull).

    Uses the REAL Effects factory + particle controller, so this asserts the
    value the renderer actually consumes.
    """
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", _RNG([5]))
    particles.reset()
    hull_hit_smoke._emit_smoke("ship", (0.1, 0.2, 0.3), (0.0, 0.0, 1.0))
    assert particles.active_count() == 1
    assert particles._active[0]._inherit == 0.0
