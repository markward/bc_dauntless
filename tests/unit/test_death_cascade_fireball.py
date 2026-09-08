"""Fireball timing for BC's death cascade (engine/appc/death_cascade.py).

`Effects.CreateDebrisExplosion` hardcodes `SetEmitLife(1.5)` and emits every
0.2 s for `fLife + 1.5` seconds -- 15 puffs per blast, each animating over
1.5 s. At BC's ~4-5 blasts a second that is ~570 overlapping sprites across one
death, which reads as sludge rather than as distinct explosions. And 1.5 s had
already been rejected once as too slow: the death sequence this replaced tuned
its `EXPLOSION_PUFF_LIFE` down to 1.0 for exactly that reason, and deleting it
lost the tuning.

So the cascade overrides both settings on the controller after the SDK helper
returns, the same way the old `_spawn_explosion` did.
"""
import pytest

from engine.appc import death_cascade, explosion_lights, particles


class FakeShip:
    """Ship stand-in carrying the surface a cascade blast touches."""
    def __init__(self, radius=4.0):
        self._radius = radius
    def GetName(self):               return "Doomed"
    def GetRadius(self):             return self._radius
    def GetLifeTime(self):           return 1.0e30
    def GetContainingSet(self):      return None
    def GetNode(self):               return None
    def AddDamage(self, *a):         pass
    def GetRandomPointOnModel(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)


@pytest.fixture(autouse=True)
def _clean():
    particles.reset()
    explosion_lights.reset()
    yield
    particles.reset()
    explosion_lights.reset()


def _one_blast_descriptor():
    state = death_cascade.begin(FakeShip(), duration=10.0)
    death_cascade.advance(state, 1.0 / 60.0)
    ds = particles.snapshot_descriptors()
    assert ds, "the cascade emitted no fireball at all"
    return ds[0]


def test_puff_animates_over_the_tuned_life_not_the_sdk_default():
    """emit_life IS the animation duration -- the renderer derives the
    sprite-sheet cell as frame = (age / life) * columns, so this value alone
    sets how fast a fireball plays."""
    d = _one_blast_descriptor()
    assert d["emit_life"] == pytest.approx(death_cascade.PUFF_LIFE)
    assert death_cascade.PUFF_LIFE < 1.5, "1.5 is the SDK default, already rejected"


def test_a_blast_emits_only_a_few_puffs():
    """Bounded per blast, so an explosion punches instead of blending into its
    neighbours."""
    d = _one_blast_descriptor()
    freq = d["emit_frequency"]
    births = [i for i in range(64) if i * freq <= d["stop_age"] + 1e-9]
    assert death_cascade.PUFFS_MIN <= len(births) <= death_cascade.PUFFS_MAX


def test_blast_puff_count_varies_between_blasts():
    """A fixed count makes every explosion the same size; the cascade should
    mix small pops with fuller bursts."""
    state = death_cascade.begin(FakeShip(), duration=30.0)
    for _ in range(int(30.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)
    # Fireballs only: the final barrage's spark controller has its own
    # stop_age, which would satisfy this without any blast varying at all.
    spans = {round(d["stop_age"], 4)
             for d in particles.snapshot_descriptors()
             if "ExplosionA" in d.get("texture_path", "")}
    assert len(spans) > 1, "every blast emitted for an identical duration"


def test_whole_death_puff_count_is_bounded():
    """The regression this guards: ~570 overlapping puffs across one death.

    The RNG is PINNED. Drawing from App.g_kSystemWrapper makes the blast count
    depend on whatever ran before (a zero spacing roll costs no time, so a
    10 s window can schedule anywhere from ~22 to MAX_BLASTS), which is a
    property of the test order rather than of this code.
    """
    mid = lambda n: n // 2                     # spacing 0.3 s, 3 puffs a blast
    state = death_cascade.begin(FakeShip(), duration=10.0, rand=mid)
    for _ in range(int(10.0 * 60)):
        death_cascade.advance(state, 1.0 / 60.0)

    total = 0
    for d in particles.snapshot_descriptors():
        if "ExplosionA" not in d.get("texture_path", ""):
            continue
        total += len([i for i in range(64)
                      if i * d["emit_frequency"] <= d["stop_age"] + 1e-9])
    assert total < 200, f"{total} puffs across one death (was ~570)"


def test_explosion_light_tracks_the_puff_not_the_emitter():
    """The flash must die with the sprite it lights rather than outliving it --
    the same coupling the old sequence kept between puff life and light life."""
    ship = FakeShip(radius=20.0)
    ship.GetWorldLocation = lambda: type("P", (), {"x": 0.0, "y": 0.0, "z": 0.0})()
    state = death_cascade.begin(ship, duration=10.0)
    death_cascade.advance(state, 1.0 / 60.0)

    lives = [s["life_s"] for s in explosion_lights._sequences]
    assert lives, "no light was scheduled for the blast"
    for life in lives:
        assert life == pytest.approx(death_cascade.PUFF_LIFE)
