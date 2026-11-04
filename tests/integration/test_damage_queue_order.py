"""Hit effects delivered at the tick boundary, in emission order (native
damage, spec docs/superpowers/specs/2026-11-02-native-damage-design.md M2,
M5, §4.4; controller rulings R7, R8), driven through real mission scripts
and the real collision path:

* E2M2: when one Cardassian explodes, ObjectDestroyed makes the other
  invincible. SPLASH is delivered after ET_OBJECT_EXPLODING, so the partner
  is invincible when its partner's death splash lands, and (M1) takes the
  damage but survives it.
* E3M5: Matan's MatanWeaponHitHandler clamps his hull and power at 15%. Two
  hits in one tick both land; the clamp, delivered at the flush, holds.
* A collision outside the tick scope: its damage lands at once, its effects
  are held (R8) and delivered at the frame's boundary, the kill's
  ET_OBJECT_EXPLODING before its ET_WEAPON_HIT (inventory rule R2).
* The host's frame-end boundary runs after the post-step pass (source
  order).
"""

import App

from engine import host_loop
from engine.appc import combat, effect_queue
from engine.appc.math import TGPoint3
from tests.helpers import headless_mission
from tests.helpers.one_set import share_one_set
from tests.helpers import host_frame_source

E2M2 = "Maelstrom.Episode2.E2M2.E2M2"
E3M5 = "Maelstrom.Episode3.E3M5.E3M5"


def _ship(set_name, name):
    return App.ShipClass_GetObject(App.g_kSetManager.GetSet(set_name), name)


def _alive(ship):
    return not ship.IsDying() and not ship.IsDead()


# ── E2M2: the partner is invincible before the splash, and survives it ───────

def test_e2m2_the_partner_is_invincible_when_the_splash_lands(monkeypatch):
    mission, episode, game, mod = headless_mission.load(E2M2)
    keldon = _ship("Serris2", "Keldon 1")
    galor = _ship("Serris2", "Galor 2")
    assert keldon is not None and galor is not None
    assert not galor.IsInvincible()
    k = keldon.GetWorldLocation()
    galor.SetTranslateXYZ(k.x + 1.0, k.y, k.z)          # inside the blast
    hull = galor.GetHull()
    keldon.SetSplashDamage(hull.GetMaxCondition() * 10.0, 50.0)
    at_splash = []
    real_apply_hit = combat.apply_hit

    def spy(ship, *args, **kwargs):
        if ship is galor:
            at_splash.append(bool(galor.IsInvincible()))
        return real_apply_hit(ship, *args, **kwargs)

    monkeypatch.setattr(combat, "apply_hit", spy)

    keldon.DestroySystem(keldon.GetHull())
    headless_mission.tick(1.0 / 60.0)                   # the boundary

    assert keldon.IsDying() or keldon.IsDead()
    assert at_splash == [True]                          # invincible first
    assert hull.GetCondition() == 0.0                   # the splash landed (M1)
    headless_mission.tick(1.0)
    assert _alive(galor)                                # and cannot die


# ── E3M5: the 15% clamp holds after two same-tick hits ──────────────────────

def test_e3m5_the_clamp_holds_after_two_same_tick_hits():
    mission, episode, game, mod = headless_mission.load(E3M5)
    headless_mission.tick(2.0)
    mod.MatanWarpsIn(None)
    matan = _ship("Belaruz4", "MatanShip")
    assert matan is not None and matan.IsInvincible()
    hull = matan.GetHull()
    full = hull.GetMaxCondition()
    at = matan.GetWorldLocation()
    for _ in range(2):                                  # one tick, two hits
        combat.apply_hit(matan, full * 0.6, at, None, weapon_type="phaser",
                         bypass_shields=True)
    assert hull.GetConditionPercentage() < 0.15         # both landed
    headless_mission.tick(1.0 / 60.0)                   # the boundary
    assert abs(hull.GetConditionPercentage() - 0.15) < 1e-9
    assert matan.GetPowerSubsystem().GetConditionPercentage() >= 0.15 - 1e-9
    assert _alive(matan)


# ── A collision: held, then delivered at the frame's boundary ────────────────

def test_a_collision_reports_at_the_boundary_right_after_its_damage(
        monkeypatch):
    from engine.appc.collisions import resolve_collisions
    from engine.appc.ships import ShipClass_Create
    from engine.rocks.rock import RockClass_Create
    effect_queue.reset()
    ship = ShipClass_Create("Galaxy")
    ship.SetRadius(10.0)
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    rock = RockClass_Create(10.0, name="Held Rock", hull=1.0, mass=100.0)
    rock.SetTranslateXYZ(12.0, 0.0, 0.0)
    rock.SetVelocity(TGPoint3(-5.0, 0.0, 0.0))
    share_one_set(ship, rock)
    seen = []
    real = App.g_kEventManager.AddEvent

    def spy(evt, _real=real):
        if evt.GetDestination() is rock:
            seen.append(evt.GetEventType())
        return _real(evt)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)

    resolve_collisions([ship, rock])

    assert rock.GetHull().GetCondition() == 0.0         # the damage, at once
    assert seen == [App.ET_OBJECT_COLLISION]            # its effects held
    assert not rock.IsDying()
    effect_queue.boundary()                             # the frame's end
    assert rock.IsDying()
    assert App.ET_WEAPON_HIT in seen
    assert (seen.index(App.ET_OBJECT_EXPLODING)
            < seen.index(App.ET_WEAPON_HIT))            # R2
    assert effect_queue.counts()["damage"] > 0


# ── The host's frame-end boundary follows the post-step pass ─────────────────

def _at(src, needle):
    i = src.find(needle)
    assert i >= 0, "%r not found in host_loop.run" % needle
    return i


def test_the_frame_end_boundary_follows_the_post_step_pass():
    """R8: what radiation, hull breakup, collisions, scenery contact and rock
    promotion report is delivered that frame, after all of them, and before
    the scene reconcile reads the frame's result."""
    src = host_frame_source.run_source()
    frame_boundary = _at(src, "_effect_queue.boundary()")
    for call in ("_combat_tick_boundary()", "_radiation_driver.update(",
                 "_hull_breakup.drain()", "collisions.tick_collisions(",
                 "_pump_scenery_contact(", "_pump_rock_promotion("):
        assert _at(src, call) < frame_boundary, call
    assert frame_boundary < _at(src, "_reconcile_scene(")
