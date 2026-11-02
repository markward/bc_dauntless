"""BC's death cascade (engine/appc/death_cascade.py).

Ground truth is Effects.ObjectExploding (sdk/Build/scripts/Effects.py:735):

    fTotalLifeLeft = random(100)/10.0 + 5.0     # 5-15 s, unless already set
    while fExplosionTime < fTotalLifeLeft:
        CreateObjectExplosion(pObject, bSound)  # at GetRandomPointOnModel()
        fExplosionTime += random(4) * 0.15      # mean 0.225 s -> ~4-5 per second

and inside CreateObjectExplosion (Effects.py:705), the line that makes a dying
ship visibly come apart:

    if random(10) < 3:
        DeathExplosionDamage(..., fRadius / 4.0, 600.0)   # -> AddDamage

Our previous death sequence was a fixed 5 s of 4 sprite puffs and carved
nothing, which is why ships got "a few holes and then disappeared".
"""
import pytest

from engine.appc import death_cascade


class FakeSet:
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)
    def GetName(self):
        return "testset"


class FakeShip:
    """Ship stand-in recording the AddDamage calls the cascade makes."""
    def __init__(self, radius=4.0, lifetime=None):
        self._radius = radius
        self._life = lifetime
        self._set = FakeSet()
        self.damage_calls = []
        self.sample_count = 0
    def GetName(self):          return "Doomed"
    def GetRadius(self):        return self._radius
    def GetContainingSet(self): return self._set
    def GetObjID(self):         return 99
    def GetLifeTime(self):
        return 1.0e30 if self._life is None else self._life
    def GetRandomPointOnModel(self):
        from engine.appc.math import TGPoint3
        self.sample_count += 1
        return TGPoint3(float(self.sample_count), 0.0, 0.0)
    def AddDamage(self, pEmitPos, fRadius, fDamage):
        self.damage_calls.append((pEmitPos, fRadius, fDamage))
    def GetNode(self):
        return None


# ── duration: BC's randomised 5-15 s window ──────────────────────────────────

def test_unset_lifetime_rolls_between_five_and_fifteen_seconds():
    """BC: random(100)/10 + 5. The old engine used a flat 5.0 for every ship."""
    seen = {death_cascade.roll_duration(FakeShip()) for _ in range(200)}
    assert min(seen) >= death_cascade.THROES_MIN
    assert max(seen) < death_cascade.THROES_MAX
    assert len(seen) > 1, "must actually vary per ship, not be a constant"


def test_already_set_lifetime_is_honoured():
    """BC only randomises when the lifetime is still at its >1e6 'unset'
    sentinel; a mission that set one (E7M1's doomed freighter) keeps it."""
    assert death_cascade.roll_duration(FakeShip(lifetime=4.0)) == 4.0


# ── the blast schedule ───────────────────────────────────────────────────────

def test_blasts_are_spaced_on_bcs_quantum():
    """Spacing is random(4) * 0.15, so every gap is a multiple of 0.15 s."""
    times = death_cascade.plan(10.0)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps, "a 10 s window must schedule more than one blast"
    for gap in gaps:
        steps = gap / death_cascade.BLAST_SPACING_UNIT
        assert abs(steps - round(steps)) < 1e-9
        assert 0 <= round(steps) < death_cascade.BLAST_SPACING_STEPS


def test_blast_schedule_covers_the_whole_window():
    times = death_cascade.plan(10.0)
    assert times[0] == 0.0
    assert times[-1] < 10.0


def test_blast_rate_is_several_per_second():
    """BC's mean gap is 0.225 s. A 10 s death is dozens of explosions, not 4 --
    this is the difference the whole change is about."""
    times = death_cascade.plan(10.0)
    assert len(times) >= 20, f"only {len(times)} blasts over 10 s"


def test_zero_spacing_rolls_cannot_hang_the_schedule():
    """GetRandomNumber(4) can return 0, which advances BC's loop by nothing.
    BC tolerates the unbounded worst case; we cap it."""
    death_cascade.plan(15.0, rand=lambda n: 0)  # must terminate
    assert len(death_cascade.plan(15.0, rand=lambda n: 0)) == death_cascade.MAX_BLASTS


# ── firing: explosions carve the hull ────────────────────────────────────────

