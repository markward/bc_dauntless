"""Cosmetic noise never changes a fight (presentation RNG; spec
docs/superpowers/specs/2026-11-02-presentation-rng-design.md §2 goal 6, map
docs/reference/engine/native-combat/rng-map.md §7.5 test 4).

The headless combat_stress fight, driven the host's way WITH GameLoop.tick
(the real AI, which draws on both gameplay streams: the SDK's
``GetRandomNumber`` and the module ``random``), runs twice from the same
seeds (``seed_every_rng``). The second arm injects cosmetic noise every
tick:

* every hit plays its sound (``hit_feedback._audio_should_play`` always
  True), so each hit makes the sound pick the throttle used to skip;
* extra presentation draws (``presentation_rng.rand``);
* a bridge officer's hit and idle animations, built through
  ``build_sequence_clips`` from the SDK's own builders, which draw on the
  SDK's RNG as the live bridge does on every player hit.

Every tick both arms record the K1 differential's per-tick record (weapon
systems and weapons, every ship's death flag, hull condition and shield
faces) plus every subsystem's condition; with the event log (weapon hits
with their payloads, explosions, deaths), the ordered apply_hit log and the
final state of both gameplay streams, they must be equal. Before the
presentation generator existed, all of those cosmetic draws came from the
gameplay streams and the second arm fought a different fight.

The fight is the Python reference (native combat off): this phase is
switch-independent, and the native arm is the differentials' business.
"""
import random

import pytest

import App

from engine import host_loop
from engine.appc import hit_feedback
from engine.appc import native_combat as nc
from engine.appc import presentation_rng
from engine.appc import sensor_contacts
from engine.appc.characters import CharacterClass
from engine.appc.ship_iter import iter_ships
from engine.bridge_idle_gestures import build_sequence_clips
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets
from tests.helpers.k3_fight import compare_calls, seed_every_rng
from tests.helpers import k1_fight as k1d

TICKS = k1d.LOOP_TICKS          # the deaths land inside the window
WARM_UP_TICKS = 60
SEED = 20261102
NOISE_DRAWS = 7                 # presentation draws injected per tick
# The SDK animation builders an officer runs on a hit and when idle.
_OFFICER_BUILDERS = ("Bridge.Characters.CommonAnimations.HitStanding",
                     "Bridge.Characters.CommonAnimations.HitHardStanding",
                     "Bridge.Characters.CommonAnimations.WallSlides")


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


class _AnimPaths:
    def path_for(self, name):
        return "data/animations/%s.nif" % name


class _Scene(k1d._Scene):
    """The K1 differential's scene, recording every subsystem's condition
    too."""

    def record(self):
        super().record()
        self.log[-1].extend(
            (self.label(s), "subsystems", tuple(
                (sub.GetName(), k1d._t(float(sub.GetCondition())))
                for sub in _subsystems(s)))
            for s in self.ships)


def _subsystems(ship):
    out = []
    for sub in ship.GetSubsystems():
        out.append(sub)
        for j in range(sub.GetNumChildSubsystems()):
            out.append(sub.GetChildSubsystem(j))
    return out


def _noise(officer):
    for _ in range(NOISE_DRAWS):
        presentation_rng.rand(1000)
    for builder in _OFFICER_BUILDERS:
        build_sequence_clips(builder, officer, _AnimPaths())


def _arm(monkeypatch, ticks=TICKS, noisy=False):
    """One fresh combat_stress fought through GameLoop.tick (the K1
    differential's loop arm, without its native tallies)."""
    with monkeypatch.context() as mp:
        scene = _Scene(mp, k1d.OFF)
        mp.setenv("DAUNTLESS_NATIVE_COMBAT", "0")
        loop = game_loop.GameLoop()
        assert not nc.enabled()
        k1d._deterministic_loop(mp)
        for ship in scene.ships:
            hull = ship.GetHull()
            hull.SetCondition(hull.GetMaxCondition() * k1d.LOOP_HULL_FRACTION)
            shields = ship.GetShields()
            if shields is not None:
                for face in range(6):
                    shields.SetCurShields(face, 0.0)
        officer = CharacterClass()
        if noisy:
            mp.setattr(hit_feedback, "_audio_should_play",
                       lambda ship, severity: True)
        seed_every_rng(SEED)
        while scene.tick < ticks:
            scene.tick += 1
            if noisy:
                _noise(officer)
            loop.tick()
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=scene.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()   # as the host does (native damage)
            if noisy:
                _noise(officer)
            scene.record()
            sensor_contacts.tick(scene.player,
                                 App.g_kUtopiaModule.GetGameTime())
        scene.streams = (App.g_kSystemWrapper._rng.getstate(),
                         random.getstate())
        return scene


def test_cosmetic_noise_never_changes_the_fight(monkeypatch):
    # A first, discarded arm: the first combat_stress fight in a process
    # diverged from every later one in the K1 harness (its loop test).
    _arm(monkeypatch, ticks=WARM_UP_TICKS)
    ref = _arm(monkeypatch)
    noisy = _arm(monkeypatch, noisy=True)

    # The fight really fought: hits landed, ships exploded and died.
    kinds = k1d._kinds(ref)
    for et in (App.ET_WEAPON_HIT, App.ET_OBJECT_EXPLODING,
               App.ET_OBJECT_DESTROYED):
        assert et in kinds, et
    assert any(c[0] == "apply_hit" for c in ref.calls)

    assert len(ref.log) == len(noisy.log)
    for tick, (a, b) in enumerate(zip(ref.log, noisy.log), start=1):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n quiet %r\n noisy %r" % (
                tick, x, y)
    for i, (x, y) in enumerate(zip(ref.events, noisy.events)):
        assert x == y, "event %d differs:\n quiet %r\n noisy %r" % (i, x, y)
    assert len(ref.events) == len(noisy.events)
    assert ref.queued.rows == noisy.queued.rows
    compare_calls(ref.calls, noisy.calls)
    assert ref.streams[0] == noisy.streams[0], "S1 ends elsewhere"
    assert ref.streams[1] == noisy.streams[1], "S2 ends elsewhere"