def test_cascade_carves_the_hull_while_the_ship_dies():
    """The headline behaviour: ~30% of blasts call AddDamage at a fresh point
    on the model, with BC's radius/4 and strength 600."""
    ship = FakeShip(radius=4.0)
    state = death_cascade.begin(ship, duration=10.0)
    for _ in range(int(10.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)

    assert ship.damage_calls, "a full death carved nothing"
    for _pt, radius, strength in ship.damage_calls:
        assert radius == pytest.approx(4.0 * death_cascade.DAMAGE_RADIUS_FRACTION)
        assert strength == pytest.approx(death_cascade.DAMAGE_STRENGTH)


def test_carves_land_at_different_points_on_the_model():
    """Each explosion samples GetRandomPointOnModel afresh, so the holes are
    spread over the hull instead of deepening one crater."""
    ship = FakeShip()
    state = death_cascade.begin(ship, duration=10.0)
    for _ in range(int(10.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    xs = [pt.x for pt, _r, _s in ship.damage_calls]
    assert len(set(xs)) == len(xs), "same point reused for multiple carves"


def test_roughly_thirty_percent_of_blasts_carve():
    """BC: random(10) < 3. Loose bounds -- this guards the constant, not the RNG."""
    ship = FakeShip()
    state = death_cascade.begin(ship, duration=30.0)
    for _ in range(int(30.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    ratio = len(ship.damage_calls) / len(state["blasts"])
    assert 0.15 < ratio < 0.5, f"carve ratio {ratio:.2f} is not ~0.3"


def test_no_carves_before_the_first_frame():
    ship = FakeShip()
    death_cascade.begin(ship, duration=10.0)
    assert ship.damage_calls == []


def test_cascade_stops_carving_once_the_window_closes():
    ship = FakeShip()
    state = death_cascade.begin(ship, duration=5.0)
    for _ in range(int(5.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    settled = len(ship.damage_calls)
    for _ in range(int(5.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    assert len(ship.damage_calls) == settled


# ── the final barrage ────────────────────────────────────────────────────────

def test_final_barrage_fires_near_the_end_of_the_window():
    """BC adds the big finish at fTotalLifeLeft - 2.5."""
    ship = FakeShip()
    state = death_cascade.begin(ship, duration=10.0)
    for _ in range(int(7.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    assert state["final_fired"] is False
    for _ in range(int(1.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    assert state["final_fired"] is True


def test_final_barrage_fires_once_only():
    ship = FakeShip()
    state = death_cascade.begin(ship, duration=10.0)
    fired = 0
    for _ in range(int(12.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
        fired += 1 if state["final_fired"] else 0
    assert state["final_fired"] is True
    # Idempotent: advancing past the end must not re-arm it.
    death_cascade.advance(state, 5.0)
    assert state["final_fired"] is True


def test_short_window_still_gets_its_final_barrage():
    """A mission-set lifetime under the 2.5 s lead (E7M1 uses 4.0; an asteroid
    uses 0.5) must not skip the finish entirely."""
    ship = FakeShip(lifetime=0.5)
    state = death_cascade.begin(ship, duration=0.5)
    for _ in range(int(1.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    assert state["final_fired"] is True


# ── raise-safety: death logic must never depend on VFX ───────────────────────

def test_advance_survives_a_ship_that_raises():
    class Exploding(FakeShip):
        def GetRandomPointOnModel(self):
            raise RuntimeError("no model")
    state = death_cascade.begin(Exploding(), duration=5.0)
    for _ in range(int(5.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)   # must not raise


# ── blast size tiers (Ruling 5: a deliberate departure from BC's fixed
#    fRadius x 0.25, at Mark's request -- "all very even in size") ─────────

def _seeded(seed=7):
    import random
    rng = random.Random(seed)
    return lambda n: rng.randrange(n)


def test_blast_scale_follows_the_tier_table():
    """60% small (0.7-1.0), 30% larger (1.0-1.6), 10% big (1.8-2.6)."""
    rand = _seeded()
    ms = [death_cascade.roll_blast_scale(rand) for _ in range(20000)]
    small = sum(1 for m in ms if 0.7 <= m < 1.0) / len(ms)
    mid = sum(1 for m in ms if 1.0 <= m <= 1.6) / len(ms)
    big = sum(1 for m in ms if 1.8 <= m <= 2.6) / len(ms)
    assert small == pytest.approx(0.60, abs=0.02)
    assert mid == pytest.approx(0.30, abs=0.02)
    assert big == pytest.approx(0.10, abs=0.02)
    assert small + mid + big == pytest.approx(1.0), "every roll lands in a tier"
    assert min(ms) >= 0.7 and max(ms) <= 2.6
    assert max(m for m in ms if m < 1.8) > 1.5, "the middle tier spans its range"


def test_the_tier_table_is_a_dial():
    total = sum(p for p, _lo, _hi in death_cascade.BLAST_SIZE_TIERS)
    assert total == pytest.approx(1.0)
    assert death_cascade.BLAST_SIZE_TIERS == (
        (0.60, 0.7, 1.0), (0.30, 1.0, 1.6), (0.10, 1.8, 2.6))


def test_blast_scale_sizes_the_fireball_the_light_and_the_hole(monkeypatch):
    """m scales the debris explosion and the light, and reaches the VISIBLE
    hole through visible_damage.hole_scale. AddDamage also deals gameplay
    damage (combat.apply_hit), so its own arguments stay BC's."""
    from engine.appc import visible_damage
    seen = {}
    monkeypatch.setattr(death_cascade, "roll_blast_scale", lambda rand: 2.2)
    monkeypatch.setattr(death_cascade, "_debris_explosion",
                        lambda ship, pt, size, rand=None: seen.setdefault("fire", size))
    monkeypatch.setattr(death_cascade, "_light",
                        lambda ship, size: seen.setdefault("light", size))

    class Ship(FakeShip):
        def AddDamage(self, pEmitPos, fRadius, fDamage):
            super().AddDamage(pEmitPos, fRadius, fDamage)
            seen["scale"] = visible_damage.current_hole_scale()

    ship = Ship(radius=4.0)
    state = death_cascade.begin(ship, duration=1.0, rand=lambda n: 0)
    death_cascade._fire(state, sound_ok=False)
    base = 4.0 * death_cascade.BLAST_SIZE_FRACTION
    assert seen["fire"] == pytest.approx(base * 2.2)
    assert seen["light"] == pytest.approx(base * 2.2)
    assert seen["scale"] == pytest.approx(2.2)
    (_pt, r, s), = ship.damage_calls
    assert r == pytest.approx(4.0 * death_cascade.DAMAGE_RADIUS_FRACTION)
    assert s == pytest.approx(death_cascade.DAMAGE_STRENGTH)
    assert visible_damage.current_hole_scale() == 1.0, "scale ends with the call"


# ── Presentation never moves a gameplay roll (presentation RNG; map
#    docs/reference/engine/native-combat/rng-map.md §7.4, §7.5 test 3) ──────

def _doomed_class():
    from engine.appc.objects import ObjectClass

    class Doomed(ObjectClass):
        """A real ObjectClass, so GetRandomPointOnModel draws as a ship's
        does (headless: three gausses on the module random, or on P inside
        a presentation scope); in a set, so the sound and sparks run."""
        def __init__(self):
            super().__init__()
            self.SetTranslateXYZ(10.0, 20.0, 30.0)
            self.SetRadius(4.0)
            self._set = FakeSet()
            self._set.GetEffectRoot = lambda: None
            self.damage_calls = []
        def GetContainingSet(self): return self._set
        def GetLifeTime(self):      return 1.0e30
        def AddDamage(self, pEmitPos, fRadius, fDamage):
            self.damage_calls.append((pEmitPos, fRadius, fDamage))

    return Doomed


def _hexes(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def _whole_death(monkeypatch, noise=None, seed=11):
    """One whole cascade from seeded S1 and S2: the duration, the blast plan,
    every AddDamage (point by .hex(), radius, strength), the points the
    damaging blasts' fireballs were drawn at, and both streams' end state."""
    import random
    import App
    from engine.appc import presentation_rng
    random.seed(seed)
    App.g_kSystemWrapper.SetRandomSeed(seed)
    presentation_rng.reset()
    fired_at = []
    debris = death_cascade._debris_explosion

    def spy(ship, point, size, *a, **k):
        fired_at.append(point)
        return debris(ship, point, size, *a, **k)

    monkeypatch.setattr(death_cascade, "_debris_explosion", spy)
    ship = _doomed_class()()
    duration = death_cascade.roll_duration(ship)
    state = death_cascade.begin(ship, duration)
    plan = list(state["blasts"])
    for _ in range(int((duration + 1.0) * 60)):
        if noise is not None:
            noise(state)
        death_cascade.advance(state, 1.0 / 60.0)
    assert state["final_fired"]
    damage = [(_hexes(p), r, s) for p, r, s in ship.damage_calls]
    # A damaging blast's fireball is at its hole (Review Focus 3).
    assert all(any(p is q for q in fired_at) for p, _r, _s in ship.damage_calls)
    return (duration, plan, damage, App.g_kSystemWrapper._rng.getstate(),
            random.getstate())


def test_presentation_never_moves_a_death_cascade_roll(monkeypatch):
    """The throes, the blast plan, which blasts damage and where, and both
    gameplay streams' end state are the same whether every blast plays a
    sound, the effect level shrinks the final barrage, or presentation
    draws more between blasts."""
    import App
    from engine.appc import presentation_rng
    quiet = _whole_death(monkeypatch)
    assert quiet[2], "the cascade carved nothing"

    def every_sound(state):
        state["last_sound_at"] = None

    def extra_draws(state):
        for _ in range(3):
            presentation_rng.rand(1000)

    assert _whole_death(monkeypatch, every_sound) == quiet
    assert _whole_death(monkeypatch, extra_draws) == quiet
    monkeypatch.setattr(App, "EffectController_GetEffectLevel",
                        lambda: App.EffectController.LOW)
    assert _whole_death(monkeypatch) == quiet


def test_only_a_damaging_blast_draws_its_point_from_the_gameplay_stream(
        monkeypatch):
    """The damage roll comes first; a damaging blast's point is drawn from
    the module random (three gausses headless), a non-damaging one's from P.
    So the module random ends exactly as many points in as there were
    holes."""
    import random
    seed = 11
    damage, s2 = _whole_death(monkeypatch, seed=seed)[2::2]
    ref = random.Random(seed)
    for _ in range(3 * len(damage)):
        ref.gauss(0.0, 1.0)
    assert s2 == ref.getstate()


def test_a_death_cascade_draws_exactly_its_gameplay_rolls_from_s1(monkeypatch):
    """BC's stream (S1) ends a whole cascade exactly the gameplay rolls in:
    the throes randrange(100), the plan's randrange(4) per blast, one
    randrange(10) damage roll per blast, and a damaging blast's size --
    randrange(1000) then randrange(1001), right after its damage roll -- since
    its hole feeds hull breakup (visible_damage.hole_scale -> hull_breakup).
    Nothing else: a non-damaging blast's size, the puffs, the sparks, the
    sound and the final barrage draw P. And it holds under noise: every
    sound, the LOW effect level, extra P draws."""
    import random
    import App
    from engine.appc import presentation_rng
    seed = 11
    quiet = _whole_death(monkeypatch, seed=seed)
    _duration, plan, damage, s1 = quiet[:4]

    ref = random.Random(seed)
    ref.randrange(100)
    for _ in plan:
        ref.randrange(death_cascade.BLAST_SPACING_STEPS)
    damaging = 0
    for _ in plan:
        if ref.randrange(10) < death_cascade.DAMAGE_CHANCE_IN_10:
            damaging += 1
            ref.randrange(1000)
            ref.randrange(1001)
    assert damaging == len(damage) > 0
    assert damaging < len(plan), "some blasts must only show"
    assert s1 == ref.getstate()

    def every_sound(state):
        state["last_sound_at"] = None

    def extra_draws(state):
        for _ in range(3):
            presentation_rng.rand(1000)

    assert _whole_death(monkeypatch, every_sound, seed=seed)[3] == s1
    assert _whole_death(monkeypatch, extra_draws, seed=seed)[3] == s1
    monkeypatch.setattr(App, "EffectController_GetEffectLevel",
                        lambda: App.EffectController.LOW)
    assert _whole_death(monkeypatch, seed=seed)[3] == s1


# ── Scopes cover the SDK builders only (presentation RNG final review M5):
#    Play() runs outside, so nothing it dispatches inline draws from P. ──────

def _scope_recording_effects(monkeypatch):
    """Fake Effects whose builders and actions record whether a presentation
    scope was open when each ran."""
    import sys
    import types
    from engine.appc import presentation_rng
    log = []

    def builder(kind):
        def build(*_a, **_k):
            log.append((kind + " built", presentation_rng.in_scope()))
            return types.SimpleNamespace(
                GetController=lambda: None,
                Play=lambda: log.append((kind + " played",
                                         presentation_rng.in_scope())))
        return build

    monkeypatch.setitem(sys.modules, "Effects", types.SimpleNamespace(
        CreateDebrisExplosion=builder("explosion"),
        CreateDebrisSparks=builder("sparks"),
        GetDeathExplosionSound=lambda ship: "boom"))
    monkeypatch.setattr(death_cascade, "_light", lambda ship, size: None)
    monkeypatch.setattr(death_cascade, "_death_sound", lambda ship: None)
    return log


def test_a_blast_builds_its_fireball_in_the_scope_and_plays_it_outside(
        monkeypatch):
    log = _scope_recording_effects(monkeypatch)
    death_cascade._debris_explosion(FakeShip(), None, 1.0)
    assert log == [("explosion built", True), ("explosion played", False)]


def test_the_final_barrage_builds_in_the_scope_and_plays_outside(monkeypatch):
    log = _scope_recording_effects(monkeypatch)
    ship = FakeShip()
    ship._set.GetEffectRoot = lambda: None
    death_cascade._fire_final(death_cascade.begin(ship, 1.0, rand=lambda n: 0))
    built = [inside for what, inside in log if what.endswith("built")]
    played = [inside for what, inside in log if what.endswith("played")]
    assert built and all(built), log
    assert len(played) == len(built) and not any(played), log
